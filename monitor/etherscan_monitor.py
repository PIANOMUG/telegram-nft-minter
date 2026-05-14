import time
import requests
import re
from datetime import datetime, timezone


ERC721_SIG = "0x80ac58cd"
ERC1155_SIG = "0xd9b67a26"


class EtherscanMonitor:
    def __init__(self, api_key: str, chain_id: int = 1):
        self.api_key = api_key
        self.chain_id = chain_id
        self.base_urls = {
            1: "https://api.etherscan.io",
            137: "https://api.polygonscan.com",
            42161: "https://api.arbiscan.io",
            10: "https://api-optimistic.etherscan.io",
            43114: "https://api.snowtrace.io",
            56: "https://api.bscscan.com",
        }
        self.base = self.base_urls.get(chain_id, "https://api.etherscan.io")
        self.seen_contracts = set()

    def get_recent_verified_contracts(self, hours: int = 1) -> list:
        try:
            from .scanner import ContractScanner
            scanner = ContractScanner(self.api_key, self.base)
            return scanner.scan_recent_deployments()
        except Exception:
            return []

    def _get_current_block(self) -> int:
        try:
            resp = requests.get(
                f"{self.base}/api",
                params={"module": "proxy", "action": "eth_blockNumber", "apikey": self.api_key},
                timeout=5,
            )
            data = resp.json()
            return int(data["result"], 16) if data.get("result") else 0
        except Exception:
            return 0

    def get_contract_abi(self, address: str) -> list:
        try:
            resp = requests.get(
                f"{self.base}/api",
                params={
                    "module": "contract",
                    "action": "getabi",
                    "address": address,
                    "apikey": self.api_key,
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("status") == "1" and data.get("result"):
                try:
                    import json
                    abi = json.loads(data["result"])
                    return abi
                except Exception:
                    return []
            return []
        except Exception:
            return []

    def detect_nft_contract(self, address: str) -> dict:
        abi = self.get_contract_abi(address)
        if not abi:
            return {"is_nft": False}

        functions = [item.get("name", "") for item in abi if item.get("type") == "function"]
        has_balance_of = "balanceOf" in functions
        has_owner_of = "ownerOf" in functions
        has_safe_transfer = "safeTransferFrom" in functions
        has_mint = any("mint" in fn.lower() for fn in functions)

        if has_owner_of and (has_balance_of or has_safe_transfer):
            supports_interface = self._check_interface_support(address)
            return {
                "is_nft": True,
                "standard": "ERC721" if supports_interface != "erc1155" else "ERC1155",
                "has_mint_function": has_mint,
                "functions": functions[:15],
            }

        return {"is_nft": False}

    def _check_interface_support(self, address: str) -> str:
        try:
            data = "0x01ffc9a7" + ERC721_SIG[2:].zfill(64)
            resp = requests.post(
                f"{self.base.replace('api', 'rpc')}",
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [{"to": address, "data": data}, "latest"],
                    "id": 1,
                },
                timeout=5,
            )
            result = resp.json().get("result", "0x" + "0" * 64)
            if result and result != "0x" + "0" * 64:
                return "erc721"
        except Exception:
            pass
        return "unknown"
