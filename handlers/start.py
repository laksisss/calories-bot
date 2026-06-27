from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select
from database import async_session
from models import User, Goal

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == user.id))
        db_user = result.scalar_one_or_none()
        if not db_user:
            db_user = User(telegram_id=user.id, username=user.username, first_name=user.first_name)
            session.add(db_user)
            session.add(Goal(user_id=user.id))
            await session.commit()
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика за день", callback_data="stats_today")],
        [InlineKeyboardButton("🎯 Моя цель", callback_data="show_goal")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
    ]
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "Я помогу отслеживать питание.\n\n"
        "📝 **Как пользоваться:**\n"
        "• Отправь текст: `курица 200г, рис 150г`\n"
        "• Выбери прием пищи из кнопок\n"
        "• Смотри статистику командой /today\n\n"
        "🆓 10 запросов/день бесплатно",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
