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
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return self._local.conn

    def _retry_on_fail(self, fn, *args, **kwargs):
        for attempt in range(3):
            try:
                return fn(*args, **kwargs)
            except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
                if attempt < 2:
                    self._local.conn = None
                    continue
                raise e

    def _init_db(self):
        c = self.conn
        self._migrate()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                label TEXT NOT NULL,
                address TEXT NOT NULL,
                encrypted_key TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                is_active INTEGER NOT NULL DEFAULT 1,
                UNIQUE(user_id, address)
            );
            CREATE TABLE IF NOT EXISTS monitored_contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                address TEXT NOT NULL,
                name TEXT,
                symbol TEXT,
                added_by INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                go_live_tx TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(user_id, address)
            );
            CREATE TABLE IF NOT EXISTS mint_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
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
                user_id INTEGER NOT NULL DEFAULT 0,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            );
            CREATE TABLE IF NOT EXISTS pending_mints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
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
            INSERT OR IGNORE INTO settings (user_id, key, value) VALUES (0, 'gas_strategy', 'auto');
            INSERT OR IGNORE INTO settings (user_id, key, value) VALUES (0, 'auto_mint', 'true');
        """)
        self.conn.commit()

    def _migrate(self):
        c = self.conn
        tables = ["wallets", "monitored_contracts", "mint_jobs", "settings", "pending_mints"]
        for table in tables:
            cols = [row["name"] for row in c.execute(f"PRAGMA table_info({table})").fetchall()]
            if "user_id" not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")

    def add_wallet(self, user_id: int, label: str, address: str, encrypted_key: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO wallets (user_id, label, address, encrypted_key) VALUES (?, ?, ?, ?)",
            (user_id, label, address, encrypted_key),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_wallets(self, user_id: int, active_only=True):
        q = "SELECT * FROM wallets WHERE user_id = ?"
        params = [user_id]
        if active_only:
            q += " AND is_active = 1"
        return self.conn.execute(q, params).fetchall()

    def get_wallet(self, wallet_id: int):
        return self.conn.execute(
            "SELECT * FROM wallets WHERE id = ?", (wallet_id,)
        ).fetchone()

    def delete_wallet(self, user_id: int, wallet_id: int):
        self.conn.execute(
            "UPDATE wallets SET is_active = 0 WHERE id = ? AND user_id = ?",
            (wallet_id, user_id),
        )
        self.conn.commit()

    def add_monitored_contract(self, user_id: int, address: str, name: str = None, symbol: str = None):
        addr = address.lower()
        existing = self.conn.execute(
            "SELECT id FROM monitored_contracts WHERE user_id = ? AND address = ?",
            (user_id, addr),
        ).fetchone()
        if existing:
            return existing["id"]
        cur = self.conn.execute(
            "INSERT INTO monitored_contracts (user_id, address, name, symbol) VALUES (?, ?, ?, ?)",
            (user_id, addr, name, symbol),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_monitored_contracts(self, user_id: int, status: str = None):
        q = "SELECT * FROM monitored_contracts WHERE user_id = ?"
        params = [user_id]
        if status:
            q += " AND status = ?"
            params.append(status)
        return self.conn.execute(q, params).fetchall()

    def get_all_monitored_contracts(self, status: str = None):
        q = "SELECT * FROM monitored_contracts"
        params = []
        if status:
            q += " WHERE status = ?"
            params.append(status)
        return self.conn.execute(q, params).fetchall()

    def get_contract_monitor_users(self, contract_address: str):
        rows = self.conn.execute(
            "SELECT DISTINCT user_id FROM monitored_contracts WHERE address = ? AND status = 'pending'",
            (contract_address.lower(),),
        ).fetchall()
        return [r["user_id"] for r in rows]

    def get_pending_mint_users(self, contract_address: str):
        rows = self.conn.execute(
            "SELECT DISTINCT user_id FROM pending_mints WHERE contract_address = ? AND status = 'pending'",
            (contract_address.lower(),),
        ).fetchall()
        return [r["user_id"] for r in rows]

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

    def get_setting(self, user_id: int, key: str):
        row = self.conn.execute(
            "SELECT value FROM settings WHERE user_id = ? AND key = ?", (user_id, key)
        ).fetchone()
        if row:
            return row["value"]
        row = self.conn.execute(
            "SELECT value FROM settings WHERE user_id = 0 AND key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_setting(self, user_id: int, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, key, value),
        )
        self.conn.commit()

    def add_mint_job(self, user_id: int, contract_address: str, wallet_id: int, quantity: int = 1):
        cur = self.conn.execute(
            "INSERT INTO mint_jobs (user_id, contract_address, wallet_id, quantity) VALUES (?, ?, ?, ?)",
            (user_id, contract_address, wallet_id, quantity),
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

    def get_mint_jobs(self, user_id: int, status: str = None, limit: int = 20):
        q = "SELECT * FROM mint_jobs WHERE user_id = ?"
        params = [user_id]
        if status:
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return self.conn.execute(q, params).fetchall()

    def add_pending_mint(self, user_id: int, contract_address: str, wallet_id: int, quantity: int = 1,
                          mint_price_wei: str = "0", fn_sig: str = None,
                          gas_strategy: str = None, chat_id: int = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO pending_mints (user_id, contract_address, wallet_id, quantity, mint_price_wei, fn_sig, gas_strategy, chat_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, contract_address.lower(), wallet_id, quantity, mint_price_wei, fn_sig, gas_strategy, chat_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_pending_mints(self, user_id: int, status: str = "pending"):
        return self.conn.execute(
            "SELECT * FROM pending_mints WHERE user_id = ? AND status = ? ORDER BY created_at ASC",
            (user_id, status),
        ).fetchall()

    def get_all_pending_mints(self, status: str = "pending"):
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

    def update_pending_mint_by_contract(self, user_id: int, contract_address: str, status: str):
        self.conn.execute(
            "UPDATE pending_mints SET status = ? WHERE user_id = ? AND contract_address = ? AND status = 'pending'",
            (status, user_id, contract_address.lower()),
        )
        self.conn.commit()

    def delete_pending_mint(self, mint_id: int):
        self.conn.execute("DELETE FROM pending_mints WHERE id = ?", (mint_id,))
        self.conn.commit()
