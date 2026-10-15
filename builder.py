import json
import os
import secrets
import shutil
import subprocess
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr
from PIL import Image, ImageDraw

from config import DATA_DIR, GRADLE_BIN, BUILD_TIMEOUT_SECONDS, ALLOWED_PERMISSIONS
from security import safe_extract_zip

AGP_VERSION = "8.7.3"
COMPILE_SDK = 35
BUILD_TOOLS = "35.0.0"

def run_command(command, cwd=None, env=None, timeout=None):
    proc = subprocess.run(command, cwd=cwd, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=timeout, check=False)
    if proc.returncode:
        raise RuntimeError("Command failed: " + " ".join(map(str, command)) + "\n" + (proc.stdout or "")[-10000:])
    return proc.stdout or ""

def ensure_managed_signing():
    external = os.environ.get("SIGNING_KEYSTORE_PATH", "").strip()
    if external:
        path = Path(external).resolve()
        store_password = os.environ.get("SIGNING_STORE_PASSWORD", "")
        alias = os.environ.get("SIGNING_KEY_ALIAS", "releasekey")
        key_password = os.environ.get("SIGNING_KEY_PASSWORD", store_password)
        if not path.is_file() or not store_password or not key_password:
            raise RuntimeError("External signing configuration is incomplete.")
        return path, store_password, alias, key_password

    folder = DATA_DIR / "signing"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        folder.chmod(0o700)
    except OSError:
        pass
    keystore = folder / "managed-release.jks"
    metadata = folder / "managed-signing.json"

    if keystore.exists() and metadata.exists():
        info = json.loads(metadata.read_text(encoding="utf-8"))
        return keystore, info["store_password"], info["key_alias"], info["key_password"]
    if keystore.exists() != metadata.exists():
        raise RuntimeError("Managed signing files are incomplete. Restore the persistent volume backup; refusing to create a replacement key.")

    password = secrets.token_urlsafe(36)
    alias = "managedrelease"
    run_command([
        "keytool", "-genkeypair", "-noprompt", "-keystore", str(keystore),
        "-storetype", "JKS", "-storepass", password, "-keypass", password,
        "-alias", alias, "-keyalg", "RSA", "-keysize", "3072", "-validity", "10000",
        "-dname", "CN=Managed APK Builder, OU=Release, O=Private, L=Unknown, ST=Unknown, C=US"
    ], timeout=90)
    metadata.write_text(json.dumps({"store_password": password, "key_password": password, "key_alias": alias}, indent=2), encoding="utf-8")
    try:
        keystore.chmod(0o600)
        metadata.chmod(0o600)
    except OSError:
        pass
    return keystore, password, alias, password

