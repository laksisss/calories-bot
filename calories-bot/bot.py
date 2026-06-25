import os
import json
import base64
import logging
import requests
from datetime import datetime, date
from io import BytesIO

import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Переменные окружения ──────────────────────────────────
TELEGRAM_TOKEN      = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
NOTION_TOKEN        = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID  = os.environ["NOTION_DATABASE_ID"]
WEBAPP_URL          = os.environ.get("WEBAPP_URL", "")

WAITING_WEIGHT = 1

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ── Notion: запись приёма пищи ────────────────────────────
def log_meal_notion(meal: dict):
    today = date.today().isoformat()
    now   = datetime.now().strftime("%H:%M")

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Name": {
                "title": [{"text": {"content": f"{meal['dish_name']} ({now})"}}]
            },
            "Дата":          {"date":   {"start": today}},
            "ККАЛ":          {"number": meal["kcal_total"]},
            "Белки":         {"number": meal["protein_g"]},
            "Жиры":          {"number": meal["fat_g"]},
            "Углеводы":      {"number": meal["carbs_g"]},
            "Вес (г)":       {"number": meal["weight_g"]},
            "Способ готовки":{"rich_text": [{"text": {"content": meal["cooking_method"]}}]},
            "Детали":        {"rich_text": [{"text": {"content": meal["details"]}}]}
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

    payload = {
        "filter": {
            "property": "Дата",
            "date": {"equals": today}
        }
    }

    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
        headers=NOTION_HEADERS,
        json=payload
    )
    r.raise_for_status()
    results = r.json().get("results", [])

    totals = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "meals": 0}
    for page in results:
        props = page["properties"]
        totals["kcal"]    += props["ККАЛ"]["number"]    or 0
        totals["protein"] += props["Белки"]["number"]   or 0
        totals["fat"]     += props["Жиры"]["number"]    or 0
        totals["carbs"]   += props["Углеводы"]["number"] or 0
        totals["meals"]   += 1

    return {k: round(v, 1) if isinstance(v, float) else v for k, v in totals.items()}

# ── Notion: данные за 7 дней (для дашборда) ───────────────
def get_week_stats() -> list:
    payload = {
        "sorts": [{"property": "Дата", "direction": "descending"}],
        "page_size": 100
    }

    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
        headers=NOTION_HEADERS,
        json=payload
    )
    r.raise_for_status()
    results = r.json().get("results", [])

    by_date: dict = {}
    for page in results:
        props = page["properties"]
        d = props["Дата"]["date"]
        if not d:
            continue
        day = d["start"]
        if day not in by_date:
            by_date[day] = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "meals": 0}
        by_date[day]["kcal"]    += props["ККАЛ"]["number"]     or 0
        by_date[day]["protein"] += props["Белки"]["number"]    or 0
        by_date[day]["fat"]     += props["Жиры"]["number"]     or 0
        by_date[day]["carbs"]   += props["Углеводы"]["number"] or 0
        by_date[day]["meals"]   += 1

    sorted_days = sorted(by_date.keys(), reverse=True)[:7]
    return [{"date": d, **by_date[d]} for d in reversed(sorted_days)]

