import os
import re
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

# ── База КБЖУ на 100г (самые частые продукты) ─────────────
FOOD_DB = {
    # Мясо / птица
    "куриная грудка": (110, 23, 2, 0),
    "курица грудка":  (110, 23, 2, 0),
    "грудка":         (110, 23, 2, 0),
    "курица":         (165, 20, 9, 0),
    "куриное бедро":  (185, 19, 12, 0),
    "бедро":          (185, 19, 12, 0),
    "говядина":       (218, 26, 12, 0),
    "свинина":        (259, 22, 18, 0),
    "фарш":           (250, 18, 20, 0),
    "индейка":        (135, 22, 5, 0),
    "лосось":         (208, 20, 13, 0),
    "тунец":          (96,  22, 1, 0),
    "скумбрия":       (191, 18, 13, 0),
    "яйцо":           (155, 13, 11, 1),
    "яйца":           (155, 13, 11, 1),

    # Крупы / злаки
    "гречка":         (92,  4,  1, 20),
    "рис":            (116, 3,  0, 26),
    "овсянка":        (88,  3,  2, 15),
    "овсяная каша":   (88,  3,  2, 15),
    "макароны":       (138, 5,  1, 28),
    "паста":          (138, 5,  1, 28),
    "перловка":       (109, 3,  0, 24),
    "булгур":         (83,  3,  0, 19),
    "киноа":          (120, 4,  2, 21),
    "хлеб":           (242, 8,  3, 47),
    "тост":           (280, 9,  4, 50),

    # Овощи
    "брокколи":       (35,  3,  0, 7),
    "цветная капуста":(30,  2,  0, 6),
    "капуста":        (28,  2,  0, 5),
    "морковь":        (41,  1,  0, 10),
    "картошка":       (77,  2,  0, 17),
    "картофель":      (77,  2,  0, 17),
    "помидор":        (20,  1,  0, 4),
    "помидоры":       (20,  1,  0, 4),
    "огурец":         (16,  1,  0, 3),
    "огурцы":         (16,  1,  0, 3),
    "перец":          (31,  1,  0, 7),
    "шпинат":         (23,  3,  0, 4),
    "авокадо":        (160, 2, 15, 9),
    "кукуруза":       (86,  3,  1, 19),
    "горошек":        (73,  5,  0, 14),

    # Фрукты
    "банан":          (89,  1,  0, 23),
    "бананы":         (89,  1,  0, 23),
    "яблоко":         (52,  0,  0, 14),
    "яблоки":         (52,  0,  0, 14),
    "апельсин":       (47,  1,  0, 12),
    "виноград":       (69,  1,  0, 18),
    "клубника":       (33,  1,  0, 8),
    "черника":        (57,  1,  0, 14),

    # Молочка
    "творог":         (103, 18, 2, 3),
    "творог 0%":      (70,  17, 0, 3),
    "творог 5%":      (121, 17, 5, 3),
    "творог 9%":      (159, 17, 9, 3),
    "кефир":          (51,  3,  2, 4),
    "молоко":         (61,  3,  3, 5),
    "йогурт":         (68,  5,  2, 8),
    "сыр":            (350, 26, 27, 0),
    "сметана":        (206, 3, 20, 4),

    # Орехи / масла
    "миндаль":        (579, 21, 50, 22),
    "грецкий орех":   (654, 15, 65, 14),
    "арахис":         (567, 26, 49, 16),
    "масло":          (717, 1, 81, 0),
    "оливковое масло":(884, 0, 100, 0),

    # Готовые блюда
    "борщ":           (50,  3,  2, 7),
    "суп":            (40,  3,  1, 6),
    "пельмени":       (275, 12, 13, 29),
    "котлета":        (215, 15, 15, 8),
    "омлет":          (154, 10, 12, 2),
    "блины":          (200, 6,  7, 29),

    # Снеки / фастфуд
    "шоколад":        (546, 6, 32, 60),
    "печенье":        (430, 6, 18, 62),
    "мороженое":      (207, 4, 11, 24),
    "чипсы":          (536, 7, 34, 53),
}

