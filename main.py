import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path

from telegram import Update, InputFile, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, ConversationHandler, MessageHandler,
    ContextTypes, filters
)

from config import BOT_TOKEN, DATA_DIR, TMP_DIR, ALLOWED_PERMISSIONS, prepare_directories, validate_runtime
from storage import BuildStorage
from security import validate_png, cleanup_path
from builder import build_release_apk

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=os.environ.get("LOG_LEVEL", "INFO").upper()
)
logger = logging.getLogger("advanced-apk-builder")
(APP_NAME, PACKAGE_ID, VERSION_NAME, VERSION_CODE, ICON, PERMISSIONS, PROJECT) = range(7)

def cleanup_session(context):
    cleanup_path(context.user_data.pop("icon_path", None))
    context.user_data.pop("build_config", None)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Advanced HTML-to-APK Builder চালু আছে!\n\n"
        "Signed Release APK তৈরি করতে /build দাও।\n"
        "ZIP-এর root folder-এ index.html রাখবে।\n\n"
        "Commands: /build /history /status /cancel"
    )

async def build_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_session(context)
    context.user_data["build_config"] = {}
    await update.effective_message.reply_text("ধাপ ১/৭ — অ্যাপের নাম লিখো (যেমন My Web App)।", reply_markup=ReplyKeyboardRemove())
    return APP_NAME

async def app_name_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = (update.effective_message.text or "").strip()
    if not value or len(value) > 50 or any(ord(c) < 32 for c in value):
        await update.effective_message.reply_text("অ্যাপের নাম ১–৫০ অক্ষরের মধ্যে দাও।")
        return APP_NAME
    context.user_data["build_config"]["app_name"] = value
    await update.effective_message.reply_text("ধাপ ২/৭ — Package ID লিখো, যেমন com.mamun.myapp")
    return PACKAGE_ID

async def package_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = (update.effective_message.text or "").strip()
    if len(value) > 200 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*){1,}", value):
        await update.effective_message.reply_text("Package ID সঠিক নয়। উদাহরণ: com.mamun.myapp")
        return PACKAGE_ID
    context.user_data["build_config"]["package_id"] = value
    await update.effective_message.reply_text("ধাপ ৩/৭ — Version name লিখো, যেমন 1.0.0")
    return VERSION_NAME

async def version_name_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = (update.effective_message.text or "").strip()
    if not value or len(value) > 30 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", value):
        await update.effective_message.reply_text("Version name সঠিক নয়। উদাহরণ: 1.0.0")
        return VERSION_NAME
    context.user_data["build_config"]["version_name"] = value
    await update.effective_message.reply_text("ধাপ ৪/৭ — Version code লিখো (যেমন 1)।")
    return VERSION_CODE

async def version_code_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = (update.effective_message.text or "").strip()
    if not value.isdigit() or int(value) < 1 or int(value) > 2100000000:
        await update.effective_message.reply_text("Version code 1 থেকে 2100000000-এর মধ্যে দাও।")
        return VERSION_CODE
    context.user_data["build_config"]["version_code"] = int(value)
    await update.effective_message.reply_text("ধাপ ৫/৭ — PNG icon document হিসেবে পাঠাও, অথবা skip লিখে default icon নাও।")
    return ICON

async def icon_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or "").strip().lower() if update.effective_message else ""
    if text in ("skip", "default", "বাদ", "না"):
        context.user_data["icon_path"] = None
        await ask_permissions(update)
        return PERMISSIONS
    doc = update.effective_message.document if update.effective_message else None
    if not doc or not (doc.file_name or "").lower().endswith(".png"):
        await update.effective_message.reply_text("PNG ফাইল document হিসেবে পাঠাও, অথবা skip লিখো।")
        return ICON
    fd, path = tempfile.mkstemp(prefix="apk-icon-", suffix=".png", dir=TMP_DIR)
    os.close(fd)
    try:
        await (await doc.get_file()).download_to_drive(custom_path=path)
        validate_png(Path(path))
    except Exception as exc:
        cleanup_path(path)
        await update.effective_message.reply_text("PNG icon গ্রহণ করা যায়নি: " + str(exc)[:200])
        return ICON
    cleanup_path(context.user_data.get("icon_path"))
    context.user_data["icon_path"] = path
    await ask_permissions(update)
    return PERMISSIONS

async def ask_permissions(update):
    await update.effective_message.reply_text(
        "ধাপ ৬/৭ — প্রয়োজনীয় permission comma দিয়ে লিখো:\n"
        "internet, camera, location, microphone, vibrate\n"
        "কিছু লাগবে না হলে none লিখো."
    )

async def permissions_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or "").strip().lower()
    if text in ("none", "না", "কিছু না", "skip"):
        permissions = []
    else:
        permissions = list(dict.fromkeys(x.strip() for x in text.split(",") if x.strip()))
        unknown = sorted(set(permissions) - set(ALLOWED_PERMISSIONS))
        if unknown:
            await update.effective_message.reply_text(
                "অজানা permission: " + ", ".join(unknown) +
                "\nঅনুমোদিত: internet, camera, location, microphone, vibrate অথবা none"
            )
            return PERMISSIONS
    context.user_data["build_config"]["permissions"] = permissions
    await update.effective_message.reply_text("ধাপ ৭/৭ — .html, .htm অথবা .zip project পাঠাও। ZIP-এর root-এ index.html থাকতে হবে।")
    return PROJECT

