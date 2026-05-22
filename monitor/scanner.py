import time
import requests
import re
from datetime import datetime, timezone


class ContractScanner:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.seen = set()

    def scan_recent_deployments(self, lookback_blocks: int = 500) -> list:
        try:
            current_block = self._get_block_number()
            if not current_block:
                return []
            from_block = max(0, current_block - lookback_blocks)

            resp = requests.get(
                f"{self.base_url}/api",
                params={
                    "module": "proxy",
                    "action": "eth_getLogs",
                    "fromBlock": hex(from_block),
                    "toBlock": "latest",
                    "address": "0x0000000000000000000000000000000000000000",
                    "topic0": "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                    "apikey": self.api_key,
                },
                timeout=30,
            )
            data = resp.json()
            if not data.get("result"):
                return []

            contracts = set()
            for log in data["result"]:
                if len(log.get("topics", [])) >= 3:
                    addr = "0x" + log["address"][2:].lower() if log["address"].startswith("0x") else log["address"].lower()
                    contracts.add(addr)

            new_contracts = []
            for addr in contracts:
                if addr in self.seen:
                    continue
                self.seen.add(addr)
                info = self._quick_check(addr)
                if info:
                    new_contracts.append(info)

            return new_contracts
        except Exception as e:
            return []

    def _get_block_number(self) -> int:
        try:
            resp = requests.get(
                f"{self.base_url}/api",
                params={"module": "proxy", "action": "eth_blockNumber", "apikey": self.api_key},
                timeout=5,
            )
            data = resp.json()
            return int(data["result"], 16) if data.get("result") else 0
        except Exception:
            return 0

    def _quick_check(self, address: str) -> dict:
        try:
            code_resp = requests.post(
                self.base_url.replace("api", "rpc"),
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_getCode",
                    "params": [address, "latest"],
                    "id": 1,
                },
                timeout=5,
            )
            code = code_resp.json().get("result", "0x")
            if code == "0x" or len(code) < 100:
                return None

            has_transfer = self._has_event_sig(address, "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef")

            if not has_transfer:
                return None

            name = self._call_string_fn(address, "0x06fdde03")

            return {
                "address": address,
                "name": name or "Unknown",
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "source": "mempool_scan",
                "has_transfer_event": True,
            }
        except Exception:
            return None

    def _has_event_sig(self, address: str, topic: str) -> bool:
        try:
            current = self._get_block_number()
            if not current:
                return False
            resp = requests.get(
                f"{self.base_url}/api",
                params={
                    "module": "logs",
                    "action": "getLogs",
                    "fromBlock": hex(max(0, current - 1000)),
                    "toBlock": "latest",
                    "address": address,
                    "topic0": topic,
                    "apikey": self.api_key,
                },
                timeout=10,
            )
            data = resp.json()
            return bool(data.get("result"))
        except Exception:
            return False

    def _call_string_fn(self, address: str, selector: str) -> str:
        try:
            data = selector + "0" * 56
            resp = requests.post(
                self.base_url.replace("api", "rpc"),
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [{"to": address, "data": data}, "latest"],
                    "id": 1,
                },
                timeout=5,
            )
            result = resp.json().get("result", "0x")
            if result and len(result) > 2:
                raw = bytes.fromhex(result[2:])
                if len(raw) >= 68:
                    offset = int.from_bytes(raw[32:64], "big") + 64
                    if offset + 32 <= len(raw):
                        length = int.from_bytes(raw[offset:offset+32], "big")
                        if offset + 32 + length <= len(raw):
                            decoded = raw[offset+32:offset+32+length].decode("utf-8", errors="ignore")
                            cleaned = re.sub(r'[^\x20-\x7E]', '', decoded)
                            return cleaned[:40]
                decoded = raw.decode("utf-8", errors="ignore")
                return re.sub(r'[^\x20-\x7E]', '', decoded)[:40]
            return ""
        except Exception:
            return ""
