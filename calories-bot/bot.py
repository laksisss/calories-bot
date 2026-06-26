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

# ── База КБЖУ на 100г — СЫРЫЕ продукты ───────────────────
# (ккал, белки, жиры, углеводы)
FOOD_DB = {
    # Мясо / птица — сырые
    "куриная грудка": (113, 23.6, 1.9, 0.4),
    "курица грудка":  (113, 23.6, 1.9, 0.4),
    "грудка":         (113, 23.6, 1.9, 0.4),
    "куриное филе":   (113, 23.6, 1.9, 0.4),
    "филе":           (113, 23.6, 1.9, 0.4),
    "курица":         (172, 20.8, 9.6, 0.4),
    "куриное бедро":  (181, 20.1, 11.0, 0.1),
    "бедро":          (181, 20.1, 11.0, 0.1),
    "говядина":       (187, 20.4, 11.4, 0.0),
    "свинина":        (261, 17.5, 21.5, 0.0),
    "фарш говяжий":   (230, 17.0, 18.0, 0.0),
    "фарш":           (230, 17.0, 18.0, 0.0),
    "индейка":        (147, 22.0, 7.0, 0.0),
    "индейка грудка": (112, 24.0, 1.5, 0.0),
    "лосось":         (142, 19.8, 6.3, 0.0),
    "тунец":          (103, 22.0, 1.0, 0.0),
    "скумбрия":       (191, 18.0, 13.2, 0.0),
    "треска":         (69,  16.0, 0.6, 0.0),
    "яйцо":           (157, 12.7, 11.5, 0.7),
    "яйца":           (157, 12.7, 11.5, 0.7),

    # Крупы — сырые (до варки)
    "гречка":         (313, 12.6, 3.3, 57.1),
    "рис":            (344, 7.0,  1.0, 75.0),
    "рис белый":      (344, 7.0,  1.0, 75.0),
    "рис бурый":      (330, 7.4,  2.7, 65.0),
    "овсянка":        (342, 12.5, 6.1, 59.5),
    "овсяная каша":   (342, 12.5, 6.1, 59.5),
    "овёс":           (342, 12.5, 6.1, 59.5),
    "макароны":       (338, 12.0, 1.7, 70.5),
    "паста":          (338, 12.0, 1.7, 70.5),
    "перловка":       (315, 9.3,  1.1, 66.9),
    "булгур":         (342, 12.3, 1.3, 69.7),
    "киноа":          (368, 14.1, 6.1, 57.2),
    "пшено":          (334, 11.5, 3.3, 66.5),
    "хлеб":           (233, 7.9,  3.3, 44.2),
    "хлеб ржаной":    (199, 6.6,  1.2, 41.0),
    "тост":           (280, 9.0,  4.0, 50.0),

    # Овощи — сырые
    "брокколи":       (34,  2.8,  0.4, 6.6),
    "цветная капуста":(30,  2.5,  0.3, 5.4),
    "капуста":        (27,  1.8,  0.1, 5.4),
    "морковь":        (41,  0.9,  0.2, 9.6),
    "картошка":       (77,  2.0,  0.4, 16.3),
    "картофель":      (77,  2.0,  0.4, 16.3),
    "помидор":        (20,  0.9,  0.2, 3.8),
    "помидоры":       (20,  0.9,  0.2, 3.8),
    "огурец":         (15,  0.8,  0.1, 2.8),
    "огурцы":         (15,  0.8,  0.1, 2.8),
    "перец болгарский":(31, 1.3,  0.3, 6.7),
    "перец":          (31,  1.3,  0.3, 6.7),
    "шпинат":         (23,  2.9,  0.4, 3.6),
    "авокадо":        (160, 2.0, 14.7, 8.5),
    "кукуруза":       (86,  3.3,  1.2, 18.7),
    "горошек":        (73,  5.0,  0.2, 13.8),
    "свекла":         (43,  1.5,  0.1, 9.6),
    "лук":            (41,  1.4,  0.2, 8.2),
    "чеснок":         (149, 6.4,  0.5, 29.9),
    "баклажан":       (25,  1.2,  0.1, 5.5),
    "кабачок":        (24,  1.5,  0.3, 4.6),

    # Фрукты
    "банан":          (89,  1.1,  0.3, 22.8),
    "бананы":         (89,  1.1,  0.3, 22.8),
    "яблоко":         (52,  0.3,  0.2, 13.8),
    "яблоки":         (52,  0.3,  0.2, 13.8),
    "апельсин":       (43,  0.9,  0.2, 10.3),
    "мандарин":       (38,  0.8,  0.2, 8.9),
    "виноград":       (72,  0.6,  0.2, 17.5),
    "клубника":       (32,  0.8,  0.4, 7.5),
    "черника":        (44,  0.7,  0.3, 10.9),
    "груша":          (57,  0.4,  0.1, 15.2),

    # Молочка
    "творог 0%":      (71,  16.5, 0.0, 1.3),
    "творог 1%":      (79,  16.3, 1.0, 1.3),
    "творог 5%":      (121, 17.0, 5.0, 1.8),
    "творог 9%":      (159, 16.7, 9.0, 2.0),
    "творог 18%":     (232, 15.0, 18.0, 2.8),
    "творог":         (121, 17.0, 5.0, 1.8),
    "кефир 0%":       (30,  3.0,  0.1, 3.8),
    "кефир 1%":       (40,  3.3,  1.0, 3.8),
    "кефир":          (51,  2.8,  2.5, 3.6),
    "молоко":         (61,  3.2,  3.6, 4.8),
    "молоко 2.5%":    (52,  2.9,  2.5, 4.8),
    "йогурт":         (68,  5.0,  2.0, 8.5),
    "сыр":            (350, 25.0, 26.8, 0.0),
    "сыр твёрдый":    (380, 26.0, 30.0, 0.0),
    "сметана 10%":    (115, 3.0, 10.0, 4.0),
    "сметана 15%":    (158, 2.6, 15.0, 3.7),
    "сметана 20%":    (204, 2.8, 20.0, 3.7),
    "сметана":        (204, 2.8, 20.0, 3.7),
    "масло сливочное":(748, 0.5, 82.5, 0.8),

    # Орехи / масла
    "миндаль":        (575, 21.2, 49.9, 21.7),
    "грецкий орех":   (654, 15.2, 65.2, 13.7),
    "арахис":         (551, 26.3, 45.2, 17.6),
    "кешью":          (553, 18.2, 43.9, 30.2),
    "масло оливковое":(884, 0.0, 99.8, 0.0),
    "масло подсолнечное": (884, 0.0, 99.9, 0.0),
    "масло":          (884, 0.0, 99.9, 0.0),

    # Бобовые
    "чечевица":       (295, 24.0, 1.5, 42.7),
    "фасоль":         (298, 20.9, 2.0, 49.7),
    "нут":            (364, 19.0, 6.0, 53.0),

    # Готовые / прочее
    "яйцо варёное":   (157, 12.7, 11.5, 0.7),
    "омлет":          (184, 9.6, 15.4, 2.0),
    "протеин":        (380, 70.0, 5.0, 15.0),
}

