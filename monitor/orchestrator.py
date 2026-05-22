import time
import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from .etherscan_monitor import EtherscanMonitor
from .opensea_monitor import OpenSeaMonitor
from .mempool_monitor import MempoolMonitor
from .scanner import ContractScanner

logger = logging.getLogger(__name__)


class MonitorOrchestrator:
    def __init__(self, etherscan: EtherscanMonitor = None, opensea: OpenSeaMonitor = None,
                 mempool: MempoolMonitor = None, db=None, scanner: ContractScanner = None):
        self.etherscan = etherscan
        self.opensea = opensea
        self.mempool = mempool
        self.db = db
        self.scanner = scanner
        self._listeners = []
        self._running = False
        self._threads = []
        self._monitored_contracts = set()

    def on_new_mint_opportunity(self, callback: Callable):
        self._listeners.append(callback)

    def _notify(self, data: dict):
        for cb in self._listeners:
            try:
                cb(data)
            except Exception as e:
                logger.error(f"Listener callback error: {e}")

    def add_contract(self, address: str):
        self._monitored_contracts.add(address.lower())
        if self.mempool:
            self.mempool.watch_contract(address)

    def register_pending_mint(self, contract_address: str, wallet_address: str,
                               mint_price_wei: int = 0, quantity: int = 1,
                               private_key: str = None):
        if self.mempool:
            self.mempool.register_pending_mint(
                contract_address, wallet_address, mint_price_wei, quantity, private_key
            )

    def unregister_pending_mint(self, contract_address: str):
        if self.mempool:
            self.mempool.unregister_pending_mint(contract_address)

    def start(self):
        if self._running:
            return
        self._running = True

        if self.mempool:
            self.mempool.start()

        if self.etherscan:
            t = threading.Thread(target=self._etherscan_loop, daemon=True)
            t.start()
            self._threads.append(t)

        if self.opensea:
            t = threading.Thread(target=self._opensea_loop, daemon=True)
            t.start()
            self._threads.append(t)

        if self.scanner:
            t = threading.Thread(target=self._scanner_loop, daemon=True)
            t.start()
            self._threads.append(t)

    def _etherscan_loop(self):
        while self._running:
            try:
                if self.db:
                    db_contracts = self.db.get_all_monitored_contracts(status="pending")
                    for c in db_contracts:
                        addr = c["address"]
                        info = self.etherscan.detect_nft_contract(addr) if self.etherscan else {}
                        if info.get("is_nft") and info.get("has_mint_function"):
                            self.db.update_contract_status(c["id"], "live")
                            self._notify({
                                "type": "contract_live",
                                "contract": addr,
                                "name": c.get("name", "Unknown"),
                                "details": info,
                                "source": "etherscan_check",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
            except Exception as e:
                logger.error(f"Etherscan loop error: {e}")
            time.sleep(30)

    def _opensea_loop(self):
        while self._running:
            try:
                if self.opensea:
                    new_cols = self.opensea.get_new_collections(limit=10)
                    for col in new_cols:
                        addr = col.get("contract_address", "").lower()
                        if addr and self.db:
                            try:
                                self.db.add_monitored_contract(0, addr, col.get("name"))
                            except Exception as e:
                                logger.error(f"Opensea add contract error: {e}")
                            self.add_contract(addr)
                            self._notify({
                                "type": "new_collection",
                                "contract": addr,
                                "name": col.get("name"),
                                "source": "opensea",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
            except Exception as e:
                logger.error(f"OpenSea loop error: {e}")
            time.sleep(60)

    def _scanner_loop(self):
        while self._running:
            try:
                if self.scanner:
                    new_contracts = self.scanner.scan_recent_deployments(lookback_blocks=100)
                    for info in new_contracts:
                        addr = info.get("address", "").lower()
                        if addr and self.db:
                            try:
                                self.db.add_monitored_contract(0, addr, info.get("name"))
                            except Exception as e:
                                logger.error(f"Scanner add contract error: {e}")
                            self.add_contract(addr)
                            self._notify({
                                "type": "new_contract_detected",
                                "contract": addr,
                                "name": info.get("name", "Unknown"),
                                "source": "chain_scan",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
            except Exception as e:
                logger.error(f"Scanner loop error: {e}")
            time.sleep(15)

    def stop(self):
        self._running = False
        if self.mempool:
            self.mempool.stop()
