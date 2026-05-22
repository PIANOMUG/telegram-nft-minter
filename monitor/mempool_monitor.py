import time
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)


MINT_SIGS = {
    "0xa0712d68", "0x1249c58b", "0x84bb1e42", "0x0f93a0cc",
    "0x3d0b1e1a", "0x6a627842", "0xab834bab", "0x9d76ea55",
    "0xe6b5d2b2", "0x7f0b2f1a", "0x4e6f9d00", "0x40d097c3",
    "0xefef39a1", "0xfea4c0a0", "0x9b3b0a1e", "0xce40b3c8",
    "0x2b0c9b5a", "0xb3eaf2b8", "0xdaa7b6e8",
}


class MempoolMonitor:
    def __init__(self, w3, known_contracts: list = None):
        self.w3 = w3
        self._contracts = set(known_contracts or [])
        self._pending_mints = {}
        self.listeners = []
        self._running = False
        self._thread = None
        self._executor = ThreadPoolExecutor(max_workers=20)

    def on_new_mint(self, callback: Callable):
        self.listeners.append(callback)

    def watch_contract(self, address: str):
        self._contracts.add(address.lower())

    def register_pending_mint(self, contract_address: str, wallet_address: str,
                               mint_price_wei: int = 0, quantity: int = 1,
                               private_key: str = None):
        addr = contract_address.lower()
        self._contracts.add(addr)
        self._pending_mints[addr] = {
            "wallet": wallet_address,
            "mint_price": mint_price_wei,
            "quantity": quantity,
            "private_key": private_key,
        }

    def unregister_pending_mint(self, contract_address: str):
        self._pending_mints.pop(contract_address.lower(), None)

    def _fire(self, data: dict):
        for cb in self.listeners:
            try:
                cb(data)
            except Exception:
                pass

    def _simulate_mint(self, contract_addr: str, wallet: str,
                       mint_price: int, quantity: int) -> bool:
        try:
            mint_sigs_to_try = [
                ("mint(uint256)", True),
                ("mint()", False),
                ("mintNFT(uint256)", True),
                ("publicMint(uint256)", True),
                ("presaleMint(uint256)", True),
                ("whitelistMint(uint256)", True),
            ]
            addr = self.w3.to_checksum_address(contract_addr)
            def try_sig(fn_sig, needs_qty):
                selector = self.w3.keccak(text=fn_sig)[:4]
                if needs_qty:
                    data = self.w3.to_hex(selector + quantity.to_bytes(32, 'big'))
                else:
                    data = self.w3.to_hex(selector)
                try:
                    self.w3.eth.call({"from": wallet, "to": addr, "data": data, "value": mint_price * quantity, "gas": 900000})
                    return True
                except Exception:
                    return False
            futures = {self._executor.submit(try_sig, fn_sig, q): fn_sig for fn_sig, q in mint_sigs_to_try}
            for future in as_completed(futures):
                if future.result():
                    return True
            return False
        except Exception:
            return False

    def _monitor_loop(self):
        cycle = 0
        while self._running:
            try:
                pending = self.w3.eth.get_block("pending", full_transactions=True)
                for tx in pending.get("transactions", []):
                    to_addr = tx.get("to")
                    if to_addr is None:
                        continue
                    to_lower = to_addr.lower()
                    if to_lower in self._contracts:
                        input_data = tx.get("input", "0x")
                        if input_data and input_data != "0x":
                            sig = input_data[:10]
                            if sig in MINT_SIGS:
                                self._fire({
                                    "type": "mint_detected",
                                    "contract": to_lower,
                                    "tx_hash": tx.get("hash").hex() if tx.get("hash") else "",
                                    "from": tx.get("from", ""),
                                    "signature": sig,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "value": str(tx.get("value", 0)),
                                })

                cycle += 1
                if cycle % 5 == 0 and self._pending_mints:
                    items = list(self._pending_mints.items())
                    def check_pending(item):
                        addr, info = item
                        if self._simulate_mint(addr, info["wallet"],
                                                info["mint_price"], info["quantity"]):
                            return addr, info
                        return None
                    check_futures = [self._executor.submit(check_pending, it) for it in items]
                    for cf in as_completed(check_futures):
                        result = cf.result()
                        if result:
                            addr, info = result
                            self._fire({
                                "type": "mint_now_live",
                                "contract": addr,
                                "wallet": info["wallet"],
                                "quantity": info["quantity"],
                                "mint_price": info["mint_price"],
                                "private_key": info.get("private_key"),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                            self._pending_mints.pop(addr, None)
            except Exception as e:
                logger.error(f"Mempool monitor error: {e}")
            time.sleep(1.0)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