def find_food(name: str):
    n = name.lower().strip()
    # Точное совпадение
    if n in FOOD_DB:
        return FOOD_DB[n], n
    # Частичное — ищем самый длинный подходящий ключ
    best = None
    best_len = 0
    for key in FOOD_DB:
        if key in n or n in key:
            if len(key) > best_len:
                best = key
                best_len = len(key)
    if best:
        return FOOD_DB[best], best
    return None, None

# ── Парсинг веса ──────────────────────────────────────────
def parse_weight(text: str) -> float | None:
    t = text.lower()
    m = re.search(r'(\d+[.,]\d+)\s*кг', t)
    if m: return float(m.group(1).replace(',', '.')) * 1000
    m = re.search(r'(\d+)\s*кг', t)
    if m: return float(m.group(1)) * 1000
    m = re.search(r'(\d+[.,]\d+)\s*(?:гр?|грамм)', t)
    if m: return float(m.group(1).replace(',', '.'))
    m = re.search(r'(\d+)\s*(?:гр?|грамм)', t)
    if m: return float(m.group(1))
    m = re.search(r'\b(\d{2,4})\b', t)
    if m: return float(m.group(1))
    return None

# ── Яйца по штукам ───────────────────────────────────────
EGG_WORDS = {
    "одно":1,"одного":1,"одним":1,"одну":1,
    "два":2,"две":2,"двух":2,"двумя":2,
    "три":3,"трёх":3,"трех":3,
    "четыре":4,"четырёх":4,"четырех":4,
    "пять":5,"шесть":6,"семь":7,"восемь":8,"девять":9,"десять":10
}