def find_food(name: str):
    """Ищет продукт в базе — сначала точное совпадение, потом частичное."""
    n = name.lower().strip()
    if n in FOOD_DB:
        return FOOD_DB[n]
    for key in FOOD_DB:
        if key in n or n in key:
            return FOOD_DB[key]
    return None

# ── Парсинг веса из текста ────────────────────────────────
def parse_weight(text: str) -> float | None:
    """Извлекает вес в граммах из строки."""
    text = text.lower()

    # кг: 1.5кг, 1,5 кг, 1кг
    m = re.search(r'(\d+[.,]\d+)\s*кг', text)
    if m:
        return float(m.group(1).replace(',', '.')) * 1000
    m = re.search(r'(\d+)\s*кг', text)
    if m:
        return float(m.group(1)) * 1000

    # г / гр / грамм
    m = re.search(r'(\d+[.,]\d+)\s*(?:гр?|грамм)', text)
    if m:
        return float(m.group(1).replace(',', '.'))
    m = re.search(r'(\d+)\s*(?:гр?|грамм)', text)
    if m:
        return float(m.group(1))

    # просто число (первое в строке)
    m = re.search(r'\b(\d{2,4})\b', text)
    if m:
        return float(m.group(1))

    return None

# ── Счёт яиц ─────────────────────────────────────────────
EGG_WORDS = {"одно": 1, "одного": 1, "одним": 1,
             "два": 2, "две": 2, "двух": 2, "двумя": 2,
             "три": 3, "трёх": 3, "трех": 3,
             "четыре": 4, "четырёх": 4, "четырех": 4,
             "пять": 5, "шесть": 6, "семь": 7,
             "восемь": 8, "девять": 9, "десять": 10}

def parse_egg_count(text: str) -> int | None:
    t = text.lower()
    if "яйц" not in t and "яйц" not in t:
        return None
    for word, count in EGG_WORDS.items():
        if word in t:
            return count
    m = re.search(r'(\d+)\s*яйц', t)
    if m:
        return int(m.group(1))
    return None

# ── Главный парсер текста ─────────────────────────────────
def parse_meal_text(text: str) -> list[dict] | None:
    """
    Парсит текст и возвращает список блюд:
    [{"name": ..., "weight_g": ..., "kcal": ..., "protein": ..., "fat": ..., "carbs": ...}]
    Возвращает None если ничего не распознал.
    """
    results = []

    # Делим на части по запятой, "и", переносу строки
    parts = re.split(r'[,\n]+|(?<=[а-яё])\s+и\s+(?=[а-яё])', text, flags=re.IGNORECASE)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Яйца — особый случай
        egg_count = parse_egg_count(part)
        if egg_count:
            kcal_100, p_100, f_100, c_100 = FOOD_DB["яйцо"]
            w = egg_count * 60  # среднее яйцо ~60г
            results.append({
                "name": f"Яйца ({egg_count} шт)",
                "weight_g": w,
                "kcal":    round(kcal_100 * w / 100),
                "protein": round(p_100 * w / 100, 1),
                "fat":     round(f_100 * w / 100, 1),
                "carbs":   round(c_100 * w / 100, 1),
            })
            continue

        # Ищем продукт
        food_data = None
        food_name = None
        for key in sorted(FOOD_DB.keys(), key=len, reverse=True):
            if key in part.lower():
                food_data = FOOD_DB[key]
                food_name = key
                break

        if not food_data:
            continue

        # Ищем вес
        weight = parse_weight(part)
        if not weight:
            weight = 100  # дефолт

        kcal_100, p_100, f_100, c_100 = food_data
        results.append({
            "name":    food_name.capitalize(),
            "weight_g": weight,
            "kcal":    round(kcal_100 * weight / 100),
            "protein": round(p_100 * weight / 100, 1),
            "fat":     round(f_100 * weight / 100, 1),
            "carbs":   round(c_100 * weight / 100, 1),
        })

    return results if results else None

