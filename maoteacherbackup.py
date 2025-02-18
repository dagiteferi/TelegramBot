import os
import io
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
)
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2.service_account import Credentials
import time

# Load environment variables
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
ADMIN_TELEGRAM_IDS = list(map(int, os.getenv("ADMIN_TELEGRAM_IDS", "").split(",")))

if not all([TOKEN, GOOGLE_DRIVE_FOLDER_ID, GOOGLE_SHEET_ID]):
    raise ValueError("Missing required environment variables.")

# Global storage
teachers = {}  # Format: {teacher_id: {"name": "Teacher Name", "registered_at": datetime}}
submissions = {}  # Format: {file_name: {student_name, file_name, submission_time, file_url, teacher_id}}
teacher_selection = {}  # Temporary storage for student-teacher selection

# Cache credentials to avoid reloading on every call.
_GOOGLE_CREDENTIALS = None


def get_google_credentials():
    global _GOOGLE_CREDENTIALS
    if _GOOGLE_CREDENTIALS is None:
        _GOOGLE_CREDENTIALS = Credentials.from_service_account_file(
            "service-account.json",
            scopes=[
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/spreadsheets",
            ],
        )
    return _GOOGLE_CREDENTIALS


def load_submissions_from_sheet():
    local_submissions = {}
    creds = get_google_credentials()
    sheets_service = build("sheets", "v4", credentials=creds)

    for attempt in range(3):
        try:
            result = sheets_service.spreadsheets().values().get(
                spreadsheetId=GOOGLE_SHEET_ID, range="Sheet1!A2:E"
            ).execute()
            rows = result.get("values", [])
            for row in rows:
                if len(row) >= 5:
                    user_name, file_name, submission_time, file_url, teacher_id = row[:5]
                    local_submissions[file_name] = {
                        "student_name": user_name,
                        "file_name": file_name,
                        "submission_time": submission_time,
                        "file_url": file_url,
                        "teacher_id": int(teacher_id) if teacher_id else None,
                    }
            break
        except Exception as e:
            print(f"Sheet load attempt {attempt + 1} failed: {e}")
            time.sleep(2)
    return local_submissions


def load_submissions_from_drive():
    local_submissions = {}
    creds = get_google_credentials()
    drive_service = build("drive", "v3", credentials=creds)

    try:
        results = drive_service.files().list(
            q=f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents",
            fields="files(id, name, webViewLink, mimeType)",
            pageSize=100,
        ).execute()
        for file in results.get("files", []):
            local_submissions[file["name"]] = {
                "file_id": file["id"],
                "file_url": file["webViewLink"],
                "file_name": file["name"],
                "mime_type": file["mimeType"],
            }
    except Exception as e:
        print(f"Drive load error: {e}")
    return local_submissions


def load_all_submissions():
    sheet_subs = load_submissions_from_sheet()
    drive_subs = load_submissions_from_drive()
    combined = {}
    # Merge drive data with sheet data
    for name, data in drive_subs.items():
        combined[name] = {
            "student_name": sheet_subs.get(name, {}).get("student_name", "Unknown Student"),
            "file_name": name,
            "submission_time": sheet_subs.get(name, {}).get("submission_time", "Unknown Time"),
            "file_url": data["file_url"],
            "file_id": data["file_id"],
            "mime_type": data["mime_type"],
            "teacher_id": sheet_subs.get(name, {}).get("teacher_id", None),
        }
    return combined


