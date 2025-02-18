import os
import io
import re
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.service_account import Credentials
from telegram.helpers import escape_markdown

# Load environment variables
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
ADMIN_TELEGRAM_IDS = list(map(int, os.getenv("ADMIN_TELEGRAM_IDS", "").split(",")))

if not all([TOKEN, GOOGLE_DRIVE_FOLDER_ID, GOOGLE_SHEET_ID]):
    raise ValueError("Missing required environment variables.")

teachers = {}
submissions = {}

def get_google_credentials():
    return Credentials.from_service_account_file('service-account.json')

def load_submissions_from_sheet():
    local_submissions = {}
    creds = get_google_credentials()
    sheets_service = build('sheets', 'v4', credentials=creds)
    
    try:
        sheet = sheets_service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID, range="Sheet1!A2:D"
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

def load_submissions_from_drive():
    local_submissions = {}
    creds = get_google_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    
    try:
        results = drive_service.files().list(
            q=f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents",
            fields="files(id, name, webViewLink)"
        ).execute()
        
        for file in results.get('files', []):
            local_submissions[file['name']] = {
                'file_id': file['id'],
                'file_url': file['webViewLink'],
                'file_name': file['name']
            }
    except Exception as e:
        print(f"Error loading submissions from Google Drive: {e}")
    return local_submissions

def load_all_submissions():
    sheet_subs = load_submissions_from_sheet()
    drive_subs = load_submissions_from_drive()
    combined = {}
    for file_name, data in sheet_subs.items():
        combined[file_name] = {
            "student_name": data["student_name"],
            "file_name": file_name,
            "submission_time": data["submission_time"],
            "file_url": drive_subs.get(file_name, {}).get("file_url", data["file_url"])
        }
    for file_name, data in drive_subs.items():
        if file_name not in combined:
            combined[file_name] = {
                "student_name": "Unknown Student",
                "file_name": file_name,
                "submission_time": "Unknown Time",
                "file_url": data["file_url"]
            }
    return combined

async def upload_to_google_drive(file, file_name):
    creds = get_google_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    telegram_file = await file.get_file()
    file_data = await telegram_file.download_as_bytearray()
    file_metadata = {'name': file_name, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(file_data), mimetype=file.mime_type)
    uploaded_file = drive_service.files().create(
        body=file_metadata, media_body=media, fields="id, webViewLink"
    ).execute()
    drive_service.permissions().create(fileId=uploaded_file['id'], body={'type': 'anyone', 'role': 'reader'}).execute()
    return uploaded_file['webViewLink']

async def append_submission_to_sheet(user_name, file_name, submission_time, file_url):
    creds = get_google_credentials()
    sheets_service = build('sheets', 'v4', credentials=creds)
    values = [[user_name, file_name, submission_time, file_url]]
    try:
        sheets_service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID, range="Sheet1!A2:D",
            valueInputOption="RAW", body={"values": values}
        ).execute()
    except Exception as e:
        print(f"Error appending data to Google Sheets: {e}")

async def start(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id in ADMIN_TELEGRAM_IDS:
        await update.message.reply_text("Admin Commands: /register_teacher <ID>, /view_submissions")
    elif user_id in teachers:
        await update.message.reply_text("Teacher Commands: /view_submissions")
    else:
        await update.message.reply_text("Send your assignment file.")

async def handle_document(update: Update, context: CallbackContext):
    file = update.message.document
    file_name = file.file_name
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    submission_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    file_url = await upload_to_google_drive(file, file_name)
    await append_submission_to_sheet(user_name, file_name, submission_time, file_url)
    submissions[user_id] = {"file_name": file_name, "submission_time": submission_time, "student_name": user_name, "file_url": file_url}
    await update.message.reply_text(f"✅ File received: {file_name}")

async def register_teacher(update: Update, context: CallbackContext):
    if update.message.from_user.id in ADMIN_TELEGRAM_IDS and context.args:
        teacher_id = int(context.args[0])
        teachers[teacher_id] = {}
        await update.message.reply_text(f"Teacher {teacher_id} registered.")
    else:
        await update.message.reply_text("Not authorized.")

async def view_submissions(update: Update, context: CallbackContext):
    global submissions
    submissions = load_all_submissions()
    
    if not submissions:
        await update.message.reply_text("No submissions yet.")
    
    for data in submissions.values():
        caption = f"📄 {data['student_name']}\n🕒 {data['submission_time']}\n🔗 [Open File]({data['file_url']})"
        try:
            file_id = data['file_id']
            await update.message.reply_document(
                document=f"https://drive.google.com/uc?id={file_id}",  # Send the file
                caption=escape_markdown(caption, version=2),  # Properly escape the caption for MarkdownV2
                parse_mode=constants.ParseMode.MARKDOWN_V2
            )
        except KeyError:
            # In case there's no file_id (e.g., it's only in the Google Sheet but not uploaded to Drive)
            await update.message.reply_text(f"File {data['file_name']} is missing on Google Drive.")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CommandHandler("register_teacher", register_teacher))
    app.add_handler(CommandHandler("view_submissions", view_submissions))
    app.run_polling()

if __name__ == "__main__":
    main()