# ── Claude Vision ─────────────────────────────────────────
def analyze_food(image_bytes: bytes, weight_g: float, cooking_method: str) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    prompt = f"""Ты — точный нутрициолог и диетолог с экспертизой в термической обработке еды.

Пользователь прислал фото еды. Данные:
- Вес блюда (уже приготовленного): {weight_g} г
- Способ приготовления: {cooking_method}

Твоя задача — максимально точно рассчитать КБЖУ.

ОБЯЗАТЕЛЬНО учти:
1. Термические потери: жарка теряет 20-40% воды и жира, варка — 15-25%, запекание — 15-35%, гриль — 25-40%
2. Если блюдо жареное — масло добавляет калории (оцени количество масла визуально)
3. Состав блюда по фото — все ингредиенты которые видишь
4. Соусы, гарниры, видимые добавки — посчитай отдельно и суммируй
5. При неопределённости — бери среднее значение диапазона

Ответь ТОЛЬКО валидным JSON без markdown-обёртки:
{{
  "dish_name": "название блюда",
  "cooking_method": "уточнённый способ готовки",
  "main_ingredients": ["ингредиент1", "ингредиент2"],
  "weight_g": {weight_g},
  "kcal_per_100g": число,
  "kcal_total": число,
  "protein_g": число,
  "fat_g": число,
  "carbs_g": число,
  "thermal_factor": "объяснение термических потерь в 1 предложении",
  "confidence": "high/medium/low",
  "details": "краткое объяснение расчёта 1-2 предложения"
}}"""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1000,
        messages=[{
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
    )

    raw = response.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

# ── Helpers ───────────────────────────────────────────────
def build_today_text(stats: dict) -> str:
    return (
        f"*📊 Сегодня, {date.today().strftime('%d.%m.%Y')}*\n\n"
        f"🔥 Калории: *{stats['kcal']}* ккал\n"
        f"💪 Белки: {stats['protein']} г\n"
        f"🧈 Жиры: {stats['fat']} г\n"
        f"🍞 Углеводы: {stats['carbs']} г\n"
        f"🍽 Приёмов пищи: {stats['meals']}"
    )

def build_main_keyboard():
    keyboard = [[InlineKeyboardButton("📋 Итого за сегодня", callback_data="today")]]
    if WEBAPP_URL:
        keyboard.insert(0, [InlineKeyboardButton(
            "📊 Открыть дашборд", web_app=WebAppInfo(url=WEBAPP_URL)
        )])
    return InlineKeyboardMarkup(keyboard)

# ── Handlers ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👨‍🍳 *Привет! Я твой калорийный агент.*\n\n"
        "Пришли мне фото еды с подписью:\n"
        "`[вес в граммах] [как готовил]`\n\n"
        "Пример подписи: `200 жарил на масле`\n\n"
        "Или просто пришли фото без подписи — я спрошу сам.",
        parse_mode="Markdown",
        reply_markup=build_main_keyboard()
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Скачиваем фото в память
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    bio = BytesIO()
    await tg_file.download_to_memory(bio)
    context.user_data["photo_bytes"] = bio.getvalue()

    # Если подпись уже содержит вес — сразу анализируем
    caption = update.message.caption
    if caption:
        parts = caption.strip().split(maxsplit=1)
        if parts and parts[0].replace(".", "").isdigit():
            context.user_data["weight"]  = float(parts[0])
            context.user_data["cooking"] = parts[1] if len(parts) > 1 else "не указан"
            await process_meal(update, context)
            return ConversationHandler.END

    await update.message.reply_text(
        "📸 Фото получил!\n\n"
        "Напиши: `[вес в граммах] [как готовил]`\n"
        "Пример: `250 варил 20 минут`",
        parse_mode="Markdown"
    )
    return WAITING_WEIGHT

async def handle_weight_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.strip().split(maxsplit=1)

    if not parts or not parts[0].replace(".", "").isdigit():
        await update.message.reply_text(
            "❌ Не понял формат. Напиши так:\n`200 жарил на сковороде`",
            parse_mode="Markdown"
        )
        return WAITING_WEIGHT

    context.user_data["weight"]  = float(parts[0])
    context.user_data["cooking"] = parts[1] if len(parts) > 1 else "не указан"
    await process_meal(update, context)
    return ConversationHandler.END

async def process_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Анализирую блюдо...")

    try:
        meal = analyze_food(
            context.user_data["photo_bytes"],
            context.user_data["weight"],
            context.user_data["cooking"]
        )

        await msg.edit_text("💾 Записываю в базу...")
        log_meal_notion(meal)

        today = get_today_stats()

        conf_emoji = {"high": "✅", "medium": "🟡", "low": "⚠️"}.get(
            meal.get("confidence", "medium"), "🟡"
        )

        text = (
            f"*{meal['dish_name']}*\n\n"
            f"🔥 *{meal['kcal_total']} ккал* {conf_emoji}\n"
            f"_{meal['kcal_per_100g']} ккал / 100 г_\n\n"
            f"💪 Белки: {meal['protein_g']} г\n"
            f"🧈 Жиры: {meal['fat_g']} г\n"
            f"🍞 Углеводы: {meal['carbs_g']} г\n\n"
            f"🌡 _{meal.get('thermal_factor', '')}_ \n\n"
            f"📝 {meal['details']}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"*Сегодня итого:*\n"
            f"🔥 {today['kcal']} ккал · {today['meals']} приём(а)\n"
            f"💪 Б: {today['protein']} г · "
            f"🧈 Ж: {today['fat']} г · "
            f"🍞 У: {today['carbs']} г"
        )

        await msg.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=build_main_keyboard()
        )

    except json.JSONDecodeError:
        await msg.edit_text(
            "❌ Не смог распознать блюдо. Попробуй другое фото или опиши блюдо в подписи."
        )
    except Exception as e:
        logger.error(f"Error processing meal: {e}")
        await msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_today_stats()
    await update.message.reply_text(
        build_today_text(stats),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔄 Обновить", callback_data="today")]]
        )
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "today":
        stats = get_today_stats()
        await query.message.reply_text(
            build_today_text(stats),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Обновить", callback_data="today")]]
            )
        )

# ── API endpoint для дашборда (простой HTTP-сервер) ───────
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import urllib.parse

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Отключаем спам в логах

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # Отдаём HTML дашборда
        if parsed.path == "/" or parsed.path == "/dashboard":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with open("dashboard.html", "rb") as f:
                self.wfile.write(f.read())

        # API: данные за сегодня
        elif parsed.path == "/api/today":
            try:
                data = get_today_stats()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        # API: лог приёмов за сегодня
        elif parsed.path == "/api/log":
            try:
                today = date.today().isoformat()
                payload = {
                    "filter": {"property": "Дата", "date": {"equals": today}},
                    "sorts": [{"timestamp": "created_time", "direction": "ascending"}]
                }
                r = requests.post(
                    f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
                    headers=NOTION_HEADERS, json=payload
                )
                r.raise_for_status()
                results = r.json().get("results", [])
                log = []
                for page in results:
                    props = page["properties"]
                    name_arr = props["Name"]["title"]
                    full_name = name_arr[0]["text"]["content"] if name_arr else "—"
                    # имя без времени в скобках
                    dish = full_name.split(" (")[0]
                    time_part = full_name[-6:-1] if "(" in full_name else "—"
                    cooking_arr = props["Способ готовки"]["rich_text"]
                    cooking = cooking_arr[0]["text"]["content"] if cooking_arr else "—"
                    log.append({
                        "name":     dish,
                        "time":     time_part,
                        "weight_g": props["Вес (г)"]["number"] or 0,
                        "cooking":  cooking,
                        "kcal":     props["ККАЛ"]["number"] or 0
                    })
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(log).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        # API: данные за 7 дней
        elif parsed.path == "/api/week":
            try:
                data = get_week_stats()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        else:
            self.send_response(404)
            self.end_headers()

def start_http_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    logger.info(f"Dashboard server on port {port}")
    server.serve_forever()

# ── Main ──────────────────────────────────────────────────
def main():
    # Запускаем HTTP-сервер в отдельном потоке
    t = threading.Thread(target=start_http_server, daemon=True)
    t.start()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, handle_photo)],
        states={
            WAITING_WEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weight_input)
            ]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot started polling")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
