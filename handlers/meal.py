import base64
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from sqlalchemy import select
from database import async_session
from models import User, Meal
from utils.parser import find_in_local_db
from ai_service import analyze_text_meal, analyze_photo
from cache import get_cached_result, set_cached_result, get_image_hash, get_text_hash
from config import FREE_DAILY_LIMIT

SELECT_MEAL_TYPE = 1

MEAL_TYPES = {
    "breakfast": "🌅 Завтрак",
    "lunch": "🍽 Обед", 
    "dinner": "🌙 Ужин",
    "snack": "🍎 Перекус"
}

def split_food_items(text: str) -> list:
    """Разбиваем текст на отдельные продукты"""
    # Сначала по переносам строк
    items = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Если одна строка - пробуем разбить по запятым
    if len(items) == 1 and ',' in text:
        items = [item.strip() for item in text.split(',') if item.strip()]
    
    return items

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == user.id))
        db_user = result.scalar_one_or_none()
        if not db_user:
            await update.message.reply_text("❌ Сначала нажми /start")
            return ConversationHandler.END
        
        today = datetime.now().strftime("%Y-%m-%d")
        if db_user.last_request_date != today:
            db_user.daily_requests = 0
            db_user.last_request_date = today
        
        if not db_user.is_pro and db_user.daily_requests >= FREE_DAILY_LIMIT:
            await update.message.reply_text("⚠️ Лимит 10 запросов/день исчерпан")
            return ConversationHandler.END
        
        # Разбиваем на отдельные продукты
        food_items = split_food_items(text)
        
        if len(food_items) > 1:
            # Несколько продуктов - показываем кнопки
            keyboard = [
                [InlineKeyboardButton(v, callback_data=f"multi_{k}_{text.replace(chr(10), '|').replace(',', ';')}")]
                for k, v in MEAL_TYPES.items()
            ]
            await update.message.reply_text(
                f"📝 Найдено продуктов: {len(food_items)}\n\n" +
                "\n".join(f"• {item}" for item in food_items) +
                "\n\nВыбери прием пищи:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SELECT_MEAL_TYPE
        
        # Один продукт - обрабатываем сразу
        await process_single_food(update, session, db_user, today, food_items[0], "snack")
        return ConversationHandler.END

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == user.id))
        db_user = result.scalar_one_or_none()
        if not db_user:
            await update.message.reply_text("❌ Сначала нажми /start")
            return
        
        today = datetime.now().strftime("%Y-%m-%d")
        if db_user.last_request_date != today:
            db_user.daily_requests = 0
            db_user.last_request_date = today
        
        if not db_user.is_pro and db_user.daily_requests >= FREE_DAILY_LIMIT:
            await update.message.reply_text("⚠️ Лимит исчерпан")
            return
        
        msg = await update.message.reply_text("📸 Анализирую фото через ИИ...")
        
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        
        meal_data = await analyze_photo(bytes(image_bytes))
        
        if not meal_data:
            await msg.edit_text("❌ Не удалось распознать блюдо. Попробуй описать текстом.")
            return
        
        # Показываем результат и спрашиваем прием пищи
        keyboard = [
            [InlineKeyboardButton(v, callback_data=f"photo_{k}_{meal_data['name']}_{meal_data['weight']}_{meal_data['calories']}_{meal_data['protein']}_{meal_data['fat']}_{meal_data['carbs']}")]
            for k, v in MEAL_TYPES.items()
        ]
        
        await msg.edit_text(
            f"🍽 {meal_data['name']}\n"
            f"⚖️ {meal_data['weight']}г\n"
            f"🔥 {meal_data['calories']} ккал\n\n"
            "Выбери прием пищи:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def meal_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора типа приема пищи"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    meal_type = data[1]
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == query.from_user.id))
        db_user = result.scalar_one_or_none()
        if not db_user:
            return
        
        today = datetime.now().strftime("%Y-%m-%d")
        
        if data[0] == "multi":
            # Несколько продуктов из текста
            text = "_".join(data[2:]).replace("|", "\n").replace(";", ",")
            food_items = split_food_items(text)
            
            total_calories = 0
            results = []
            errors = []
            
            for food in food_items:
                meal_data = find_in_local_db(food)
                
                # Если не нашли в базе - спрашиваем ИИ
                if not meal_data:
                    await query.message.reply_text(f"🤔 Ищу '{food}' в базе...")
                    meal_data = await analyze_text_meal(food)
                
                if meal_data:
                    meal = Meal(
                        user_id=db_user.id, date=today, name=meal_data["name"],
                        weight=meal_data["weight"], calories=meal_data["calories"],
                        protein=meal_data["protein"], fat=meal_data["fat"],
                        carbs=meal_data["carbs"], meal_type=meal_type
                    )
                    session.add(meal)
                    total_calories += meal_data["calories"]
                    results.append(f"✅ {meal_data['name']} - {meal_data['calories']} ккал")
                else:
                    errors.append(f"❌ {food}")
            
            db_user.daily_requests += len(food_items)
            await session.commit()
            
            response = f"📊 Добавлено в {MEAL_TYPES[meal_type].lower()}:\n\n"
            if results:
                response += "\n".join(results)
                response += f"\n\n🔥 Всего: {total_calories} ккал"
            if errors:
                response += "\n\nНе распознано:\n" + "\n".join(errors)
            
            await query.edit_message_text(response)
        
        elif data[0] == "photo":
            # Фото
            meal_data = {
                "name": data[2],
                "weight": float(data[3]),
                "calories": float(data[4]),
                "protein": float(data[5]),
                "fat": float(data[6]),
                "carbs": float(data[7])
            }
            
            meal = Meal(
                user_id=db_user.id, date=today, name=meal_data["name"],
                weight=meal_data["weight"], calories=meal_data["calories"],
                protein=meal_data["protein"], fat=meal_data["fat"],
                carbs=meal_data["carbs"], meal_type=meal_type
            )
            session.add(meal)
            db_user.daily_requests += 1
            await session.commit()
            
            await query.edit_message_text(
                f"✅ Добавлено в {MEAL_TYPES[meal_type].lower()}:\n\n"
                f"🍽 {meal_data['name']}\n"
                f"⚖️ {meal_data['weight']}г\n"
                f"🔥 {meal_data['calories']} ккал\n"
                f"🥩 Б: {meal_data['protein']}г | 🥑 Ж: {meal_data['fat']}г | 🍞 У: {meal_data['carbs']}г"
            )

