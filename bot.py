import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from datetime import datetime

# Load environment variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Retrieve admin IDs safely and store them as a list
admin_ids = os.getenv("ADMIN_TELEGRAM_IDS")

if admin_ids:
    ADMIN_TELEGRAM_IDS = list(map(int, admin_ids.split(",")))  # Convert to list of integers
else:
    ADMIN_TELEGRAM_IDS = []  # Default to an empty list if not found

# Dictionary to store student submissions (In memory, should be replaced with a database)
submissions = {}

# Dictionary to store teachers and their registered students' submissions
teachers = {}

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

async def handle_document(update: Update, context: CallbackContext) -> None:
    file = update.message.document
    file_id = file.file_id
    file_name = file.file_name
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    # Get the current time of the submission
    submission_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Store the submission
    submissions[user_id] = {
        "file_name": file_name,
        "file_id": file_id,
        "submission_time": submission_time,
        "student_name": user_name
    }

    # Notify the student
    await update.message.reply_text(f"✅ Received your file: {file_name} at {submission_time}")

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


# Command to view student submissions (Only admins & assigned teachers can access)
async def view_submissions(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id

    # Check if the user is an admin or a registered teacher
    if user_id in ADMIN_TELEGRAM_IDS or user_id in teachers:
        if submissions:
            submission_list = "📂 Student Submissions:\n"
            for student_id, data in submissions.items():
                submission_list += (
                    f"👤 {data['student_name']}: {data['file_name']} (File ID: {data['file_id']})\n"
                    f"📅 Submitted at: {data['submission_time']}\n\n"
                )
            await update.message.reply_text(submission_list)
        else:
            await update.message.reply_text("📭 No submissions yet.")
    else:
        await update.message.reply_text("❌ You are not authorized to view submissions.")

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
