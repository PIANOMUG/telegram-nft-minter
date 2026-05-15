import os
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.ai_bot import AIBot


def main():
    logger.info("Starting Discord AI Bot...")
    bot = AIBot()
    retry_delay = 1
    while True:
        try:
            bot.run_bot()
        except Exception as e:
            logger.error(f"Bot crashed: {e}. Restarting in {retry_delay}s...", exc_info=True)
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)


if __name__ == "__main__":
    main()
