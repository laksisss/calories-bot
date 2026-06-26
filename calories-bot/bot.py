import os
import json
import base64
import logging
import requests
import httpx
from datetime import datetime, date
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN     = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
NOTION_TOKEN       = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

WAITING_WEIGHT = 1

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ── Память на блюда (в памяти процесса) ──────────────────
# { "dish_key": { "kcal_per_100g": x, "protein_per_100g": x, ... } }
dish_memory: dict = {}

def dish_key(name: str) -> str:
    return name.lower().strip()

# ── Claude: анализ фото ───────────────────────────────────
def analyze_photo(image_bytes: bytes) -> dict:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    prompt = """Ты — нутрициолог. Посмотри на фото еды и определи:
1. Название блюда (коротко, 2-4 слова)
2. КБЖУ на 100 г (примерно, с учётом типичного способа приготовления)

Ответь ТОЛЬКО валидным JSON без markdown:
{
  "dish_name": "название",
  "kcal_per_100g": число,
  "protein_per_100g": число,
  "fat_per_100g": число,
  "carbs_per_100g": число,
  "confidence": "high/medium/low"
}"""

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": "claude-opus-4-6",
            "max_tokens": 500,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64
                        }
                    },
                    {"type": "text", "text": prompt}
                ]
            }]
        },
        timeout=30
    )
    response.raise_for_status()
    raw = response.json()["content"][0]["text"].strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

# ── Claude: парсинг текстового ввода ─────────────────────
def parse_text_meal(text: str) -> dict:
    prompt = f"""Пользователь написал о еде: "{text}"

Извлеки название блюда, вес в граммах и рассчитай КБЖУ.
Если вес не указан — предположи стандартную порцию.

Ответь ТОЛЬКО валидным JSON без markdown:
{{
  "dish_name": "название",
  "weight_g": число,
  "kcal_total": число,
  "protein_g": число,
  "fat_g": число,
  "carbs_g": число,
  "note": "короткое пояснение"
}}"""

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": "claude-opus-4-6",
            "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=30
    )
    response.raise_for_status()
    raw = response.json()["content"][0]["text"].strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

# ── Notion: записать приём ────────────────────────────────
def log_to_notion(dish_name: str, weight_g: float,
                  kcal: float, protein: float, fat: float, carbs: float):
    today = date.today().isoformat()
    now   = datetime.now().strftime("%H:%M")

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Name":     {"title":  [{"text": {"content": f"{dish_name} ({now})"}}]},
            "Дата":     {"date":   {"start": today}},
            "ККАЛ":     {"number": round(kcal, 1)},
            "Белки":    {"number": round(protein, 1)},
            "Жиры":     {"number": round(fat, 1)},
            "Углеводы": {"number": round(carbs, 1)},
            "Вес (г)":  {"number": round(weight_g, 1)}
        }
    }
    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=NOTION_HEADERS,
        json=payload
    )
    r.raise_for_status()

# ── Notion: статистика за сегодня ─────────────────────────
def get_today_stats() -> dict:
    today = date.today().isoformat()
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
        headers=NOTION_HEADERS,
        json={"filter": {"property": "Дата", "date": {"equals": today}}}
    )
    r.raise_for_status()
    results = r.json().get("results", [])

    totals = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "meals": 0}
    for page in results:
        p = page["properties"]
        totals["kcal"]    += p["ККАЛ"]["number"]     or 0
        totals["protein"] += p["Белки"]["number"]    or 0
        totals["fat"]     += p["Жиры"]["number"]     or 0
        totals["carbs"]   += p["Углеводы"]["number"] or 0
        totals["meals"]   += 1

    return {k: round(v, 1) if isinstance(v, float) else v for k, v in totals.items()}

# ── Handlers ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я записываю что ты ешь.\n\n"
        "📸 Пришли фото — скажу что это и спрошу вес\n"
        "✍️ Напиши текстом — сразу запишу\n\n"
        "Примеры:\n"
        "• `гречка 200г`\n"
        "• `съел куриную грудку примерно 150г`\n"
        "• `2 яйца вкрутую`\n\n"
        "/today — итог за сегодня",
        parse_mode="Markdown"
    )

# ── Фото ──────────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Смотрю что на фото...")

    try:
        photo = update.message.photo[-1]
        tg_file = await photo.get_file()
        bio = BytesIO()
        await tg_file.download_to_memory(bio)
        image_bytes = bio.getvalue()

        # Анализируем фото
        result = analyze_photo(image_bytes)
        dish    = result["dish_name"]
        key     = dish_key(dish)
        conf    = result.get("confidence", "medium")
        conf_e  = {"high": "✅", "medium": "🟡", "low": "⚠️"}.get(conf, "🟡")

        # Сохраняем данные на 100г в память
        dish_memory[key] = {
            "dish_name":       dish,
            "kcal_per_100g":   result["kcal_per_100g"],
            "protein_per_100g":result["protein_per_100g"],
            "fat_per_100g":    result["fat_per_100g"],
            "carbs_per_100g":  result["carbs_per_100g"]
        }

        # Сохраняем в контекст пользователя
        context.user_data["pending_dish"] = key

        await msg.edit_text(
            f"{conf_e} *{dish}*\n\n"
            f"~{result['kcal_per_100g']} ккал / 100 г\n\n"
            f"Сколько грамм съел?",
            parse_mode="Markdown"
        )
        return WAITING_WEIGHT

    except Exception as e:
        logger.error(f"Photo error: {e}")
        await msg.edit_text(f"❌ Не смог распознать фото. Попробуй ещё раз или напиши текстом.")
        return ConversationHandler.END

