import time
import json
import threading
from datetime import datetime, timezone
from typing import Callable


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
            for fn_sig, needs_qty in mint_sigs_to_try:
                selector = self.w3.keccak(text=fn_sig)[:4]
                if needs_qty:
                    data = self.w3.to_hex(selector + quantity.to_bytes(32, 'big'))
                else:
                    data = self.w3.to_hex(selector)
                try:
                    self.w3.eth.call({
                        "from": wallet,
                        "to": addr,
                        "data": data,
                        "value": mint_price * quantity,
                    })
                    return True
                except Exception:
                    continue
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
                    for addr, info in list(self._pending_mints.items()):
                        if self._simulate_mint(addr, info["wallet"],
                                                info["mint_price"], info["quantity"]):
                            self._fire({
                                "type": "mint_now_live",
                                "contract": addr,
                                "wallet": info["wallet"],
                                "quantity": info["quantity"],
                                "mint_price": info["mint_price"],
                                "private_key": info.get("private_key"),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                            del self._pending_mints[addr]
            except Exception:
                pass
            time.sleep(0.1)

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