async def upload_to_google_drive(file, file_name):
    creds = get_google_credentials()
    drive_service = build("drive", "v3", credentials=creds)
    telegram_file = await file.get_file()
    file_data = await telegram_file.download_as_bytearray()

    file_metadata = {"name": file_name, "parents": [GOOGLE_DRIVE_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(file_data), mimetype=file.mime_type, chunksize=256 * 1024)

    uploaded_file = await asyncio.to_thread(
        lambda: drive_service.files().create(
            body=file_metadata, media_body=media, fields="id, webViewLink", supportsAllDrives=True
        ).execute()
    )

    await asyncio.to_thread(
        lambda: drive_service.permissions().create(
            fileId=uploaded_file["id"], body={"type": "anyone", "role": "reader"}
        ).execute()
    )
    return uploaded_file["webViewLink"]


async def append_submission_to_sheet(user_name, file_name, submission_time, file_url, teacher_id):
    creds = get_google_credentials()
    sheets_service = build("sheets", "v4", credentials=creds)
    values = [[user_name, file_name, submission_time, file_url, teacher_id]]
    try:
        await asyncio.to_thread(
            lambda: sheets_service.spreadsheets().values().append(
                spreadsheetId=GOOGLE_SHEET_ID,
                range="Sheet1!A2:E",
                valueInputOption="USER_ENTERED",
                body={"values": values},
            ).execute()
        )
    except Exception as e:
        print(f"Sheet append error: {e}")


async def download_file_from_drive(file_id):
    """Download file bytes from Google Drive using MediaIoBaseDownload asynchronously."""

    def _download():
        creds = get_google_credentials()
        drive_service = build("drive", "v3", credentials=creds)
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request, chunksize=256 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        return fh

    return await asyncio.to_thread(_download)


async def start(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id in ADMIN_TELEGRAM_IDS:
        await update.message.reply_text("Admin commands:\n/register_teacher <ID> <NAME>\n/view_submissions")
    elif user_id in teachers:
        await update.message.reply_text("Teacher commands:\n/view_submissions")
    else:
        await update.message.reply_text("Please submit your assignment file.")


async def handle_document(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    file = update.message.document
    file_name = file.file_name

    if file_name in submissions:
        await update.message.reply_text(f"⚠️ {file_name} already exists in submissions.")
        return

    # Store file info temporarily while waiting for teacher selection
    teacher_selection[user_id] = {"file": file, "file_name": file_name}
    await prompt_for_teacher_selection(update, context)


async def prompt_for_teacher_selection(update: Update, context: CallbackContext):
    if not teachers:
        await update.message.reply_text("❌ No teachers available. Please contact an admin.")
        return

    keyboard = [
        [InlineKeyboardButton(teacher["name"], callback_data=f"teacher_{teacher_id}")]
        for teacher_id, teacher in teachers.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Please select your teacher:", reply_markup=reply_markup)


async def handle_teacher_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    teacher_id = int(query.data.split("_")[1])

    if user_id not in teacher_selection:
        await query.edit_message_text("❌ Submission expired. Please try again.")
        return

    file_info = teacher_selection[user_id]
    file = file_info["file"]
    file_name = file_info["file_name"]

    try:
        # Upload to Drive
        file_url = await upload_to_google_drive(file, file_name)

        # Update Sheet
        submission_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await append_submission_to_sheet(
            query.from_user.full_name, file_name, submission_time, file_url, teacher_id
        )

        # Update local cache
        submissions[file_name] = {
            "student_name": query.from_user.full_name,
            "file_name": file_name,
            "submission_time": submission_time,
            "file_url": file_url,
            "teacher_id": teacher_id,
        }

        await query.edit_message_text(f"✅ {file_name} submitted successfully to {teachers[teacher_id]['name']}!")
    except Exception as e:
        await query.edit_message_text(f"❌ Submission failed: {str(e)[:200]}")
    finally:
        del teacher_selection[user_id]  # Clean up


async def register_teacher(update: Update, context: CallbackContext):
    if update.message.from_user.id not in ADMIN_TELEGRAM_IDS:
        await update.message.reply_text("⛔ Permission denied.")
        return

    try:
        teacher_id = int(context.args[0])
        teacher_name = " ".join(context.args[1:]).strip()
        if not teacher_name:
            raise ValueError("Teacher name is required.")

        teachers[teacher_id] = {"name": teacher_name, "registered_at": datetime.now()}
        await update.message.reply_text(f"👨🏫 Teacher {teacher_name} (ID: {teacher_id}) registered successfully.")
    except (IndexError, ValueError) as e:
        await update.message.reply_text(f"❌ Usage: /register_teacher <TELEGRAM_ID> <TEACHER_NAME>")


async def view_submissions(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id

    # Authorization check
    if user_id not in ADMIN_TELEGRAM_IDS and user_id not in teachers:
        await update.message.reply_text("⛔ You don't have permission to view submissions.")
        return

    global submissions
    submissions = load_all_submissions()

    # Filter submissions for teachers
    if user_id in teachers and user_id not in ADMIN_TELEGRAM_IDS:
        filtered = {k: v for k, v in submissions.items() if v["teacher_id"] == user_id}
    else:
        filtered = submissions  # Admins see all

    if not filtered:
        await update.message.reply_text("📭 No submissions found.")
        return

    success_count = 0
    for file_data in filtered.values():
        try:
            file_bytes = await download_file_from_drive(file_data["file_id"])
            caption = (
                f"📄 {file_data['file_name']}\n"
                f"👤 Student: {file_data['student_name']}\n"
                f"⏰ Submitted: {file_data['submission_time']}\n"
                f"🔗 {file_data['file_url']}"
            )
            await update.message.reply_document(
                document=file_bytes,
                filename=file_data["file_name"],
                caption=caption,
                read_timeout=30,
                connect_timeout=30,
                write_timeout=30,
            )
            success_count += 1
            await asyncio.sleep(1)
        except Exception as e:
            error_msg = f"⚠️ Failed to display {file_data['file_name']}: {str(e)[:200]}"
            await update.message.reply_text(error_msg)

    await update.message.reply_text(
        f"📊 Results:\n• Successfully shown: {success_count}\n• Total submissions: {len(filtered)}"
    )


def main():
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register_teacher", register_teacher))
    application.add_handler(CommandHandler("view_submissions", view_submissions))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(handle_teacher_selection, pattern="^teacher_"))

    # Load initial submissions
    global submissions
    submissions = load_all_submissions()

    # Start bot
    application.run_polling()


if __name__ == "__main__":
    main()