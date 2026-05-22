from web3 import Web3
from config import CHAIN_INFO


class ChainManager:
    def __init__(self):
        self._w3 = {}

    def get_w3(self, chain_id: int) -> Web3:
        if chain_id not in self._w3:
            info = CHAIN_INFO.get(chain_id)
            if not info:
                raise ValueError(f"Unsupported chain: {chain_id}")
            self._w3[chain_id] = Web3(Web3.HTTPProvider(info["rpc"]))
        return self._w3[chain_id]

    def get_explorer_url(self, chain_id: int, tx_hash: str = None) -> str:
        info = CHAIN_INFO.get(chain_id)
        if not info:
            raise ValueError(f"Unsupported chain: {chain_id}")
        base = info["explorer"]
        if tx_hash:
            return f"{base}/tx/{tx_hash}"
        return base

    def get_currency(self, chain_id: int) -> str:
        info = CHAIN_INFO.get(chain_id)
        if not info:
            raise ValueError(f"Unsupported chain: {chain_id}")
        return info["currency"]

    def get_chain_name(self, chain_id: int) -> str:
        info = CHAIN_INFO.get(chain_id)
        if not info:
            raise ValueError(f"Unsupported chain: {chain_id}")
        return info["name"]
