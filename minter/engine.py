import time
import json
from web3 import Web3
from web3.exceptions import TransactionNotFound
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from .gas import GasOptimizer
from .wallet import WalletManager
from .chain import ChainManager
from config import GAS_LIMIT_MINT

def _dedup_abi(abi_list):
    seen = set()
    result = []
    for item in abi_list:
        if item.get("type") != "function":
            result.append(item)
            continue
        sig = item["name"] + "(" + ",".join(i.get("type", "") for i in item.get("inputs", [])) + ")"
        if sig not in seen:
            seen.add(sig)
            result.append(item)
    return result

MINT_ABI = _dedup_abi(json.loads('[{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"mint","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[],"name":"mint","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"mintNFT","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"_count","type":"uint256"}],"name":"mint","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"mint","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"publicMint","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"publicSaleMint","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"mintPublic","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"presaleMint","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"whitelistMint","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"whiteListMint","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"mintPresale","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"mintWhitelist","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"mintWhiteList","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"presale","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"quantity","type":"uint256"}],"name":"whitelist","outputs":[],"stateMutability":"payable","type":"function"}]'))

MONITOR_ABI = json.loads('[{"constant":true,"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"}]')

MINT_CANDIDATES = [
    ("mint(uint256)", True),
    ("mint()", False),
    ("mintNFT(uint256)", True),
    ("publicMint(uint256)", True),
    ("publicSaleMint(uint256)", True),
    ("mintPublic(uint256)", True),
    ("presaleMint(uint256)", True),
    ("whitelistMint(uint256)", True),
    ("whiteListMint(uint256)", True),
    ("mintPresale(uint256)", True),
    ("mintWhitelist(uint256)", True),
    ("mintWhiteList(uint256)", True),
    ("presale(uint256)", True),
    ("whitelist(uint256)", True),
]


