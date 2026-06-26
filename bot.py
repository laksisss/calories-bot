import asyncio
import sys
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram import Update
from config import TELEGRAM_TOKEN
from database import init_db
from handlers.start import start_command
from handlers.meal import handle_text, handle_photo
from handlers.stats import stats_today
from handlers.profile import set_goal, show_goal, show_achievements

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def main():
    # Инициализация базы данных
    await init_db()
    
    # Создание приложения
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Регистрация обработчиков
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("today", stats_today))
    app.add_handler(CommandHandler("goal", set_goal))
    app.add_handler(CommandHandler("profile", show_goal))
    app.add_handler(CommandHandler("achievements", show_achievements))
    app.add_handler(CallbackQueryHandler(stats_today, pattern="stats_today"))
    app.add_handler(CallbackQueryHandler(show_goal, pattern="show_goal"))
    app.add_handler(CallbackQueryHandler(show_achievements, pattern="achievements"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🚀 Бот запущен!")
    
    # Запуск polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    # Держим бота запущенным
    await asyncio.Event().wait()

if __name__ == "__main__":
    # Для Windows настраиваем event loop
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # Запускаем главную функцию
    asyncio.run(main())