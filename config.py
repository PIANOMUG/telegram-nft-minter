import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_IDS = [int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x]

RPC_URL = os.getenv("RPC_URL", "https://eth-mainnet.g.alchemy.com/v2/your-api-key")
CHAIN_ID = int(os.getenv("CHAIN_ID", "1"))
EXPLORER_URL = os.getenv("EXPLORER_URL", "https://etherscan.io")

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
OPENSEA_API_KEY = os.getenv("OPENSEA_API_KEY", "")
FLASHBOTS_RELAY = os.getenv("FLASHBOTS_RELAY", "https://relay.flashbots.net")

DEFAULT_GAS_STRATEGY = os.getenv("DEFAULT_GAS_STRATEGY", "fast")
MAX_PRIORITY_FEE_GWEI = int(os.getenv("MAX_PRIORITY_FEE_GWEI", "200"))
MAX_FEE_GWEI = int(os.getenv("MAX_FEE_GWEI", "500"))
GAS_LIMIT_MINT = int(os.getenv("GAS_LIMIT_MINT", "300000"))

MONITOR_INTERVAL_SECONDS = int(os.getenv("MONITOR_INTERVAL_SECONDS", "15"))
MONITOR_NEW_CONTRACTS = os.getenv("MONITOR_NEW_CONTRACTS", "true").lower() == "true"

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/bot.db")