class MintingEngine:
    def __init__(self, w3: Web3, wallet_mgr: WalletManager, gas_optimizer: GasOptimizer,
                 chain_mgr: ChainManager = None, default_chain: int = 1):
        self.w3 = w3
        self.wallet_mgr = wallet_mgr
        self.gas_optimizer = gas_optimizer
        self.chain_mgr = chain_mgr or ChainManager()
        self.default_chain = default_chain
        self.executor = ThreadPoolExecutor(max_workers=20)
        self._info_cache = {}
        self._cache_max = 500

    def _get_mint_price(self, contract: Web3, address: str) -> int:
        price_selectors = [
            ("mintPrice", "67e0badb"), ("cost", "823afc11"),
            ("price", "a035b1fe"), ("publicMintPrice", "ceb24bd0"),
            ("salePrice", "93bf7bee"), ("getPrice", "ceb24bd0"),
            ("mintFee", "514e62fc"), ("mintCost", "d0e4b9f6"),
            ("MINT_PRICE", "a2d7c3f4"), ("getMintCost", "cc9c37fc"),
        ]
        addr = Web3.to_checksum_address(address)
        for fn_name, selector_hex in price_selectors:
            try:
                selector = bytes.fromhex(selector_hex)
                data = "0x" + selector.hex()
                result = self.w3.eth.call({"to": addr, "data": data})
                if result and len(result) >= 32:
                    val = int.from_bytes(result[-32:], "big")
                    if val > 0:
                        return val
            except Exception:
                continue
        return 0

    def simulate_mint_call(self, contract_address: str, from_address: str,
                            fn_sig: str, needs_quantity: bool,
                            quantity: int = 1, value: int = 0) -> bool:
        try:
            addr = Web3.to_checksum_address(contract_address)
            selector = Web3.keccak(text=fn_sig)[:4]
            if needs_quantity:
                data = Web3.to_hex(selector + quantity.to_bytes(32, 'big'))
            else:
                data = Web3.to_hex(selector)
            self.w3.eth.call({
                "from": from_address,
                "to": addr,
                "data": data,
                "value": value,
                "gas": GAS_LIMIT_MINT * 3,
            })
            return True
        except Exception:
            return False

    def _try_values(self, contract_address: str, wallet_address: str,
                     fn_sig: str, needs_quantity: bool, quantity: int, values: list) -> bool:
        for v in values:
            if self.simulate_mint_call(contract_address, wallet_address,
                                        fn_sig, needs_quantity, quantity, v):
                return True
        return False

    def detect_available_mint(self, contract_address: str, wallet_address: str,
                               mint_price: int = 0, quantity: int = 1):
        values_to_try = [mint_price * quantity]
        if mint_price * quantity == 0:
            values_to_try.append(10**15)
            values_to_try.append(5 * 10**15)
        addr = Web3.to_checksum_address(contract_address)
        futures = {}
        for fn_sig, needs_quantity in MINT_CANDIDATES:
            futures[self.executor.submit(
                self._try_values, contract_address, wallet_address,
                fn_sig, needs_quantity, quantity, values_to_try
            )] = (fn_sig, needs_quantity)

        for future in as_completed(futures):
            if future.result():
                fn_sig, needs_quantity = futures[future]
                fn_name = fn_sig.split("(")[0]
                fn_params = ["uint256"] if needs_quantity else []
                return fn_name, fn_params, fn_sig
        return None, None, None

    def is_mint_live(self, contract_address: str, wallet_address: str,
                     mint_price: int = 0, quantity: int = 1) -> bool:
        fn_name, fn_params, fn_sig = self.detect_available_mint(
            contract_address, wallet_address, mint_price, quantity
        )
        return fn_name is not None

    def _find_mint_function(self, contract: Web3):
        candidates = [
            ("mint", ["uint256"]),
            ("mintNFT", ["uint256"]),
            ("mint", []),
        ]
        for fn_name, params in candidates:
            try:
                fn = getattr(contract.functions, fn_name, None)
                if fn:
                    if params:
                        fn(1).call()
                    else:
                        fn().call()
                    return fn_name, params
            except Exception:
                continue
        return "mint", ["uint256"]

    def _detect_mint_data(self, contract_address: str) -> dict:
        key = contract_address.lower()
        cached = self._info_cache.get(key)
        if cached:
            return cached
        if len(self._info_cache) > self._cache_max:
            for k in list(self._info_cache)[:100]:
                del self._info_cache[k]
        addr = Web3.to_checksum_address(contract_address)
        contract = self.w3.eth.contract(address=addr, abi=MINT_ABI)
        info_contract = self.w3.eth.contract(address=addr, abi=MONITOR_ABI)
        name = "Unknown"
        symbol = "?"
        try:
            name = info_contract.functions.name().call()[:32]
        except Exception:
            pass
        try:
            symbol = info_contract.functions.symbol().call()[:8]
        except Exception:
            pass
        mint_price = self._get_mint_price(contract, contract_address)
        fn_name, fn_params = self._find_mint_function(contract)
        result = {"name": name, "symbol": symbol, "mint_price": mint_price, "fn_name": fn_name, "fn_params": fn_params}
        self._info_cache[key] = result
        return result

    def get_contract_info(self, contract_address: str) -> dict:
        return self._detect_mint_data(contract_address)

    def mint_single(self, contract_address: str, private_key: str, quantity: int = 1,
                    gas_strategy: str = "auto", chain_id: int = 1) -> dict:
        w3 = self.chain_mgr.get_w3(chain_id) if chain_id != self.default_chain else self.w3
        contract_addr = Web3.to_checksum_address(contract_address)
        info = self._detect_mint_data(contract_address)
        account = w3.eth.account.from_key(private_key)
        sender = account.address
        mint_price = info["mint_price"]
        total_value = mint_price * quantity

        fn_name, fn_params, fn_sig = self.detect_available_mint(
            contract_addr, sender, mint_price, quantity
        )
        if fn_name is None:
            fn_name, fn_params = info["fn_name"], info["fn_params"]

        contract = w3.eth.contract(address=contract_addr, abi=MINT_ABI)
        nonce = w3.eth.get_transaction_count(sender, "pending")
        current_strategy = gas_strategy
        last_error = None

        for attempt in range(3):
            try:
                gas_params = self.gas_optimizer.get_optimal_gas(current_strategy)
                tx_base = {
                    "from": sender, "nonce": nonce, "value": total_value,
                    "chainId": w3.eth.chain_id,
                    "gas": GAS_LIMIT_MINT,
                    "maxPriorityFeePerGas": gas_params["maxPriorityFeePerGas"],
                    "maxFeePerGas": gas_params["maxFeePerGas"],
                }
                if fn_params and fn_params[0] == "uint256":
                    tx_data = getattr(contract.functions, fn_name)(quantity).build_transaction(tx_base)
                else:
                    tx_data = getattr(contract.functions, fn_name)().build_transaction(tx_base)

                signed = w3.eth.account.sign_transaction(tx_data, private_key)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                tx_hex = tx_hash.hex()

                return {
                    "success": True,
                    "tx_hash": tx_hex,
                    "explorer_url": self.chain_mgr.get_explorer_url(chain_id, tx_hex),
                    "contract": contract_address,
                    "quantity": quantity,
                    "gas_price_gwei": gas_params["priority_gwei"],
                    "method": f"{fn_name}({', '.join(fn_params)})",
                    "gas_strategy": current_strategy,
                    "chain_id": chain_id,
                }
            except Exception as e:
                last_error = str(e)
                if "insufficient funds" in last_error.lower():
                    break
                new_strategy = self.gas_optimizer.escalate_gas(current_strategy)
                if new_strategy == current_strategy:
                    break
                current_strategy = new_strategy
                nonce = w3.eth.get_transaction_count(sender, "pending")

        return {"success": False, "error": last_error, "contract": contract_address}

    def mint_batch(self, contract_address: str, private_keys: list, quantity: int = 1,
                   gas_strategy: str = "fast") -> list:
        results = []
        futures = []
        for pk in private_keys:
            futures.append(
                self.executor.submit(self.mint_single, contract_address, pk, quantity, gas_strategy)
            )
        for future in as_completed(futures):
            results.append(future.result())
        return results

    def mint_parallel_single_wallet(self, contract_address: str, private_key: str,
                                      quantity: int = 1, rounds: int = 3,
                                      gas_strategy: str = "auto", chain_id: int = 1) -> list:
        nonce = self.w3.eth.get_transaction_count(
            self.w3.eth.account.from_key(private_key).address, "pending"
        )
        futures = []
        for i in range(rounds):
            futures.append(
                self.executor.submit(self._mint_with_nonce, contract_address, private_key,
                                      quantity, gas_strategy, nonce + i, chain_id)
            )
        results = []
        for future in as_completed(futures):
            results.append(future.result())
        return results

    def _mint_with_nonce(self, contract_address: str, private_key: str, quantity: int,
                          gas_strategy: str, nonce: int, chain_id: int = 1) -> dict:
        try:
            w3 = self.chain_mgr.get_w3(chain_id) if chain_id != self.default_chain else self.w3
            contract_addr = Web3.to_checksum_address(contract_address)
            info = self._detect_mint_data(contract_address)
            account = w3.eth.account.from_key(private_key)
            sender = account.address
            mint_price = info["mint_price"]
            total_value = mint_price * quantity

            fn_name, fn_params, fn_sig = self.detect_available_mint(
                contract_addr, sender, mint_price, quantity
            )
            if fn_name is None:
                fn_name, fn_params = info["fn_name"], info["fn_params"]

            gas_params = self.gas_optimizer.get_optimal_gas(gas_strategy)
            contract = w3.eth.contract(address=contract_addr, abi=MINT_ABI)
            tx_base = {
                "from": sender, "nonce": nonce, "value": total_value,
                "chainId": w3.eth.chain_id,
                "gas": GAS_LIMIT_MINT,
                "maxPriorityFeePerGas": gas_params["maxPriorityFeePerGas"],
                "maxFeePerGas": gas_params["maxFeePerGas"],
            }
            if fn_params and fn_params[0] == "uint256":
                tx_data = getattr(contract.functions, fn_name)(quantity).build_transaction(tx_base)
            else:
                tx_data = getattr(contract.functions, fn_name)().build_transaction(tx_base)

            signed = w3.eth.account.sign_transaction(tx_data, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            return {
                "success": True,
                "tx_hash": tx_hash.hex(),
                "explorer_url": self.chain_mgr.get_explorer_url(chain_id, tx_hash.hex()),
                "contract": contract_address,
                "quantity": quantity,
                "gas_price_gwei": gas_params["priority_gwei"],
                "method": f"{fn_name}({', '.join(fn_params)})",
                "chain_id": chain_id,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "contract": contract_address}

    def check_transaction(self, tx_hash: str) -> dict:
        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
            if receipt is None:
                return {"status": "pending", "confirmations": 0}
            block_num = self.w3.eth.block_number
            confirms = block_num - receipt["blockNumber"]
            status = "confirmed" if receipt["status"] == 1 else "failed"
            return {"status": status, "confirmations": confirms, "block": receipt["blockNumber"]}
        except TransactionNotFound:
            return {"status": "pending", "confirmations": 0}
        except Exception as e:
            return {"status": "unknown", "error": str(e)}
