import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", 10))
CACHE_TTL = 86400
CLAUDE_TEXT_MODEL = "claude-3-5-haiku-20241022"
CLAUDE_VISION_MODEL = "claude-3-5-sonnet-20241022"
WEB_APP_URL = os.getenv("WEB_APP_URL", "")