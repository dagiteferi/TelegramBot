import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Load environment variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID"))  # Admin ID from .env

# Dictionary to store student submissions (In memory, can be replaced with a database)
submissions = {}

# Define the teacher's Telegram ID (will be set by the admin)
TEACHER_TELEGRAM_ID = None

# Function to check if a file exists (in Telegram's storage)
async def check_file_exists(file_id: str, context: CallbackContext):
    file = await context.bot.get_file(file_id)
    if file:
        print(f"✅ The file exists in Telegram storage: {file.file_id}")
    else:
        print("❌ The file does NOT exist in Telegram storage!")

async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id

    # If it's the admin, let them know they can manage the teacher and submissions
    if user_id == ADMIN_TELEGRAM_ID:
        await update.message.reply_text(f"Hello, Admin! You can manage the teacher and submissions.")
    else:
        await update.message.reply_text("Hello! Send me your assignment file.")

async def handle_document(update: Update, context: CallbackContext) -> None:
    file = update.message.document
    file_id = file.file_id  # Retrieve the file ID
    file_name = file.file_name  # Get the file name
    user_id = update.message.from_user.id  # Unique user ID for the student

    # Check if the file exists in Telegram storage
    await check_file_exists(file_id, context)

    # Store the file metadata (In memory storage, can be replaced with a database)
    submissions[user_id] = {"file_name": file_name, "file_id": file_id}

    # Respond to the student with the file name and confirmation
    await update.message.reply_text(f"Received your file: {file_name} (File ID: {file_id})")

# Command for admin to register teacher's Telegram ID
async def register_teacher(update: Update, context: CallbackContext) -> None:
    global TEACHER_TELEGRAM_ID
    user_id = update.message.from_user.id

    # Only the admin can register the teacher
    if user_id == ADMIN_TELEGRAM_ID:
        if context.args:
            TEACHER_TELEGRAM_ID = context.args[0]  # Get the teacher's ID from arguments
            await update.message.reply_text(f"Teacher registered with Telegram ID: {TEACHER_TELEGRAM_ID}")
        else:
            await update.message.reply_text("Please provide the teacher's Telegram ID.")
    else:
        await update.message.reply_text("You are not authorized to register a teacher.")

# Command to view student submissions (Only admin and teacher can access)
async def view_submissions(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id

    # Check if the user is the admin or teacher
    if user_id == ADMIN_TELEGRAM_ID or user_id == TEACHER_TELEGRAM_ID:
        # List the submissions
        if submissions:
            submission_list = "Student Submissions:\n"
            for student_id, data in submissions.items():
                student_name = context.bot.get_chat(student_id).first_name  # Get student's name
                submission_list += f"{student_name}: {data['file_name']} (File ID: {data['file_id']})\n"
            await update.message.reply_text(submission_list)
        else:
            await update.message.reply_text("No submissions yet.")
    else:
        await update.message.reply_text("You are not authorized to view the submissions.")

def main():
    app = Application.builder().token(TOKEN).build()

    # Start and document handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Command for admin to register teacher
    app.add_handler(CommandHandler("register_teacher", register_teacher))

    # Handler for admin/teacher to view submissions
    app.add_handler(CommandHandler("view_submissions", view_submissions))

    app.run_polling()

if __name__ == '__main__':
    main()