# ── Если не нашли в базе → Claude ────────────────────────
def ask_claude_text(text: str) -> list[dict] | None:
    prompt = f"""Пользователь написал о еде: "{text}"

Определи все продукты/блюда, их вес в граммах и КБЖУ.
Если вес не указан — используй стандартную порцию.
Верни ТОЛЬКО валидный JSON-массив без markdown:
[
  {{
    "name": "название",
    "weight_g": число,
    "kcal": число,
    "protein": число,
    "fat": число,
    "carbs": число
  }}
]"""

    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=20
        )
        response.raise_for_status()
        raw = response.json()["content"][0]["text"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Claude text error: {e}")
        return None

# ── Claude: анализ фото ───────────────────────────────────
def analyze_photo(image_bytes: bytes) -> dict:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    prompt = """Ты нутрициолог. Посмотри на фото еды.

Определи блюдо и КБЖУ на 100г.
Ответь ТОЛЬКО валидным JSON без markdown:
{
  "dish_name": "название (коротко)",
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
            "max_tokens": 300,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_b64}},
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

# ── Notion ────────────────────────────────────────────────
def log_to_notion(name, weight_g, kcal, protein, fat, carbs):
    today = date.today().isoformat()
    now   = datetime.now().strftime("%H:%M")
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Name":     {"title":  [{"text": {"content": f"{name} ({now})"}}]},
            "Дата":     {"date":   {"start": today}},
            "ККАЛ":     {"number": round(float(kcal), 1)},
            "Белки":    {"number": round(float(protein), 1)},
            "Жиры":     {"number": round(float(fat), 1)},
            "Углеводы": {"number": round(float(carbs), 1)},
            "Вес (г)":  {"number": round(float(weight_g), 1)}
        }
    }
    r = requests.post("https://api.notion.com/v1/pages",
                      headers=NOTION_HEADERS, json=payload)
    r.raise_for_status()

def get_today_stats():
    today = date.today().isoformat()
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
        headers=NOTION_HEADERS,
        json={"filter": {"property": "Дата", "date": {"equals": today}}}
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    t = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "meals": 0}
    for page in results:
        p = page["properties"]
        t["kcal"]    += p["ККАЛ"]["number"]     or 0
        t["protein"] += p["Белки"]["number"]    or 0
        t["fat"]     += p["Жиры"]["number"]     or 0
        t["carbs"]   += p["Углеводы"]["number"] or 0
        t["meals"]   += 1
    return {k: round(v, 1) if isinstance(v, float) else v for k, v in t.items()}

def today_text(stats):
    return (
        f"*📊 {date.today().strftime('%d.%m.%Y')}*\n\n"
        f"🔥 {stats['kcal']} ккал\n"
        f"💪 Белки: {stats['protein']} г\n"
        f"🧈 Жиры: {stats['fat']} г\n"
        f"🍞 Углеводы: {stats['carbs']} г\n"
        f"🍽 Приёмов: {stats['meals']}"
    )

def meal_reply(items: list[dict], today: dict) -> str:
    lines = []
    total_kcal = 0
    for item in items:
        lines.append(
            f"✅ *{item['name']}* {item['weight_g']}г — {item['kcal']} ккал\n"
            f"   💪{item['protein']}г 🧈{item['fat']}г 🍞{item['carbs']}г"
        )
        total_kcal += item['kcal']

    if len(items) > 1:
        lines.append(f"\n*Итого этого приёма: {total_kcal} ккал*")

    lines.append(
        f"\n━━━━━━━━━━━━\n"
        f"*Сегодня:* 🔥 {today['kcal']} ккал · {today['meals']} приём(а)"
    )
    return "\n".join(lines)

# ── Память блюд (фото) ────────────────────────────────────
dish_memory: dict = {}

# ── Handlers ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Пиши что ел — запишу.\n\n"
        "📸 *Фото* — распознаю и спрошу вес\n"
        "✍️ *Текст* — сразу считаю и записываю\n\n"
        "Примеры:\n"
        "• `куриная грудка 200г`\n"
        "• `гречка 150г, брокколи 100г`\n"
        "• `2 яйца`\n"
        "• `творог 9% 250гр`\n"
        "• `0.5кг риса`\n\n"
        "/today — итог дня",
        parse_mode="Markdown"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Смотрю что на фото...")
    try:
        photo = update.message.photo[-1]
        tg_file = await photo.get_file()
        bio = BytesIO()
        await tg_file.download_to_memory(bio)

        result = analyze_photo(bio.getvalue())
        dish = result["dish_name"]
        key  = dish.lower().strip()
        conf_e = {"high": "✅", "medium": "🟡", "low": "⚠️"}.get(
            result.get("confidence", "medium"), "🟡")

        dish_memory[key] = {
            "dish_name":        dish,
            "kcal_per_100g":    result["kcal_per_100g"],
            "protein_per_100g": result["protein_per_100g"],
            "fat_per_100g":     result["fat_per_100g"],
            "carbs_per_100g":   result["carbs_per_100g"]
        }
        context.user_data["pending_dish"] = key

        await msg.edit_text(
            f"{conf_e} *{dish}*\n"
            f"~{result['kcal_per_100g']} ккал / 100 г\n\n"
            f"Сколько грамм съел?",
            parse_mode="Markdown"
        )
        return WAITING_WEIGHT

    except Exception as e:
        logger.error(f"Photo error: {e}")
        await msg.edit_text("❌ Не смог распознать фото. Попробуй ещё раз или напиши текстом.")
        return ConversationHandler.END

async def handle_weight_after_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nums = re.findall(r'\d+(?:[.,]\d+)?', update.message.text)
    if not nums:
        await update.message.reply_text("Напиши просто число, например: `150`", parse_mode="Markdown")
        return WAITING_WEIGHT

    weight_g = float(nums[0].replace(',', '.'))
    key = context.user_data.get("pending_dish")

    if not key or key not in dish_memory:
        await update.message.reply_text("Пришли фото ещё раз.")
        return ConversationHandler.END

    d = dish_memory[key]
    item = {
        "name":    d["dish_name"],
        "weight_g": weight_g,
        "kcal":    round(d["kcal_per_100g"]    * weight_g / 100),
        "protein": round(d["protein_per_100g"] * weight_g / 100, 1),
        "fat":     round(d["fat_per_100g"]     * weight_g / 100, 1),
        "carbs":   round(d["carbs_per_100g"]   * weight_g / 100, 1),
    }

    try:
        log_to_notion(item["name"], item["weight_g"],
                      item["kcal"], item["protein"], item["fat"], item["carbs"])
        today = get_today_stats()
        await update.message.reply_text(
            meal_reply([item], today),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 Итог дня", callback_data="today")
            ]])
        )
    except Exception as e:
        logger.error(f"Notion error: {e}")
        await update.message.reply_text(f"❌ Ошибка записи: {str(e)[:100]}")

    return ConversationHandler.END

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("/"):
        return

    msg = await update.message.reply_text("✍️ Считаю...")

    # Сначала локальный парсер
    items = parse_meal_text(text)

    # Если не нашли — спрашиваем Claude
    if not items:
        items = ask_claude_text(text)

    if not items:
        await msg.edit_text(
            "❓ Не нашёл такой продукт. Попробуй уточнить:\n"
            "`куриная грудка 200г`\n`гречка 150г`\n`2 яйца`",
            parse_mode="Markdown"
        )
        return

    try:
        for item in items:
            log_to_notion(item["name"], item["weight_g"],
                          item["kcal"], item["protein"], item["fat"], item["carbs"])
        today = get_today_stats()
        await msg.edit_text(
            meal_reply(items, today),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 Итог дня", callback_data="today")
            ]])
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit_text(f"❌ Ошибка: {str(e)[:150]}")

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stats = get_today_stats()
        await update.message.reply_text(
            today_text(stats), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Обновить", callback_data="today")
            ]])
        )
    except Exception as e:
        await update.message.reply_text(f"❌ {str(e)[:100]}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "today":
        stats = get_today_stats()
        await q.message.reply_text(
            today_text(stats), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Обновить", callback_data="today")
            ]])
        )

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
