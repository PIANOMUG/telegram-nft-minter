import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

BOT_PERSONALITY = os.getenv("BOT_PERSONALITY", "You are a friendly, knowledgeable Discord assistant.")
ALLOWED_CHANNELS = [int(x) for x in os.getenv("ALLOWED_CHANNELS", "").split(",") if x]
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "2"))
MEMORY_LIMIT = int(os.getenv("MEMORY_LIMIT", "50"))