def redact_error(exc):
    message = str(exc)
    if BOT_TOKEN:
        message = message.replace(BOT_TOKEN, "[REDACTED]")
    for key in ("SIGNING_STORE_PASSWORD", "SIGNING_KEY_PASSWORD"):
        secret = os.environ.get(key, "")
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[-2200:]

async def project_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.effective_message.document
    if not doc:
        await update.effective_message.reply_text("একটি .html, .htm অথবা .zip document পাঠাও।")
        return PROJECT
    filename = (doc.file_name or "project").strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in (".html", ".htm", ".zip"):
        await update.effective_message.reply_text("শুধু .html, .htm অথবা .zip ফাইল গ্রহণ করা হবে।")
        return PROJECT

    cfg = dict(context.user_data.get("build_config", {}))
    icon_path = context.user_data.get("icon_path")
    job_dir = Path(tempfile.mkdtemp(prefix="apk-build-", dir=TMP_DIR))
    source_path = job_dir / ("project" + suffix)
    status_message = await update.effective_message.reply_text("⏳ Project download হচ্ছে…")
    storage = context.application.bot_data["storage"]
    build_id = storage.create_build(
        update.effective_user.id, update.effective_chat.id, cfg["app_name"],
        cfg["package_id"], cfg["version_name"], cfg["version_code"]
    )

    loop = asyncio.get_running_loop()

    def status_callback(phase, message):
        storage.update_status(build_id, phase, message)
        # This callback runs in the worker thread; schedule Telegram edits on the event loop.
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                status_message.edit_text(f"⏳ Build #{build_id}\\nStatus: {phase}\\n{message}"),
                loop
            )
            try:
                future.result(timeout=15)
            except Exception:
                pass

    try:
        await (await doc.get_file()).download_to_drive(custom_path=str(source_path))
        await status_message.edit_text(f"⏳ Build #{build_id}: Android project প্রস্তুত হচ্ছে…")
        apk_path = await asyncio.to_thread(
            build_release_apk,
            input_path=source_path,
            input_kind="zip" if suffix == ".zip" else "html",
            icon_path=icon_path,
            app_name=cfg["app_name"],
            package_id=cfg["package_id"],
            version_name=cfg["version_name"],
            version_code=cfg["version_code"],
            permissions=cfg.get("permissions", []),
            workspace=job_dir,
            status_callback=status_callback
        )
        storage.update_status(build_id, "success", "Signed Release APK created and verified", finished=True)
        await status_message.edit_text(f"✅ Build #{build_id} সফল। Signed APK পাঠানো হচ্ছে…")
        with apk_path.open("rb") as f:
            await update.effective_message.reply_document(
                document=InputFile(f, filename="app-release.apk"),
                caption=(
                    f"✅ Signed Release APK\nApp: {cfg['app_name']}\n"
                    f"Package: {cfg['package_id']}\nVersion: {cfg['version_name']} ({cfg['version_code']})\n"
                    f"Build ID: {build_id}"
                ),
                read_timeout=300, write_timeout=300, connect_timeout=30, pool_timeout=30
            )
    except Exception as exc:
        error = redact_error(exc)
        logger.exception("Build %s failed", build_id)
        storage.update_status(build_id, "failed", error, finished=True)
        try:
            await status_message.edit_text(f"❌ Build #{build_id} ব্যর্থ হয়েছে।\n\nকারণ:\n{error[:1700]}")
        except Exception:
            await update.effective_message.reply_text(f"❌ Build #{build_id} ব্যর্থ হয়েছে।")
    finally:
        cleanup_path(job_dir)
        cleanup_path(icon_path)
        context.user_data.pop("icon_path", None)
        context.user_data.pop("build_config", None)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_session(context)
    await update.effective_message.reply_text("Wizard বাতিল হয়েছে। নতুন করে শুরু করতে /build দাও।", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = context.application.bot_data["storage"].history(update.effective_user.id, limit=10)
    if not rows:
        await update.effective_message.reply_text("এখনও কোনো build history নেই। /build দিয়ে শুরু করো।")
        return
    lines = ["📚 সাম্প্রতিক build history:"]
    for row in rows:
        lines.append(f"#{row['id']} · {row['app_name']} · {row['status']}\nPackage: {row['package_id']}\nসময়: {row['created_at']}")
    await update.effective_message.reply_text("\n\n".join(lines))

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active = context.application.bot_data["storage"].latest_active(update.effective_user.id)
    if not active:
        await update.effective_message.reply_text("এখন কোনো active build নেই। আগের build দেখতে /history দাও।")
        return
    await update.effective_message.reply_text(
        f"Build #{active['id']} — {active['app_name']}\nStatus: {active['status']}\n{active['status_message'] or ''}"
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled bot error", exc_info=context.error)

def main():
    prepare_directories()
    validate_runtime()
    storage = BuildStorage(DATA_DIR / "build-history.sqlite3")
    app = Application.builder().token(BOT_TOKEN).build()
    app.bot_data["storage"] = storage
    wizard = ConversationHandler(
        entry_points=[CommandHandler("build", build_command)],
        states={
            APP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, app_name_step)],
            PACKAGE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, package_step)],
            VERSION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, version_name_step)],
            VERSION_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, version_code_step)],
            ICON: [MessageHandler(filters.Document.ALL, icon_step), MessageHandler(filters.TEXT & ~filters.COMMAND, icon_step)],
            PERMISSIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, permissions_step)],
            PROJECT: [MessageHandler(filters.Document.ALL, project_step)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True, per_user=True, allow_reentry=True
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(wizard)
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_error_handler(error_handler)
    logger.info("Advanced HTML-to-APK Builder starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
