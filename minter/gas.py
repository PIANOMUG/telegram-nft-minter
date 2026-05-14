import time
from web3 import Web3
from web3.types import Wei
from dataclasses import dataclass


@dataclass
class GasPrices:
    safe_low: float
    standard: float
    fast: float
    instant: float
    base_fee: float
    priority_fee: float


class GasOptimizer:
    def __init__(self, w3: Web3, max_priority_gwei: int = 200, max_fee_gwei: int = 500):
        self.w3 = w3
        self.max_priority_gwei = max_priority_gwei
        self.max_fee_gwei = max_fee_gwei

    def get_gas_prices(self) -> GasPrices:
        try:
            fee_history = self.w3.eth.fee_history(5, "latest", [25, 50, 75])
            base_fee = fee_history["baseFeePerGas"][-1]
            rewards = [r[0] for r in fee_history["reward"]]
            avg_priority = sum(rewards) // len(rewards) if rewards else 1_000_000_000

            base_gwei = Web3.from_wei(base_fee, "gwei")
            prio_gwei = Web3.from_wei(avg_priority, "gwei")

            return GasPrices(
                safe_low=round(base_gwei + prio_gwei * 0.9, 1),
                standard=round(base_gwei + prio_gwei, 1),
                fast=round(base_gwei + prio_gwei * 1.5, 1),
                instant=round(base_gwei + prio_gwei * 2.5, 1),
                base_fee=round(base_gwei, 1),
                priority_fee=round(prio_gwei, 1),
            )
        except Exception:
            return GasPrices(
                safe_low=20, standard=30, fast=50, instant=80,
                base_fee=25, priority_fee=10,
            )

    def get_optimal_gas(self, strategy: str = "fast") -> dict:
        prices = self.get_gas_prices()
        multipliers = {"slow": 0.9, "average": 1.0, "fast": 1.3, "max": 2.0, "instant": 2.5}

        prio_gwei = prices.priority_fee
        if strategy == "instant":
            prio_gwei = prices.priority_fee if prices.priority_fee > 50 else 80
        elif strategy == "max":
            prio_gwei = min(prices.priority_fee * 3, self.max_priority_gwei)

        prio_gwei = min(prio_gwei, self.max_priority_gwei)
        max_gwei = min(prices.base_fee + prio_gwei, self.max_fee_gwei)
        multiplier = multipliers.get(strategy, 1.3)
        final_prio = min(int(prio_gwei * multiplier * 1e9), self.max_priority_gwei * 10**9)
        final_max = min(int(max_gwei * multiplier * 1e9), self.max_fee_gwei * 10**9)

        return {
            "maxPriorityFeePerGas": Wei(final_prio),
            "maxFeePerGas": Wei(final_max),
            "strategy": strategy,
            "priority_gwei": round(final_prio / 1e9, 1),
            "max_gwei": round(final_max / 1e9, 1),
        }

    def estimate_gas_for_mint(self, contract_address: str, w3: Web3) -> int:
        try:
            gas_estimate = w3.eth.estimate_gas({"to": contract_address, "data": "0x"})
            return int(gas_estimate * 1.2)
        except Exception:
            return 300000