async def handle_weight_after_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Извлекаем число из текста (например "150" или "150г" или "150 грамм")
    import re
    nums = re.findall(r'\d+(?:\.\d+)?', text)
    if not nums:
        await update.message.reply_text("Напиши просто число, например: `150`", parse_mode="Markdown")
        return WAITING_WEIGHT

    weight_g = float(nums[0])
    key = context.user_data.get("pending_dish")

    if not key or key not in dish_memory:
        await update.message.reply_text("Что-то пошло не так, пришли фото ещё раз.")
        return ConversationHandler.END

    d = dish_memory[key]
    kcal    = d["kcal_per_100g"]    * weight_g / 100
    protein = d["protein_per_100g"] * weight_g / 100
    fat     = d["fat_per_100g"]     * weight_g / 100
    carbs   = d["carbs_per_100g"]   * weight_g / 100

    try:
        log_to_notion(d["dish_name"], weight_g, kcal, protein, fat, carbs)
        today = get_today_stats()

        await update.message.reply_text(
            f"✅ *{d['dish_name']}* — {weight_g} г\n\n"
            f"🔥 {round(kcal)} ккал\n"
            f"💪 Б: {round(protein,1)}г · 🧈 Ж: {round(fat,1)}г · 🍞 У: {round(carbs,1)}г\n\n"
            f"━━━━━━━━━━━━\n"
            f"*Сегодня итого:*\n"
            f"🔥 {today['kcal']} ккал · {today['meals']} приём(а)\n"
            f"💪 {today['protein']}г · 🧈 {today['fat']}г · 🍞 {today['carbs']}г",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 Подробно", callback_data="today")
            ]])
        )
    except Exception as e:
        logger.error(f"Notion error: {e}")
        await update.message.reply_text(f"❌ Не смог записать: {str(e)[:100]}")

    return ConversationHandler.END

# ── Текстовый ввод ────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Игнорируем команды
    if text.startswith("/"):
        return

    msg = await update.message.reply_text("✍️ Записываю...")

    try:
        result = parse_text_meal(text)

        log_to_notion(
            result["dish_name"],
            result["weight_g"],
            result["kcal_total"],
            result["protein_g"],
            result["fat_g"],
            result["carbs_g"]
        )

        today = get_today_stats()

        await msg.edit_text(
            f"✅ *{result['dish_name']}* — {result['weight_g']} г\n\n"
            f"🔥 {result['kcal_total']} ккал\n"
            f"💪 Б: {result['protein_g']}г · 🧈 Ж: {result['fat_g']}г · 🍞 У: {result['carbs_g']}г\n"
            f"_{result.get('note', '')}_\n\n"
            f"━━━━━━━━━━━━\n"
            f"*Сегодня итого:*\n"
            f"🔥 {today['kcal']} ккал · {today['meals']} приём(а)\n"
            f"💪 {today['protein']}г · 🧈 {today['fat']}г · 🍞 {today['carbs']}г",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 Подробно", callback_data="today")
            ]])
        )

    except Exception as e:
        logger.error(f"Text meal error: {e}")
        await msg.edit_text(
            "❌ Не понял. Попробуй написать иначе, например:\n"
            "`гречка с курицей 300г` или `2 яйца`",
            parse_mode="Markdown"
        )

# ── /today ────────────────────────────────────────────────
async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stats = get_today_stats()
        text = (
            f"*📊 {date.today().strftime('%d.%m.%Y')}*\n\n"
            f"🔥 {stats['kcal']} ккал\n"
            f"💪 Белки: {stats['protein']} г\n"
            f"🧈 Жиры: {stats['fat']} г\n"
            f"🍞 Углеводы: {stats['carbs']} г\n"
            f"🍽 Приёмов: {stats['meals']}"
        )
        target = update.message or update.callback_query.message
        await target.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Today error: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "today":
        stats = get_today_stats()
        await q.message.reply_text(
            f"*📊 {date.today().strftime('%d.%m.%Y')}*\n\n"
            f"🔥 {stats['kcal']} ккал\n"
            f"💪 Белки: {stats['protein']} г\n"
            f"🧈 Жиры: {stats['fat']} г\n"
            f"🍞 Углеводы: {stats['carbs']} г\n"
            f"🍽 Приёмов: {stats['meals']}",
            parse_mode="Markdown"
        )

# ── Main ──────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, handle_photo)],
        states={
            WAITING_WEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weight_after_photo)
            ]
        },
        fallbacks=[CommandHandler("start", start)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