def parse_egg_count(text: str) -> int | None:
    t = text.lower()
    if "яйц" not in t: return None
    for word, count in EGG_WORDS.items():
        if word in t: return count
    m = re.search(r'(\d+)\s*яйц', t)
    if m: return int(m.group(1))
    if "яйцо" in t or "яйца" in t: return 1
    return None

# ── Парсинг текста в список блюд ─────────────────────────
def parse_meal_text(text: str) -> list[dict]:
    results = []
    # Делим по запятой, переносу, "и" между продуктами
    parts = re.split(r'[\n]+|,\s*', text)

    for part in parts:
        part = part.strip()
        if not part: continue

        # Яйца
        egg_count = parse_egg_count(part)
        if egg_count:
            kcal_100, p, f, c = FOOD_DB["яйцо"]
            w = egg_count * 60
            results.append({
                "name": f"Яйца ({egg_count} шт)",
                "weight_g": w,
                "kcal":    round(kcal_100 * w / 100),
                "protein": round(p * w / 100, 1),
                "fat":     round(f * w / 100, 1),
                "carbs":   round(c * w / 100, 1),
            })
            continue

        food_data, food_key = find_food(part)
        if not food_data: continue

        weight = parse_weight(part) or 100
        kcal_100, p, f, c = food_data
        results.append({
            "name":    food_key.capitalize(),
            "weight_g": weight,
            "kcal":    round(kcal_100 * weight / 100),
            "protein": round(p * weight / 100, 1),
            "fat":     round(f * weight / 100, 1),
            "carbs":   round(c * weight / 100, 1),
        })

    return results

# ── Claude: если не нашли в базе ────────────────────────
def ask_claude_text(text: str) -> list[dict] | None:
    prompt = f"""Пользователь написал о еде: "{text}"

Определи продукты/блюда. Используй калораж СЫРЫХ продуктов.
Если вес не указан — стандартная порция.
Верни ТОЛЬКО валидный JSON-массив без markdown:
[{{"name":"название","weight_g":число,"kcal":число,"protein":число,"fat":число,"carbs":число}}]"""
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 400,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=20
        )
        r.raise_for_status()
        raw = r.json()["content"][0]["text"].strip()
        raw = raw.replace("```json","").replace("```","").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Claude text: {e}")
        return None

# ── Claude: анализ фото ──────────────────────────────────
def analyze_photo(image_bytes: bytes) -> dict:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    prompt = """Нутрициолог. Определи блюдо на фото и КБЖУ на 100г сырого продукта.
JSON без markdown:
{"dish_name":"название","kcal_per_100g":число,"protein_per_100g":число,"fat_per_100g":число,"carbs_per_100g":число,"confidence":"high/medium/low"}"""
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": "claude-opus-4-6", "max_tokens": 300,
              "messages": [{"role": "user", "content": [
                  {"type": "image", "source": {"type": "base64",
                   "media_type": "image/jpeg", "data": image_b64}},
                  {"type": "text", "text": prompt}
              ]}]},
        timeout=30
    )
    r.raise_for_status()
    raw = r.json()["content"][0]["text"].strip()
    raw = raw.replace("```json","").replace("```","").strip()
    return json.loads(raw)

# ── Notion ───────────────────────────────────────────────
def log_meal_batch(items: list[dict]):
    """Записывает ОДИН приём пищи (несколько продуктов = одна строка)."""
    today = date.today().isoformat()
    now   = datetime.now().strftime("%H:%M")

    total_kcal    = sum(i["kcal"]    for i in items)
    total_protein = sum(i["protein"] for i in items)
    total_fat     = sum(i["fat"]     for i in items)
    total_carbs   = sum(i["carbs"]   for i in items)
    names = ", ".join(i["name"] for i in items)

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Name":     {"title":  [{"text": {"content": f"{names} ({now})"}}]},
            "Дата":     {"date":   {"start": today}},
            "ККАЛ":     {"number": round(total_kcal, 1)},
            "Белки":    {"number": round(total_protein, 1)},
            "Жиры":     {"number": round(total_fat, 1)},
            "Углеводы": {"number": round(total_carbs, 1)},
            "Вес (г)":  {"number": round(sum(i["weight_g"] for i in items), 1)}
        }
    }
    r = requests.post("https://api.notion.com/v1/pages",
                      headers=NOTION_HEADERS, json=payload)
    r.raise_for_status()

