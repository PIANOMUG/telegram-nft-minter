import logging
from openai import OpenAI
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, BOT_PERSONALITY

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self):
        self.client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        self.model = LLM_MODEL

    def _build_system(self, server_name: str = "") -> str:
        return f"{BOT_PERSONALITY}\n\nYou are in the Discord server: {server_name or 'Unknown'}"

    def chat(self, context: list, server_name: str = "") -> str:
        try:
            messages = [{"role": "system", "content": self._build_system(server_name)}]
            messages.extend(context)
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=500,
                temperature=0.8,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return None
