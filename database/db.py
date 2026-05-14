import sqlite3
import threading
import os
from datetime import datetime, timezone


class Database:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    @property
    def conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_db(self):
        c = self.conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                address TEXT NOT NULL UNIQUE,
                encrypted_key TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                is_active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS monitored_contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT NOT NULL UNIQUE,
                name TEXT,
                symbol TEXT,
                added_by INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                go_live_tx TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS mint_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_address TEXT NOT NULL,
                wallet_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'queued',
                tx_hashes TEXT,
                gas_price_gwei REAL,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (wallet_id) REFERENCES wallets(id)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_mints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_address TEXT NOT NULL,
                wallet_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                mint_price_wei TEXT,
                fn_sig TEXT,
                gas_strategy TEXT,
                chat_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (wallet_id) REFERENCES wallets(id)
            );
            INSERT OR IGNORE INTO settings (key, value) VALUES ('gas_strategy', 'fast');
            INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_mint', 'true');
        """)
        self.conn.commit()

    def add_wallet(self, label: str, address: str, encrypted_key: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO wallets (label, address, encrypted_key) VALUES (?, ?, ?)",
            (label, address, encrypted_key),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_wallets(self, active_only=True):
        q = "SELECT * FROM wallets"
        if active_only:
            q += " WHERE is_active = 1"
        return self.conn.execute(q).fetchall()

    def get_wallet(self, wallet_id: int):
        return self.conn.execute(
            "SELECT * FROM wallets WHERE id = ?", (wallet_id,)
        ).fetchone()

    def delete_wallet(self, wallet_id: int):
        self.conn.execute("UPDATE wallets SET is_active = 0 WHERE id = ?", (wallet_id,))
        self.conn.commit()

    def add_monitored_contract(self, address: str, name: str = None, symbol: str = None):
        addr = address.lower()
        existing = self.conn.execute(
            "SELECT id FROM monitored_contracts WHERE address = ?", (addr,)
        ).fetchone()
        if existing:
            return existing["id"]
        cur = self.conn.execute(
            "INSERT INTO monitored_contracts (address, name, symbol) VALUES (?, ?, ?)",
            (addr, name, symbol),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_monitored_contracts(self, status: str = None):
        q = "SELECT * FROM monitored_contracts"
        params = []
        if status:
            q += " WHERE status = ?"
            params.append(status)
        return self.conn.execute(q, params).fetchall()

    def update_contract_status(self, contract_id: int, status: str, go_live_tx: str = None):
        q = "UPDATE monitored_contracts SET status = ?"
        params = [status]
        if go_live_tx:
            q += ", go_live_tx = ?"
            params.append(go_live_tx)
        q += " WHERE id = ?"
        params.append(contract_id)
        self.conn.execute(q, params)
        self.conn.commit()

    def get_setting(self, key: str):
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
        self.conn.commit()

    def add_mint_job(self, contract_address: str, wallet_id: int, quantity: int = 1):
        cur = self.conn.execute(
            "INSERT INTO mint_jobs (contract_address, wallet_id, quantity) VALUES (?, ?, ?)",
            (contract_address, wallet_id, quantity),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_mint_job(self, job_id: int, status: str, tx_hashes: str = None, gas_price_gwei: float = None, error: str = None):
        q = "UPDATE mint_jobs SET status = ?"
        params = [status]
        if tx_hashes:
            q += ", tx_hashes = ?"
            params.append(tx_hashes)
        if gas_price_gwei:
            q += ", gas_price_gwei = ?"
            params.append(gas_price_gwei)
        if error:
            q += ", error = ?"
            params.append(error)
        q += " WHERE id = ?"
        params.append(job_id)
        self.conn.execute(q, params)
        self.conn.commit()

    def get_mint_jobs(self, status: str = None, limit: int = 20):
        q = "SELECT * FROM mint_jobs"
        params = []
        if status:
            q += " WHERE status = ?"
            params.append(status)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return self.conn.execute(q, params).fetchall()

    def add_pending_mint(self, contract_address: str, wallet_id: int, quantity: int = 1,
                          mint_price_wei: str = "0", fn_sig: str = None,
                          gas_strategy: str = None, chat_id: int = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO pending_mints (contract_address, wallet_id, quantity, mint_price_wei, fn_sig, gas_strategy, chat_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (contract_address.lower(), wallet_id, quantity, mint_price_wei, fn_sig, gas_strategy, chat_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_pending_mints(self, status: str = "pending"):
        return self.conn.execute(
            "SELECT * FROM pending_mints WHERE status = ? ORDER BY created_at ASC",
            (status,),
        ).fetchall()

    def update_pending_mint(self, mint_id: int, status: str, retry_count: int = None,
                             fn_sig: str = None):
        q = "UPDATE pending_mints SET status = ?"
        params = [status]
        if retry_count is not None:
            q += ", retry_count = ?"
            params.append(retry_count)
        if fn_sig is not None:
            q += ", fn_sig = ?"
            params.append(fn_sig)
        q += " WHERE id = ?"
        params.append(mint_id)
        self.conn.execute(q, params)
        self.conn.commit()

    def update_pending_mint_by_contract(self, contract_address: str, status: str):
        self.conn.execute(
            "UPDATE pending_mints SET status = ? WHERE contract_address = ? AND status = 'pending'",
            (status, contract_address.lower()),
        )
        self.conn.commit()

    def delete_pending_mint(self, mint_id: int):
        self.conn.execute("DELETE FROM pending_mints WHERE id = ?", (mint_id,))
        self.conn.commit()
