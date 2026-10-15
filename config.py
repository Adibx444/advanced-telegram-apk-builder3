import os
from pathlib import Path

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data")).resolve()
TMP_DIR = Path(os.environ.get("TMP_DIR", "/app/tmp")).resolve()
GRADLE_BIN = os.environ.get("GRADLE_BIN", "/opt/gradle/bin/gradle")
BUILD_TIMEOUT_SECONDS = int(os.environ.get("BUILD_TIMEOUT_SECONDS", "1800"))

ALLOWED_PERMISSIONS = {
    "internet": "android.permission.INTERNET",
    "camera": "android.permission.CAMERA",
    "location": "android.permission.ACCESS_FINE_LOCATION",
    "microphone": "android.permission.RECORD_AUDIO",
    "vibrate": "android.permission.VIBRATE",
}

def prepare_directories():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    for path in (DATA_DIR, TMP_DIR):
        try:
            path.chmod(0o700)
        except OSError:
            pass

def validate_runtime():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing.")
    if not Path("/opt/android-sdk/platforms/android-35").exists():
        raise RuntimeError("Android SDK platform 35 is not installed.")
