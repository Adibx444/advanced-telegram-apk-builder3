# Advanced HTML-to-APK Builder Bot

A Telegram bot that packages one HTML file or a ZIP website project into a signed Android Release APK.

## Included features
- Advanced wizard: app name, package ID, version name/code, PNG icon, permissions and project upload
- ZIP project support for local CSS, JavaScript, images and fonts
- Offline support for local assets (external CDN/API resources still need internet)
- WebView with JavaScript, DOM storage and Android Back navigation
- Persistent managed Release signing key
- Build status and SQLite build history
- ZIP path traversal and symlink checks
- Temporary workspace cleanup

## Railway setup
1. Push the repository to GitHub and create a Railway service from it.
2. Set the `BOT_TOKEN` Railway variable.
3. Attach a persistent Volume mounted at `/app/data`.
4. Deploy using the included Dockerfile.
5. In Telegram send `/start`, then `/build`.

Environment variables:
- `BOT_TOKEN` (required)
- `DATA_DIR` (default `/app/data`)
- `TMP_DIR` (default `/app/tmp`)
- `BUILD_TIMEOUT_SECONDS` (default 1800)
- Optional external signing: `SIGNING_KEYSTORE_PATH`, `SIGNING_STORE_PASSWORD`, `SIGNING_KEY_ALIAS`, `SIGNING_KEY_PASSWORD`

The first build creates `/app/data/signing/managed-release.jks` and its password metadata. Back up both securely. If the persistent volume is lost, updates signed with the old key may no longer be possible. Never commit these files or secrets to GitHub.

## Commands
- `/start`
- `/build`
- `/cancel`
- `/status`
- `/history`

## Permissions
Select a comma-separated subset of `internet, camera, location, microphone, vibrate`, or `none`. Manifest permission declarations do not automatically implement Android runtime permission prompts for camera/microphone/geolocation; websites may not be able to use these APIs until runtime handling is added.

## Limits and security
No fixed upload-size limit is imposed by this app. Telegram Bot API limits, Railway memory/storage, build timeout and output delivery limits still apply. ZIP extraction rejects traversal paths and symlinks. Very large or highly compressed archives can still exhaust resources, so monitor the service.

The database stores build metadata only. Source files and APK build output are deleted from temporary storage after each build. This starter bot is best for trusted/private use; public multi-tenant hosting needs authentication, quotas, malware scanning and stronger sandboxing.
