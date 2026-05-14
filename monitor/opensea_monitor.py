import time
import requests
from datetime import datetime, timezone


class OpenSeaMonitor:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.seen_collections = set()
        self.base_url = "https://api.opensea.io/api/v2"

    def get_new_collections(self, limit: int = 20) -> list:
        headers = {}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key

        try:
            resp = requests.get(
                f"{self.base_url}/collections",
                params={"limit": limit, "offset": 0},
                headers=headers,
                timeout=15,
            )
            data = resp.json()
            if not isinstance(data, dict):
                return []
            new_collections = []
            for col in data.get("collections", []):
                if not isinstance(col, dict):
                    continue
                slug = col.get("collection", "")
                if slug in self.seen_collections:
                    continue
                self.seen_collections.add(slug)

                contract_data = col.get("primary_asset_contracts", [{}])[0] if col.get("primary_asset_contracts") else {}
                contract_addr = contract_data.get("address", "")
                if not contract_addr:
                    continue

                new_collections.append({
                    "name": col.get("name", "Unknown"),
                    "slug": slug,
                    "contract_address": contract_addr,
                    "chain": col.get("chain", "ethereum"),
                    "featured": col.get("featured", False),
                    "created_at": col.get("created_date", ""),
                    "stats": col.get("stats", {}),
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })

            return new_collections
        except Exception as e:
            return []

    def resolve_url(self, url: str) -> dict:
        slug = None
        if "opensea.io/collection/" in url:
            slug = url.split("opensea.io/collection/")[1].split("/")[0].split("?")[0]
        elif "opensea.io/assets/" in url:
            parts = url.split("opensea.io/assets/")[1].split("/")
            if len(parts) >= 2:
                chain = parts[0]
                addr = parts[1].split("?")[0]
                return {"contract_address": addr, "chain": chain, "slug": slug, "source": "url_direct"}
        if not slug:
            return {"error": "Could not extract collection slug from URL"}
        headers = {}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        try:
            resp = requests.get(
                f"{self.base_url}/collections/{slug}",
                headers=headers,
                timeout=15,
            )
            if resp.status_code != 200:
                return {"error": f"OpenSea API returned {resp.status_code}"}
            data = resp.json()
            if not isinstance(data, dict):
                return {"error": f"OpenSea API returned unexpected format: {type(data).__name__}"}
            collection = data.get("collection")
            if not isinstance(collection, dict):
                collection = data
            name = collection.get("name", slug) if isinstance(collection, dict) else slug
            contracts = (collection.get("primary_asset_contracts") if isinstance(collection, dict) else None) or []
            if not contracts:
                addr = collection.get("address") or collection.get("contract_address", "") if isinstance(collection, dict) else ""
                if addr:
                    return {"contract_address": addr, "name": name, "slug": slug, "source": "opensea_api"}
                return {"error": "No contract found for this collection"}
            contract = contracts[0] if isinstance(contracts, list) else contracts
            addr = contract.get("address", "") if isinstance(contract, dict) else ""
            if not addr:
                return {"error": "No address in contract data"}
            return {"contract_address": addr, "name": name, "slug": slug, "source": "opensea_api"}
        except Exception as e:
            return {"error": str(e)}

    def get_trending_collections(self) -> list:
        headers = {}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key

        try:
            resp = requests.get(
                f"{self.base_url}/collections/trending",
                params={"limit": 10},
                headers=headers,
                timeout=15,
            )
            data = resp.json()
            results = []
            for col in data.get("collections", []):
                results.append({
                    "name": col.get("name"),
                    "slug": col.get("slug"),
                    "floor_price": col.get("floor_price"),
                    "volume": col.get("volume"),
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })
            return results
        except Exception:
            return []
