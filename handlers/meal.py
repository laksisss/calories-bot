import base64
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from database import async_session
from models import User, Meal
from utils.parser import find_in_local_db
from ai_service import analyze_text_meal, analyze_photo
from cache import get_cached_result, set_cached_result, get_image_hash, get_text_hash
from config import FREE_DAILY_LIMIT

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == user.id))
        db_user = result.scalar_one()
        today = datetime.now().strftime("%Y-%m-%d")
        if db_user.last_request_date != today:
            db_user.daily_requests = 0
            db_user.last_request_date = today
        if not db_user.is_pro and db_user.daily_requests >= FREE_DAILY_LIMIT:
            await update.message.reply_text("⚠️ Лимит бесплатных запросов исчерпан (10/день)\n\n💎 Перейди на PRO для безлимита")
            return
        meal_data = find_in_local_db(text)
        if not meal_data:
            cache_key = f"text_{get_text_hash(text)}"
            cached = await get_cached_result(session, cache_key)
            if cached:
                meal_data = cached
            else:
                await update.message.reply_text("🤔 Анализирую...")
                meal_data = await analyze_text_meal(text)
                if meal_data:
                    await set_cached_result(session, cache_key, meal_data)
        if not meal_data:
            await update.message.reply_text("❌ Не удалось распознать блюдо")
            return
        meal = Meal(user_id=db_user.id, date=today, name=meal_data["name"], weight=meal_data["weight"], calories=meal_data["calories"], protein=meal_data["protein"], fat=meal_data["fat"], carbs=meal_data["carbs"])
        session.add(meal)
        db_user.daily_requests += 1
        await session.commit()
    await update.message.reply_text(f"✅ Добавлено:\n\n🍽 {meal_data['name']}\n⚖️ {meal_data['weight']}г\n🔥 {meal_data['calories']} ккал\n🥩 Белки: {meal_data['protein']}г\n Жиры: {meal_data['fat']}г\n🍞 Углеводы: {meal_data['carbs']}г")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == user.id))
        db_user = result.scalar_one()
        today = datetime.now().strftime("%Y-%m-%d")
        if db_user.last_request_date != today:
            db_user.daily_requests = 0
            db_user.last_request_date = today
        if not db_user.is_pro and db_user.daily_requests >= FREE_DAILY_LIMIT:
            await update.message.reply_text("⚠️ Лимит бесплатных запросов исчерпан (10/день)\n\n💎 Перейди на PRO для безлимита")
            return
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        cache_key = f"image_{get_image_hash(bytes(image_bytes))}"
        cached = await get_cached_result(session, cache_key)
        if cached:
            meal_data = cached
        else:
            await update.message.reply_text("📸 Анализирую фото...")
            meal_data = await analyze_photo(image_base64)
            if meal_data:
                await set_cached_result(session, cache_key, meal_data)
        if not meal_data:
            await update.message.reply_text(" Не удалось распознать блюдо на фото")
            return
        meal = Meal(user_id=db_user.id, date=today, name=meal_data["name"], weight=meal_data["weight"], calories=meal_data["calories"], protein=meal_data["protein"], fat=meal_data["fat"], carbs=meal_data["carbs"])
        session.add(meal)
        db_user.daily_requests += 1
        await session.commit()
    await update.message.reply_text(f"✅ Добавлено:\n\n🍽 {meal_data['name']}\n⚖️ {meal_data['weight']}г\n🔥 {meal_data['calories']} ккал\n🥩 Белки: {meal_data['protein']}г\n🥑 Жиры: {meal_data['fat']}г\n🍞 Углеводы: {meal_data['carbs']}г")
