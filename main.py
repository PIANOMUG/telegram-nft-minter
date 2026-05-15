import os
import sys
import time
import logging
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from web3 import Web3

from config import (
    TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, RPC_URL, CHAIN_ID,
    ETHERSCAN_API_KEY, OPENSEA_API_KEY, ENCRYPTION_KEY, DATABASE_PATH,
    DEFAULT_GAS_STRATEGY, MAX_PRIORITY_FEE_GWEI, MAX_FEE_GWEI,
    MONITOR_INTERVAL_SECONDS, MONITOR_NEW_CONTRACTS,
)
from database.db import Database
from minter.wallet import WalletManager
from minter.gas import GasOptimizer
from minter.engine import MintingEngine
from minter.chain import ChainManager
from monitor.etherscan_monitor import EtherscanMonitor
from monitor.opensea_monitor import OpenSeaMonitor
from monitor.mempool_monitor import MempoolMonitor
from monitor.scanner import ContractScanner
from monitor.orchestrator import MonitorOrchestrator
from bot.telegram_bot import NFTBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("main")


def main():
    logger.info("Starting NFT SuperMinter Bot...")

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    if not RPC_URL or "your-api-key" in RPC_URL:
        logger.warning("RPC_URL not properly configured. Using default.")

    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if w3.is_connected():
        logger.info(f"Connected to chain {CHAIN_ID} (block: {w3.eth.block_number})")
    else:
        logger.warning("Web3 not connected. Some features will be limited.")

    db = Database(DATABASE_PATH)
    wallet_mgr = WalletManager(ENCRYPTION_KEY)
    gas_opt = GasOptimizer(w3, max_priority_gwei=MAX_PRIORITY_FEE_GWEI, max_fee_gwei=MAX_FEE_GWEI)
    chain_mgr = ChainManager()
    engine = MintingEngine(w3, wallet_mgr, gas_opt, chain_mgr=chain_mgr, default_chain=CHAIN_ID)

    etherscan = None
    if ETHERSCAN_API_KEY:
        etherscan = EtherscanMonitor(ETHERSCAN_API_KEY, CHAIN_ID)

    opensea = None
    if OPENSEA_API_KEY:
        opensea = OpenSeaMonitor(OPENSEA_API_KEY)

    mempool = MempoolMonitor(w3)
    explorer_urls = {
        1: "https://api.etherscan.io",
        137: "https://api.polygonscan.com",
        42161: "https://api.arbiscan.io",
        10: "https://api-optimistic.etherscan.io",
        43114: "https://api.snowtrace.io",
        56: "https://api.bscscan.com",
    }
    scanner_base = explorer_urls.get(CHAIN_ID, "https://api.etherscan.io")
    scanner = ContractScanner(ETHERSCAN_API_KEY or "", scanner_base)

    orchestrator = MonitorOrchestrator(
        etherscan=etherscan,
        opensea=opensea,
        mempool=mempool,
        db=db,
        scanner=scanner if MONITOR_NEW_CONTRACTS else None,
    )

    if db.get_setting(0, "gas_strategy") is None:
        db.set_setting(0, "gas_strategy", DEFAULT_GAS_STRATEGY)

    bot = NFTBot(
        token=TELEGRAM_BOT_TOKEN,
        db=db,
        wallet_mgr=wallet_mgr,
        gas_opt=gas_opt,
        engine=engine,
        monitor=orchestrator,
        allowed_users=ALLOWED_USER_IDS or None,
        opensea=opensea,
        chain_mgr=chain_mgr,
    )

    orchestrator.start()
    logger.info("Monitor started. Launching bot...")

    retry_delay = 1
    max_delay = 60
    while True:
        try:
            bot.run()
        except Exception as e:
            logger.error(f"Bot crashed: {e}. Restarting in {retry_delay}s...", exc_info=True)
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_delay)


if __name__ == "__main__":
    main()