def log_single(name, weight_g, kcal, protein, fat, carbs):
    """Записывает одно блюдо (для фото)."""
    log_meal_batch([{"name": name, "weight_g": weight_g,
                     "kcal": kcal, "protein": protein,
                     "fat": fat, "carbs": carbs}])

def get_today_stats():
    today = date.today().isoformat()
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
        headers=NOTION_HEADERS,
        json={"filter": {"property": "Дата", "date": {"equals": today}}}
    )
    r.raise_for_status()
    t = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "meals": 0}
    for page in r.json().get("results", []):
        p = page["properties"]
        t["kcal"]    += p["ККАЛ"]["number"]     or 0
        t["protein"] += p["Белки"]["number"]    or 0
        t["fat"]     += p["Жиры"]["number"]     or 0
        t["carbs"]   += p["Углеводы"]["number"] or 0
        t["meals"]   += 1
    return {k: round(v, 1) if isinstance(v, float) else v for k, v in t.items()}

# ── Форматирование ────────────────────────────────────────
def meal_reply(items: list[dict], today: dict) -> str:
    lines = []
    for item in items:
        lines.append(
            f"✅ *{item['name']}* {item['weight_g']}г — {item['kcal']} ккал\n"
            f"   💪{item['protein']}г  🧈{item['fat']}г  🍞{item['carbs']}г"
        )
    if len(items) > 1:
        total = sum(i["kcal"] for i in items)
        lines.append(f"\n*Приём: {total} ккал*")
    lines.append(
        f"\n━━━━━━━━━━━━\n"
        f"*Сегодня:* 🔥 {today['kcal']} ккал · {today['meals']} приём(а)"
    )
    return "\n".join(lines)

def today_text(s):
    return (
        f"*📊 {date.today().strftime('%d.%m.%Y')}*\n\n"
        f"🔥 {s['kcal']} ккал\n"
        f"💪 Белки: {s['protein']} г\n"
        f"🧈 Жиры: {s['fat']} г\n"
        f"🍞 Углеводы: {s['carbs']} г\n"
        f"🍽 Приёмов: {s['meals']}"
    )

# ── Память блюд (фото) ───────────────────────────────────
dish_memory: dict = {}

# ── Handlers ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Пиши что ел — запишу.\n\n"
        "📸 *Фото* — распознаю, спрошу вес\n"
        "✍️ *Текст* — считаю и записываю сразу\n\n"
        "Несколько продуктов — один приём:\n"
        "`рис 150г`\n"
        "`куриная грудка 200г, брокколи 100г`\n"
        "`2 яйца`\n"
        "`творог 9% 250гр`\n\n"
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
        conf_e = {"high":"✅","medium":"🟡","low":"⚠️"}.get(result.get("confidence","medium"),"🟡")

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
            f"Сколько грамм?",
            parse_mode="Markdown"
        )
        return WAITING_WEIGHT
    except Exception as e:
        logger.error(f"Photo error: {e}")
        await msg.edit_text("❌ Не смог распознать. Попробуй ещё раз или напиши текстом.")
        return ConversationHandler.END

async def handle_weight_after_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nums = re.findall(r'\d+(?:[.,]\d+)?', update.message.text)
    if not nums:
        await update.message.reply_text("Напиши число, например: `150`", parse_mode="Markdown")
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
        log_single(item["name"], item["weight_g"],
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
        logger.error(f"Notion: {e}")
        await update.message.reply_text(f"❌ Ошибка записи: {str(e)[:100]}")
    return ConversationHandler.END

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("/"): return

    msg = await update.message.reply_text("✍️ Считаю...")

    items = parse_meal_text(text)
    if not items:
        items = ask_claude_text(text)

    if not items:
        await msg.edit_text(
            "❓ Не нашёл такой продукт. Попробуй:\n"
            "`куриная грудка 200г`\n`гречка 150г`\n`2 яйца`",
            parse_mode="Markdown"
        )
        return

    try:
        # Одно сообщение = один приём = одна запись в Notion
        log_meal_batch(items)
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
        states={WAITING_WEIGHT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weight_after_photo)
        ]},
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
