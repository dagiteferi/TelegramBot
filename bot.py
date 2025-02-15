import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Load environment variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Hello! Send me your assignment file.")

async def handle_document(update: Update, context: CallbackContext) -> None:
    file = update.message.document
    print(f"Received file: {file.file_name}")  # Debug log
    await update.message.reply_text(f"Received your file: {file.file_name}")


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    app.run_polling()

if __name__ == '__main__':
    main()
