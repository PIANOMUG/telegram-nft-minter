import time
import statistics
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
            p25 = sorted(rewards)[len(rewards)//4] if len(rewards) > 1 else (rewards[0] if rewards else 1_000_000_000)
            avg_priority = sum(rewards) // len(rewards) if rewards else 1_000_000_000

            base_gwei = Web3.from_wei(base_fee, "gwei")
            avg_prio_gwei = Web3.from_wei(avg_priority, "gwei")
            p25_gwei = Web3.from_wei(p25, "gwei")

            return GasPrices(
                safe_low=round(base_gwei + p25_gwei, 1),
                standard=round(base_gwei + avg_prio_gwei, 1),
                fast=round(base_gwei + avg_prio_gwei * 1.5, 1),
                instant=round(base_gwei + avg_prio_gwei * 2.5, 1),
                base_fee=round(base_gwei, 1),
                priority_fee=round(avg_prio_gwei, 1),
            )
        except Exception:
            return GasPrices(
                safe_low=20, standard=30, fast=50, instant=80,
                base_fee=25, priority_fee=10,
            )

    def get_optimal_gas(self, strategy: str = "fast") -> dict:
        prices = self.get_gas_prices()
        base = prices.base_fee
        prio = prices.priority_fee

        if strategy == "slow":
            target_prio = prio * 0.8
            multiplier = 0.9
        elif strategy == "average":
            target_prio = prio
            multiplier = 1.0
        elif strategy == "fast":
            target_prio = prio * 1.5
            multiplier = 1.3
        elif strategy == "instant":
            target_prio = max(prio * 2.5, 80)
            multiplier = 2.0
        elif strategy == "max":
            target_prio = min(prio * 3, self.max_priority_gwei)
            multiplier = 2.5
        elif strategy == "auto":
            if base < 20:
                target_prio = prio * 0.8
                multiplier = 0.9
            elif base < 50:
                target_prio = prio
                multiplier = 1.0
            elif base < 100:
                target_prio = prio * 1.5
                multiplier = 1.3
            else:
                target_prio = prio * 2.5
                multiplier = 2.0
        else:
            target_prio = prio * 1.5
            multiplier = 1.3

        target_prio = min(target_prio, self.max_priority_gwei)
        max_gwei = min(base + target_prio, self.max_fee_gwei)
        final_prio = min(int(target_prio * multiplier * 1e9), self.max_priority_gwei * 10**9)
        final_max = min(int(max_gwei * multiplier * 1e9), self.max_fee_gwei * 10**9)

        return {
            "maxPriorityFeePerGas": Wei(final_prio),
            "maxFeePerGas": Wei(final_max),
            "strategy": strategy,
            "priority_gwei": round(final_prio / 1e9, 1),
            "max_gwei": round(final_max / 1e9, 1),
            "base_fee_gwei": round(base, 1),
        }

    def escalate_gas(self, current_strategy: str) -> str:
        tiers = ["slow", "average", "fast", "instant", "max"]
        if current_strategy in tiers:
            idx = tiers.index(current_strategy)
            if idx < len(tiers) - 1:
                return tiers[idx + 1]
        return "max"

