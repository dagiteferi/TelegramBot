import os
import firebase_admin
from firebase_admin import credentials, storage
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Load environment variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Initialize Firebase Admin SDK
cred = credentials.Certificate('firebase_credentials.json')  # Use your correct credentials file path
firebase_admin.initialize_app(cred, {
    'storageBucket': 'assignmentsubmitbot-a29a3.appspot.com'  # Correct Firebase Storage bucket name
})

# Firebase Storage Bucket
bucket = storage.bucket()

# Function to check if a file exists in Firebase Storage
def check_file_exists(file_name: str):
    blob = bucket.blob(f"assignments/{file_name}")
    if blob.exists():
        print(f"The file {file_name} exists in Firebase Storage.")
    else:
        print(f"The file {file_name} does not exist in Firebase Storage.")

async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Hello! Send me your assignment file.")

async def handle_document(update: Update, context: CallbackContext) -> None:
    file = update.message.document
    file_name = file.file_name

    # Ensure the "temp" directory exists
    os.makedirs("temp", exist_ok=True)  # Create "temp" directory if it doesn't exist

    # Download the file from Telegram using context.bot
    file_id = file.file_id
    new_file = await context.bot.get_file(file_id)
    file_path = f"temp/{file_name}"

    # Download file to the local system
    await new_file.download_to_drive(file_path)
    
    # Upload the file to Firebase Storage
    blob = bucket.blob(f"assignments/{file_name}")
    blob.upload_from_filename(file_path)

    # Check if the file is successfully uploaded
    check_file_exists(file_name)

    # Respond to the user
    await update.message.reply_text(f"Received and uploaded your file: {file_name}")

    # Optionally delete the local file after uploading
    os.remove(file_path)


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    app.run_polling()

if __name__ == '__main__':
    main()
