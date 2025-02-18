import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
from google.oauth2.service_account import Credentials

# Load environment variables
load_dotenv()

# Bot and Google API credentials
TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

if not TOKEN:
    raise ValueError("BOT_TOKEN is missing or not set.")
if not GOOGLE_DRIVE_FOLDER_ID:
    raise ValueError("GOOGLE_DRIVE_FOLDER_ID is missing or not set.")
if not GOOGLE_SHEET_ID:
    raise ValueError("GOOGLE_SHEET_ID is missing or not set.")

admin_ids = os.getenv("ADMIN_TELEGRAM_IDS")
ADMIN_TELEGRAM_IDS = list(map(int, admin_ids.split(","))) if admin_ids else []

# Dictionary to store teachers
teachers = {}

# Load submissions from Google Sheets
def load_submissions_from_sheet():
    local_submissions = {}
    creds = Credentials.from_service_account_file('service-account.json')
    sheets_service = build('sheets', 'v4', credentials=creds)

    try:
        sheet = sheets_service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range="Sheet1!A2:D"  # Adjust if needed
        ).execute()
        rows = sheet.get('values', [])

        for row in rows:
            if len(row) == 4:
                user_name, file_name, submission_time, file_url = row
                local_submissions[file_name] = {
                    'student_name': user_name,
                    'file_name': file_name,
                    'submission_time': submission_time,
                    'file_url': file_url
                }
    except Exception as e:
        print(f"Error loading submissions from Google Sheets: {e}")

    return local_submissions

# Load submissions from Google Drive
def load_submissions_from_drive():
    local_submissions = {}
    creds = Credentials.from_service_account_file('service-account.json')
    drive_service = build('drive', 'v3', credentials=creds)

    try:
        results = drive_service.files().list(
            q=f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents",
            fields="files(id, name, webViewLink)"
        ).execute()

        for file in results.get('files', []):
            file_name = file['name']
            file_id = file['id']
            file_url = file['webViewLink']
            local_submissions[file_name] = {
                'file_id': file_id,
                'file_url': file_url,
                'file_name': file_name
            }
    except Exception as e:
        print(f"Error loading submissions from Google Drive: {e}")

    return local_submissions

# Merge data from Google Sheets and Google Drive
def load_all_submissions():
    submissions_from_sheet = load_submissions_from_sheet()
    submissions_from_drive = load_submissions_from_drive()

    combined_submissions = {}

    for file_name, data in submissions_from_sheet.items():
        if file_name in submissions_from_drive:
            combined_submissions[file_name] = {
                "student_name": data["student_name"],
                "file_name": file_name,
                "submission_time": data["submission_time"],
                "file_url": submissions_from_drive[file_name]["file_url"]
            }
        else:
            combined_submissions[file_name] = data

    for file_name, data in submissions_from_drive.items():
        if file_name not in combined_submissions:
            combined_submissions[file_name] = {
                "student_name": "Unknown Student",
                "file_name": file_name,
                "submission_time": "Unknown Time",
                "file_url": data["file_url"]
            }

    return combined_submissions

submissions = load_all_submissions()

# Upload file to Google Drive
async def upload_to_google_drive(file, file_name):
    creds = Credentials.from_service_account_file('service-account.json')
    drive_service = build('drive', 'v3', credentials=creds)

    telegram_file = await file.get_file()
    file_data = await telegram_file.download_as_bytearray()

    file_metadata = {'name': file_name, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(file_data), mimetype=file.mime_type)
    uploaded_file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink"
    ).execute()

    # Set file to be publicly accessible
    permission = {
        'type': 'anyone',
        'role': 'reader'
    }
    drive_service.permissions().create(fileId=uploaded_file['id'], body=permission).execute()

    return uploaded_file['webViewLink']


# Append submission to Google Sheets
async def append_submission_to_sheet(user_name, file_name, submission_time, file_url):
    creds = Credentials.from_service_account_file('service-account.json')
    sheets_service = build('sheets', 'v4', credentials=creds)

    if not GOOGLE_SHEET_ID:
        print("Error: GOOGLE_SHEET_ID is missing.")
        return

    values = [[user_name, file_name, submission_time, file_url]]
    body = {"values": values}

    try:
        request = sheets_service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range="Sheet1!A2:D",
            valueInputOption="RAW",
            body=body
        )
        request.execute()
    except Exception as e:
        print(f"Error appending data to Google Sheets: {e}")

# Start command
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    if user_id in ADMIN_TELEGRAM_IDS:
        await update.message.reply_text(
            f"Hello, {user_name}! You are an admin. Use:\n"
            "/register_teacher <TEACHER_ID> - Register a teacher\n"
            "/view_submissions - View student submissions"
        )
    elif user_id in teachers:
        await update.message.reply_text("Hello Teacher! Use /view_submissions to see assignments.")
    else:
        await update.message.reply_text("Hello! Send me your assignment file.")

# Handle document submissions
async def handle_document(update: Update, context: CallbackContext) -> None:
    file = update.message.document
    file_name = file.file_name
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    submission_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    file_url = await upload_to_google_drive(file, file_name)
    await append_submission_to_sheet(user_name, file_name, submission_time, file_url)

    submissions[user_id] = {
        "file_name": file_name,
        "submission_time": submission_time,
        "student_name": user_name,
        "file_url": file_url
    }

    await update.message.reply_text(f"✅ Received your file: {file_name} at {submission_time}.")

# Register teacher command
async def register_teacher(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id

    if user_id in ADMIN_TELEGRAM_IDS:
        if context.args:
            teacher_id = int(context.args[0])
            teachers[teacher_id] = {"registered_by": user_id}

            teacher_name = (await context.bot.get_chat(teacher_id)).first_name
            await update.message.reply_text(f"✅ Teacher {teacher_name} registered!")

            await context.bot.send_message(
                chat_id=teacher_id,
                text=f"Hello {teacher_name}, you are now registered as a teacher."
            )
        else:
            await update.message.reply_text("⚠ Provide the teacher's Telegram ID.")
    else:
        await update.message.reply_text("❌ Not authorized.")

import telegram
import re

async def view_submissions(update: Update, context: CallbackContext) -> None:
    global submissions
    submissions = load_all_submissions()

    if not submissions:
        await update.message.reply_text("No submissions yet.")
    else:
        for file_name, data in submissions.items():
            student_name = data.get("student_name", "Unknown Student")
            submission_time = data.get("submission_time", "Unknown Time")
            file_url = data.get("file_url", "")

            # Escape markdown special characters
            student_name = re.sub(r"([_*[\]()~`>#+-=|{}.!])", r"\\\1", student_name)
            
            if not file_url:
                await update.message.reply_text(f"⚠️ **{student_name}** submitted a file, but the URL is missing.")
                continue  # Skip sending the document if the URL is empty

            caption = f"📄 **{student_name}**\n🕒 {submission_time}\n🔗 [Open File]({file_url})"

            try:
                await context.bot.send_document(
                    chat_id=update.message.chat_id,
                    document=file_url,
                    caption=caption,
                    parse_mode=telegram.constants.ParseMode.MARKDOWN
                )
            except telegram.error.BadRequest as e:
                await update.message.reply_text(f"⚠️ Error sending file for {student_name}: {e}")


# Run bot
def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CommandHandler("register_teacher", register_teacher))
    application.add_handler(CommandHandler("view_submissions", view_submissions))
    application.run_polling()

if __name__ == "__main__":
    main()