async def process_single_food(update, session, db_user, today, text, meal_type="snack"):
    """Обработка одного продукта"""
    meal_data = find_in_local_db(text)
    
    # Если не нашли в локальной базе - спрашиваем ИИ
    if not meal_data:
        await update.message.reply_text(f"🤔 Ищу '{text}' через ИИ...")
        cache_key = f"text_{get_text_hash(text)}"
        cached = await get_cached_result(session, cache_key)
        if cached:
            meal_data = cached
        else:
            meal_data = await analyze_text_meal(text)
            if meal_data:
                await set_cached_result(session, cache_key, meal_data)
    
    if not meal_data:
        await update.message.reply_text(f"❌ Не удалось распознать '{text}'. Попробуй указать вес иначе.")
        return
    
    meal = Meal(
        user_id=db_user.id, date=today, name=meal_data["name"],
        weight=meal_data["weight"], calories=meal_data["calories"],
        protein=meal_data["protein"], fat=meal_data["fat"],
        carbs=meal_data["carbs"], meal_type=meal_type
    )
    session.add(meal)
    db_user.daily_requests += 1
    await session.commit()
    
    await update.message.reply_text(
        f"✅ {meal_data['name']}\n"
        f"⚖️ {meal_data['weight']}г\n"
        f"🔥 {meal_data['calories']} ккал\n"
        f"🥩 Б: {meal_data['protein']}г | 🥑 Ж: {meal_data['fat']}г | 🍞 У: {meal_data['carbs']}г"
    )