def make_icon(icon_path, res_dir):
    sizes = {"mipmap-mdpi":48, "mipmap-hdpi":72, "mipmap-xhdpi":96, "mipmap-xxhdpi":144, "mipmap-xxxhdpi":192}
    if icon_path and Path(icon_path).is_file():
        with Image.open(icon_path) as im:
            base = im.convert("RGBA")
    else:
        base = Image.new("RGBA", (512,512), (37,99,235,255))
        draw = ImageDraw.Draw(base)
        draw.rounded_rectangle((90,90,422,422), radius=70, fill=(255,255,255,255))
        draw.rectangle((175,185,337,325), fill=(37,99,235,255))
    for folder, size in sizes.items():
        d = res_dir / folder
        d.mkdir(parents=True, exist_ok=True)
        image = base.copy()
        image.thumbnail((size,size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA",(size,size),(0,0,0,0))
        canvas.alpha_composite(image, ((size-image.width)//2,(size-image.height)//2))
        canvas.save(d / "ic_launcher.png", "PNG")

def create_android_project(project_dir, app_name, package_id, version_name, version_code, permissions, icon_path):
    app = project_dir / "app"
    java_dir = app / "src/main/java" / Path(*package_id.split("."))
    res_dir = app / "src/main/res"
    assets_dir = app / "src/main/assets/site"
    java_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    (project_dir / "settings.gradle").write_text("\n".join([
        "pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }",
        "dependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }",
        "rootProject.name = 'GeneratedWebApp'",
        "include ':app'",
        ""
    ]), encoding="utf-8")
    (project_dir / "build.gradle").write_text(
        "plugins { id 'com.android.application' version '" + AGP_VERSION + "' apply false }\n",
        encoding="utf-8"
    )
    (project_dir / "gradle.properties").write_text(
        "org.gradle.jvmargs=-Xmx1536m -Dfile.encoding=UTF-8\nandroid.useAndroidX=true\norg.gradle.parallel=false\n",
        encoding="utf-8"
    )
    app_gradle = "\n".join([
        "plugins { id 'com.android.application' }",
        "android {",
        f"    namespace '{package_id}'",
        f"    compileSdk {COMPILE_SDK}",
        "    defaultConfig {",
        f"        applicationId '{package_id}'",
        "        minSdk 23",
        "        targetSdk 35",
        f"        versionCode {version_code}",
        f"        versionName {quoteattr(version_name)}",
        "    }",
        "    signingConfigs {",
        "        release {",
        "            storeFile file(System.getenv('SIGNING_KEYSTORE_PATH'))",
        "            storePassword System.getenv('SIGNING_STORE_PASSWORD')",
        "            keyAlias System.getenv('SIGNING_KEY_ALIAS')",
        "            keyPassword System.getenv('SIGNING_KEY_PASSWORD')",
        "        }",
        "    }",
        "    buildTypes { release { signingConfig signingConfigs.release; minifyEnabled false } }",
        "    compileOptions { sourceCompatibility JavaVersion.VERSION_17; targetCompatibility JavaVersion.VERSION_17 }",
        "}",
        ""
    ])
    (app / "build.gradle").write_text(app_gradle, encoding="utf-8")

    permission_xml = "\n".join(
        f'    <uses-permission android:name="{ALLOWED_PERMISSIONS[key]}" />'
        for key in permissions if key in ALLOWED_PERMISSIONS
    )
    manifest = "\n".join([
        '<?xml version="1.0" encoding="utf-8"?>',
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">',
        permission_xml,
        '  <application android:allowBackup="false" android:label=' + quoteattr(app_name) + ' android:icon="@mipmap/ic_launcher" android:usesCleartextTraffic="false" android:theme="@style/AppTheme">',
        '    <activity android:name=".MainActivity" android:configChanges="keyboard|keyboardHidden|orientation|screenSize" android:exported="true">',
        '      <intent-filter><action android:name="android.intent.action.MAIN" /><category android:name="android.intent.category.LAUNCHER" /></intent-filter>',
        '    </activity>',
        '  </application>',
        '</manifest>',
        ''
    ])
    (app / "src/main/AndroidManifest.xml").write_text(manifest, encoding="utf-8")

    (res_dir / "values").mkdir(parents=True, exist_ok=True)
    (res_dir / "values/styles.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources><style name="AppTheme" parent="@android:style/Theme.Material.Light.NoActionBar"><item name="android:fontFamily">sans</item><item name="android:colorAccent">#2563EB</item></style></resources>\n',
        encoding="utf-8"
    )
    (res_dir / "values-night").mkdir(parents=True, exist_ok=True)
    (res_dir / "values-night/styles.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources><style name="AppTheme" parent="@android:style/Theme.Material.NoActionBar"><item name="android:fontFamily">sans</item><item name="android:colorAccent">#93C5FD</item></style></resources>\n',
        encoding="utf-8"
    )

    java = "\n".join([
        f"package {package_id};",
        "import android.app.Activity;",
        "import android.os.Bundle;",
        "import android.webkit.WebSettings;",
        "import android.webkit.WebView;",
        "import android.webkit.WebViewClient;",
        "import android.webkit.WebChromeClient;",
        "import android.os.Build;",
        "import android.webkit.WebResourceRequest;",
        "public class MainActivity extends Activity {",
        "  private WebView webView;",
        "  @Override protected void onCreate(Bundle savedInstanceState) {",
        "    super.onCreate(savedInstanceState);",
        "    webView = new WebView(this);",
        "    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) webView.setForceDarkAllowed(true);",
        "    WebSettings settings = webView.getSettings();",
        "    settings.setJavaScriptEnabled(true);",
        "    settings.setDomStorageEnabled(true);",
        "    settings.setAllowFileAccess(true);",
        "    settings.setAllowContentAccess(true);",
        "    settings.setLoadsImagesAutomatically(true);",
        "    settings.setSupportZoom(true);",
        "    settings.setBuiltInZoomControls(false);",
        "    webView.setWebViewClient(new WebViewClient() {",
        "      @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) { return false; }",
        "    });",
        "    webView.setWebChromeClient(new WebChromeClient());",
        "    setContentView(webView);",
        '    if (savedInstanceState == null) webView.loadUrl("file:///android_asset/site/index.html"); else webView.restoreState(savedInstanceState);',
        "  }",
        "  @Override protected void onSaveInstanceState(Bundle outState) { super.onSaveInstanceState(outState); if (webView != null) webView.saveState(outState); }",
        "  @Override public void onBackPressed() { if (webView != null && webView.canGoBack()) webView.goBack(); else super.onBackPressed(); }",
        "  @Override protected void onDestroy() { if (webView != null) { webView.stopLoading(); webView.destroy(); } super.onDestroy(); }",
        "}",
        ""
    ])
    (java_dir / "MainActivity.java").write_text(java, encoding="utf-8")
    make_icon(icon_path, res_dir)
    return assets_dir

def build_release_apk(input_path, input_kind, icon_path, app_name, package_id, version_name, version_code, permissions, workspace, status_callback=None):
    workspace = Path(workspace).resolve()
    project_dir = workspace / "android-project"
    web_dir = workspace / "web-project"
    project_dir.mkdir(parents=True, exist_ok=True)
    web_dir.mkdir(parents=True, exist_ok=True)

    def status(phase, message):
        if status_callback:
            try:
                status_callback(phase, message)
            except Exception:
                pass

    status("preparing", "Preparing and validating project")
    if input_kind == "zip":
        safe_extract_zip(Path(input_path), web_dir)
    else:
        shutil.copy2(input_path, web_dir / "index.html")

    assets_dir = create_android_project(project_dir, app_name, package_id, version_name, version_code, permissions, icon_path)
    shutil.copytree(web_dir, assets_dir, dirs_exist_ok=True)
    if not (assets_dir / "index.html").is_file():
        raise RuntimeError("index.html not found in project root.")

    status("signing", "Preparing managed release signing key")
    keystore, store_password, alias, key_password = ensure_managed_signing()
    env = os.environ.copy()
    env.update({
        "SIGNING_KEYSTORE_PATH": str(keystore),
        "SIGNING_STORE_PASSWORD": store_password,
        "SIGNING_KEY_ALIAS": alias,
        "SIGNING_KEY_PASSWORD": key_password,
        "ANDROID_HOME": env.get("ANDROID_HOME", "/opt/android-sdk"),
        "ANDROID_SDK_ROOT": env.get("ANDROID_SDK_ROOT", "/opt/android-sdk"),
    })
    status("building", "Gradle is compiling the signed Release APK")
    output = run_command([GRADLE_BIN, "--no-daemon", "--stacktrace", "assembleRelease"],
                         cwd=project_dir, env=env, timeout=BUILD_TIMEOUT_SECONDS)
    apk = project_dir / "app/build/outputs/apk/release/app-release.apk"
    if not apk.is_file():
        raise RuntimeError("Gradle completed but APK output was not found.\n" + output[-5000:])
    apksigner = Path(env["ANDROID_HOME"]) / "build-tools" / BUILD_TOOLS / "apksigner"
    status("signing", "Verifying APK signature")
    run_command([str(apksigner), "verify", "--verbose", str(apk)], env=env, timeout=60)
    return apk
