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
            goal = Goal(user_id=user.id)
            session.add(goal)
            await session.commit()
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="stats_today")],
        [InlineKeyboardButton("🎯 Цель", callback_data="show_goal")],
        [InlineKeyboardButton("🏆 Достижения", callback_data="achievements")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "Я помогу тебе отслеживать питание.\n\n"
        "📝 Отправь мне:\n"
        "• Текст: 'рис 200г, курица 150г'\n"
        "• Фото блюда\n\n"
        "🆓 Бесплатно: 10 запросов в день\n"
        "💎 PRO: безлимит",
        reply_markup=reply_markup
    )
