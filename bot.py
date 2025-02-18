import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
from google.oauth2.service_account import Credentials

# Load environment variables from .env file
load_dotenv()

# Load sensitive information from environment variables
TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
admin_ids = os.getenv("ADMIN_TELEGRAM_IDS")

# Retrieve admin IDs safely and store them as a list
if admin_ids:
    ADMIN_TELEGRAM_IDS = list(map(int, admin_ids.split(",")))  # Convert to list of integers
else:
    ADMIN_TELEGRAM_IDS = []  # Default to an empty list if not found

# Dictionary to store student submissions (In memory, should be replaced with a database)
submissions = {}

# Dictionary to store teachers and their registered students' submissions
teachers = {}

# Define the function to append data to Google Sheets
async def append_submission_to_sheet(user_name, file_name, submission_time, file_url):
    creds = Credentials.from_service_account_file('service-account.json')
    sheets_service = build('sheets', 'v4', credentials=creds)

    # Your Google Sheet ID (from .env file)
    sheet_id = GOOGLE_SHEET_ID

    # The range where you want to append the data (assuming Sheet1 is your sheet name)
    range_ = "Sheet1!A2:D"  # Adjust the range as per your sheet structure

    # Data to append: [Student Name, File Name, Submission Time, File URL]
    values = [[user_name, file_name, submission_time, file_url]]

    # Prepare the body for the API request
    body = {
        "values": values
    }

    try:
        # Use the Sheets API to append the data
        request = sheets_service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=range_,
            valueInputOption="RAW",  # Use RAW to insert the data exactly as it is
            body=body
        )
        response = request.execute()

        # Print or log the successful response if needed
        print(f"Data successfully appended: {response}")
    except Exception as e:
        print(f"Error appending data to Google Sheets: {e}")

# Start command handler
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name  # Get user's first name

    # If it's an admin, let them know they can manage teachers and submissions
    if user_id in ADMIN_TELEGRAM_IDS:
        await update.message.reply_text(
            f"Hello, {user_name}! You are an admin. Use:\n"
            "/register_teacher <TEACHER_ID> - Register a teacher\n"
            "/view_submissions - View student submissions"
        )
    elif user_id in teachers:
        # Teacher gets notified they have been registered
        admin_id = teachers[user_id]["registered_by"]
        admin_name = context.bot.get_chat(admin_id).first_name
        await update.message.reply_text(
            f"Hello {user_name}, you are a registered teacher! You were invited by {admin_name}. "
            "Use /view_submissions to see students' assignments."
        )
    else:
        await update.message.reply_text("Hello! Send me your assignment file.")

# Handle document submissions (students send their assignments)
async def handle_document(update: Update, context: CallbackContext) -> None:
    file = update.message.document
    file_id = file.file_id
    file_name = file.file_name
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    # Get the current time of the submission
    submission_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Upload the file to Google Drive
    file_url = await upload_to_google_drive(file, file_name)

    # Store the submission metadata in Google Sheets
    await append_submission_to_sheet(user_name, file_name, submission_time, file_url)

    # Store the submission locally for future retrieval
    submissions[user_id] = {
        "file_name": file_name,
        "file_id": file_id,
        "submission_time": submission_time,
        "student_name": user_name,
        "file_url": file_url
    }

    # Notify the student
    await update.message.reply_text(f"✅ Received your file: {file_name} at {submission_time}. You can view it later!")

# Register teacher command (only admins can do this)
async def register_teacher(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id

    # Only an admin can register a teacher
    if user_id in ADMIN_TELEGRAM_IDS:
        if context.args:
            teacher_id = int(context.args[0])  # Convert teacher ID to an integer
            teachers[teacher_id] = {"registered_by": user_id}  # Store teacher's info

            # Await the coroutine to get teacher's name
            teacher_name = (await context.bot.get_chat(teacher_id)).first_name  # Get teacher's name
            admin_name = (await context.bot.get_chat(user_id)).first_name  # Get admin's name

            # Confirm registration with admin
            await update.message.reply_text(
                f"✅ Teacher {teacher_name} (ID: {teacher_id}) has been registered!"
            )
            
            # Send a message to the registered teacher
            await context.bot.send_message(
                chat_id=teacher_id,
                text=f"Hello {teacher_name}, you have been registered as a teacher by {admin_name}. "
                     "Use /view_submissions to see students' assignments."
            )
            
        else:
            await update.message.reply_text("⚠ Please provide the teacher's Telegram ID.")
    else:
        await update.message.reply_text("❌ You are not authorized to register a teacher.")

# View all submissions (for admins or registered teachers)
async def view_submissions(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id

    # Check if the user is an admin or a registered teacher
    if user_id in ADMIN_TELEGRAM_IDS or user_id in teachers:
        if submissions:
            submission_list = "📂 **Student Submissions**:\n"
            
            # Iterate through all the submissions in the submissions dictionary
            for student_id, data in submissions.items():
                # Get the file URL from Google Drive
                file_url = data['file_url']

                # Add submission metadata to the list
                submission_list += (
                    f"👤 **{data['student_name']}**: {data['file_name']} (File ID: {data['file_id']})\n"
                    f"📅 **Submitted at**: {data['submission_time']}\n"
                    f"🔗 **[Download File]({file_url})**\n\n"  # Link to the file in Google Drive
                )

                # Prepare the caption for sending the file
                caption = (
                    f"📂 **Assignment Submission** from {data['student_name']}.\n"
                    f"📅 **Submitted at**: {data['submission_time']}\n"
                    f"🔗 **[Click here to download]({file_url})**"  # File ID link in caption
                )

                # Send the file with the caption to the teacher or admin
                await context.bot.send_document(
                    chat_id=user_id,  # Send to the admin or teacher
                    document=data['file_id'],  # File ID that was uploaded to Google Drive
                    caption=caption,  # Add caption to the document
                    parse_mode='Markdown'  # Ensure Markdown is enabled for link parsing
                )

            # After sending all files, send the list of submissions to the teacher/admin
            await update.message.reply_text(submission_list, parse_mode='Markdown')
        else:
            await update.message.reply_text("📭 No submissions yet.")
    else:
        await update.message.reply_text("❌ You are not authorized to view submissions.")

# Function to upload files to Google Drive
async def upload_to_google_drive(file, file_name):
    creds = Credentials.from_service_account_file('service-account.json')
    drive_service = build('drive', 'v3', credentials=creds)

    # Get the file from Telegram Bot
    file_obj = await file.get_file()
    file_content = await file_obj.download_as_bytearray()

    # Prepare file for upload to Google Drive
    media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype='application/octet-stream')

    # Upload the file to Google Drive folder
    request = drive_service.files().create(
        media_body=media,
        body={
            'name': file_name,
            'parents': [GOOGLE_DRIVE_FOLDER_ID]  # ID of the Google Drive folder where files should be stored
        }
    )
    file_metadata = request.execute()

    file_url = f"https://drive.google.com/file/d/{file_metadata['id']}/view"
    return file_url  # Return the file URL for further use

# Main function to start the bot
def main():
    app = Application.builder().token(TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CommandHandler("register_teacher", register_teacher))
    app.add_handler(CommandHandler("view_submissions", view_submissions))

    app.run_polling()

if __name__ == '__main__':
    main()
