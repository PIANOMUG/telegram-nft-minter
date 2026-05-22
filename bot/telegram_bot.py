import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
from telegram.constants import ParseMode

from database.db import Database
from minter.wallet import WalletManager
from minter.gas import GasOptimizer
from minter.engine import MintingEngine
from monitor.orchestrator import MonitorOrchestrator
from monitor.opensea_monitor import OpenSeaMonitor

logger = logging.getLogger(__name__)

MENU = {
    "👛 Wallets": "/wallets",
    "➕ Add Wallet": "/addwallet",
    "✨ Create Wallet": "/createwallet",
    "❌ Delete Wallet": "/deletewallet",
    "💰 Balance": "/balance",
    "🎨 Mint": "/mint",
    "⚡ Fast Mint": "/fastmint",
    "🖼️ OpenSea Mint": "/openseamint",
    "👁️ Monitor": "/monitor",
    "📋 Contracts": "/contracts",
    "📅 Schedule": "/schedule",
    "🤖 Auto Mint On": "/autoon",
    "⛔ Auto Off": "/autooff",
    "⛽ Gas Prices": "/gas",
    "🎯 Set Gas": "/setgas",
    "🔗 Set Chain": "/setchain",
    "📊 Status": "/status",
    "ℹ️ Help": "/help",
}

ARGLESS = {"/wallets", "/balance", "/contracts", "/schedule", "/autoon",
           "/autooff", "/gas", "/status", "/help", "/createwallet", "/test", "/ping"}


def _build_menu():
    keys = list(MENU.keys())
    rows = []
    for i in range(0, len(keys), 2):
        row = [KeyboardButton(keys[i])]
        if i + 1 < len(keys):
            row.append(KeyboardButton(keys[i + 1]))
        rows.append(row)
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


class NFTBot:
    def __init__(self, token: str, db: Database, wallet_mgr: WalletManager,
                 gas_opt: GasOptimizer, engine: MintingEngine,
                 monitor: MonitorOrchestrator, allowed_users: list = None,
                 opensea: OpenSeaMonitor = None, chain_mgr=None):
        self.token = token
        self.db = db
        self.wallet_mgr = wallet_mgr
        self.gas_opt = gas_opt
        self.engine = engine
        self.monitor = monitor
        self.allowed_users = allowed_users or []
        self.opensea = opensea or OpenSeaMonitor()
        self.chain_mgr = chain_mgr
        self.app = Application.builder().token(token).build()
        self._register_handlers()
        self._register_monitor_callbacks()

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("wallets", self.cmd_wallets))
        self.app.add_handler(CommandHandler("addwallet", self.cmd_add_wallet))
        self.app.add_handler(CommandHandler("createwallet", self.cmd_create_wallet))
        self.app.add_handler(CommandHandler("deletewallet", self.cmd_delete_wallet))
        self.app.add_handler(CommandHandler("monitor", self.cmd_monitor))
        self.app.add_handler(CommandHandler("contracts", self.cmd_contracts))
        self.app.add_handler(CommandHandler("mint", self.cmd_mint))
        self.app.add_handler(CommandHandler("fastmint", self.cmd_fast_mint))
        self.app.add_handler(CommandHandler("gas", self.cmd_gas))
        self.app.add_handler(CommandHandler("setgas", self.cmd_set_gas))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("balance", self.cmd_balance))
        self.app.add_handler(CommandHandler("autoon", self.cmd_auto_on))
        self.app.add_handler(CommandHandler("autooff", self.cmd_auto_off))
        self.app.add_handler(CommandHandler("schedule", self.cmd_schedule))
        self.app.add_handler(CommandHandler("test", self.cmd_test))
        self.app.add_handler(CommandHandler("ping", self.cmd_ping))
        self.app.add_handler(CommandHandler("setchain", self.cmd_set_chain))
        self.app.add_handler(CommandHandler("openseamint", self.cmd_opensea_mint))
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))
        self.app.add_error_handler(self.handle_error)
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.cmd_echo))
        logger.info(f"Registered {len(self.app.handlers.get(0, []))} handlers")

    def _user_id(self, update: Update) -> int:
        return update.effective_user.id if update.effective_user else 0

    def _user_chain(self, uid: int) -> int:
        chain_str = self.db.get_setting(uid, "chain_id")
        if chain_str:
            try:
                return int(chain_str)
            except (ValueError, TypeError):
                pass
        return 1

    def _check_auth(self, update: Update) -> bool:
        if not self.allowed_users:
            return True
        try:
            return update.effective_user and update.effective_user.id in self.allowed_users
        except Exception:
            return False

    async def _reply(self, msg_or_update, text: str, **kwargs):
        msg = msg_or_update if hasattr(msg_or_update, "reply_text") else msg_or_update.message
        try:
            kwargs.setdefault("parse_mode", ParseMode.MARKDOWN)
            return await msg.reply_text(text, **kwargs)
        except Exception:
            kwargs.pop("parse_mode", None)
            try:
                return await msg.reply_text(text, **kwargs)
            except Exception as e2:
                logger.warning(f"Failed to send reply: {e2}")
                return None

    async def _safe_edit(self, msg, text: str, **kwargs):
        try:
            kwargs.setdefault("parse_mode", ParseMode.MARKDOWN)
            return await msg.edit_text(text, **kwargs)
        except Exception:
            kwargs.pop("parse_mode", None)
            try:
                return await msg.edit_text(text, **kwargs)
            except Exception as e2:
                logger.warning(f"Failed to edit message: {e2}")

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            await self._reply(update, "Unauthorized.")
            return
        text = (
            "🚀 **NFT SuperMinter Bot**\n\n"
            "Monitor & mint NFTs instantly.\n\n"
            "Tap a button below to get started 👇"
        )
        await update.message.reply_text(text, reply_markup=_build_menu())

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.cmd_start(update, context)

    async def cmd_wallets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        wallets = self.db.get_wallets(uid)
        if not wallets:
            await self._reply(update, "No wallets. Use /createwallet or /addwallet.")
            return
        lines = ["**Your Wallets:**"]
        for w in wallets:
            addr = w["address"][:6] + "..." + w["address"][-4:]
            lines.append(f"`{w['id']}`. {w['label']}: `{addr}`")
        await self._reply(update, "\n".join(lines))

    async def cmd_add_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        args = context.args
        if not args:
            await self._reply(update, "Usage: /addwallet `<private_key_hex>`")
            return
        pk = args[0].strip().strip("<>`'\"")
        if pk.startswith("0x"):
            pk = pk[2:]
        pk = pk.strip()
        if not pk or len(pk) != 64:
            await self._reply(update, "Invalid private key (must be 64 hex characters).")
            return
        try:
            address = self.wallet_mgr.import_private_key(pk)
            encrypted = self.wallet_mgr.encrypt_private_key(pk)
            label = f"wallet_{address[:6]}"
            self.db.add_wallet(self._user_id(update), label, address, encrypted)
            await self._reply(update,
                f"Wallet imported: `{address[:6]}...{address[-4:]}`",
            )
        except Exception as e:
            await self._reply(update, f"Error: {e}")

    async def cmd_create_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        address, pk = self.wallet_mgr.create_wallet()
        encrypted = self.wallet_mgr.encrypt_private_key(pk)
        label = f"wallet_{address[:6]}"
        self.db.add_wallet(uid, label, address, encrypted)
        await self._reply(update,
            f"**New Wallet Created**\nAddress: `{address}`\nPrivate Key: `{pk}`\n\n"
            "**SAVE THIS KEY. It will not be shown again.**",
        )

    async def cmd_delete_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        args = context.args
        if not args:
            await self._reply(update, "Usage: /deletewallet `<wallet_id>`")
            return
        try:
            wallet_id = int(args[0])
            self.db.delete_wallet(self._user_id(update), wallet_id)
            await self._reply(update, f"Wallet {wallet_id} deleted.")
        except Exception as e:
            await self._reply(update, f"Error: {e}")

    async def cmd_monitor(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        args = context.args
        if not args:
            await self._reply(update, "Usage: /monitor `<contract_address>`")
            return
        addr = args[0].strip()
        try:
            self.monitor.add_contract(addr)
            info = self.engine.get_contract_info(addr)
            cid = self.db.add_monitored_contract(uid, addr, info.get("name"), info.get("symbol"))
            mint_price_eth = info.get('mint_price', 0) / 1e18
            await self._reply(update,
                f"**Monitoring Contract**\n"
                f"Address: `{addr}`\n"
                f"Name: {info.get('name', 'Unknown')}\n"
                f"Symbol: {info.get('symbol', '?')}\n"
                f"Mint Price: {mint_price_eth:.8f} ETH\n"
                f"Mint Method: `{info.get('fn_name')}`\n"
                f"ID: `{cid}`",
            )
        except Exception as e:
            await self._reply(update, f"Error monitoring contract: {e}")

    async def cmd_contracts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        contracts = self.db.get_monitored_contracts(uid)
        if not contracts:
            await self._reply(update, "No contracts being monitored.")
            return
        lines = ["**Monitored Contracts:**"]
        for c in contracts:
            addr = c["address"][:6] + "..." + c["address"][-4:]
            lines.append(f"`{c['id']}`. {c.get('name', '?')} ({addr}) - **{c['status']}**")
        await self._reply(update, "\n".join(lines))

    async def cmd_mint(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        chain_id = self._user_chain(uid)
        args = context.args
        if not args:
            await self._reply(update, "Usage: /mint `<contract_address>` `[quantity=1]`")
            return
        contract = args[0].strip()
        try:
            quantity = int(args[1]) if len(args) > 1 else 1
        except ValueError:
            await self._reply(update, "Quantity must be a number.")
            return
        wallets = self.db.get_wallets(uid)
        if not wallets:
            await self._reply(update, "No wallets. Add one first.")
            return

        wallet = wallets[0]
        try:
            pk = self.wallet_mgr.decrypt_private_key(wallet["encrypted_key"])
            if not pk:
                await self._reply(update, "Could not decrypt wallet key.")
                return
        except Exception:
            await self._reply(update, "Could not decrypt wallet key.")
            return
        sender = wallet["address"]

        msg = await self._reply(update, f"Detecting whitelist tier for `{sender[:6]}...{sender[-4:]}`...")
        if not msg:
            return

        info = self.engine.get_contract_info(contract)
        mint_price = info.get("mint_price", 0)

        fn_name, fn_params, fn_sig = self.engine.detect_available_mint(
            contract, sender, mint_price, quantity
        )

        if fn_name:
            gas_strategy = self.db.get_setting(uid, "gas_strategy")
            await self._safe_edit(msg, f"Whitelist tier: **{fn_sig}**\nMinting...")
            result = self.engine.mint_single(contract, pk, quantity, gas_strategy, chain_id)
            job_id = self.db.add_mint_job(uid, contract, wallet["id"], quantity)
            if result["success"]:
                self.db.update_mint_job(job_id, "confirmed",
                                        tx_hashes=result["tx_hash"],
                                        gas_price_gwei=result["gas_price_gwei"])
                await self._safe_edit(msg,
                    f"**Mint Sent!**\n"
                    f"Contract: `{contract[:6]}...{contract[-4:]}`\n"
                    f"Qty: {quantity}\n"
                    f"Gas: {result['gas_price_gwei']} gwei\n"
                    f"Method: **{fn_sig}**\n"
                    f"[View Tx]({result['explorer_url']})"
                )
            else:
                self.db.update_mint_job(job_id, "failed", error=result.get("error"))
                await self._safe_edit(msg, f"Mint failed: {result.get('error')}")
        else:
            gas_strategy = self.db.get_setting(uid, "gas_strategy")
            pending_id = self.db.add_pending_mint(
                user_id=uid,
                contract_address=contract,
                wallet_id=wallet["id"],
                quantity=quantity,
                mint_price_wei=str(mint_price),
                fn_sig=None,
                gas_strategy=gas_strategy,
                chat_id=update.effective_user.id,
            )
            self.monitor.register_pending_mint(
                contract_address=contract,
                wallet_address=sender,
                mint_price_wei=mint_price,
                quantity=quantity,
                private_key=pk,
            )
            await self._safe_edit(msg,
                f"**Mint Not Live Yet**\n"
                f"Contract: `{contract[:6]}...{contract[-4:]}`\n"
                f"Wallet: `{sender[:6]}...{sender[-4:]}`\n"
                f"Tier: Checking all whitelist/public tiers\n"
                f"Qty: {quantity}\n\n"
                f"Bot will auto-mint the moment `{contract[:6]}...{contract[-4:]}` goes live.\n"
                f"High-speed mempool scanner active (0.1s check).\n"
                f"Use `/schedule` to view pending mints.\n"
                f"ID: `{pending_id}`"
            )
            logger.info(f"Queued pending mint #{pending_id} for {contract}")

    async def cmd_fast_mint(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        chain_id = self._user_chain(uid)
        args = context.args
        if not args:
            await self._reply(update, "Usage: /fastmint `<contract>` `[qty=1]` `[rounds=3]`")
            return
        contract = args[0].strip()
        try:
            quantity = int(args[1]) if len(args) > 1 else 1
            rounds = int(args[2]) if len(args) > 2 else 3
        except ValueError:
            await self._reply(update, "Quantity and rounds must be numbers.")
            return
        wallets = self.db.get_wallets(uid)
        if not wallets:
            await self._reply(update, "No wallets.")
            return
        msg = await self._reply(update, f"Super-speed minting x{quantity} in {rounds} rounds...")
        if not msg:
            return
        wallet = wallets[0]
        pk = self.wallet_mgr.decrypt_private_key(wallet["encrypted_key"])
        gas_strategy = self.db.get_setting(uid, "gas_strategy")
        results = self.engine.mint_parallel_single_wallet(contract, pk, quantity, rounds, gas_strategy, chain_id)
        successes = [r for r in results if r["success"]]
        fails = [r for r in results if not r["success"]]
        text = (
            f"**Fast Mint Complete**\n"
            f"Successful: {len(successes)}/{len(results)}\n"
            f"Failed: {len(fails)}\n"
        )
        if successes:
            hashes = "\n".join([f"[Tx]({s['explorer_url']})" for s in successes[:5]])
            text += f"Txs:\n{hashes}"
        if fails:
            text += f"\nFirst error: {fails[0].get('error', 'unknown')}"
        await self._safe_edit(msg, text)

    async def cmd_opensea_mint(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        chain_id = self._user_chain(uid)
        args = context.args
        if not args:
            await self._reply(update, "Usage: /openseamint `<opensea_url>` `[qty=1]`")
            return
        url = args[0].strip()
        try:
            quantity = int(args[1]) if len(args) > 1 else 1
        except ValueError:
            await self._reply(update, "Quantity must be a number.")
            return
        wallets = self.db.get_wallets(uid)
        if not wallets:
            await self._reply(update, "No wallets. Add one first.")
            return
        resolved = self.opensea.resolve_url(url)
        if "error" in resolved:
            await self._reply(update, f"Failed to resolve URL: {resolved['error']}")
            return
        contract = resolved["contract_address"]
        name = resolved.get("name", "Unknown")
        await self._reply(update, f"Found: {name}\nContract: {contract}\nMinting...")
        wallet = wallets[0]
        pk = self.wallet_mgr.decrypt_private_key(wallet["encrypted_key"])
        gas_strategy = self.db.get_setting(uid, "gas_strategy")
        mint_result = self.engine.mint_single(contract, pk, quantity, gas_strategy or "auto", chain_id)
        if mint_result["success"]:
            await self._reply(update, f"Minted!\nName: {name}\nQty: {quantity}\nTx: {mint_result['explorer_url']}")
        else:
            await self._reply(update, f"Mint failed: {mint_result.get('error')}")

    async def cmd_gas(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        prices = self.gas_opt.get_gas_prices()
        text = (
            f"**Gas Prices**\n"
            f"Safe Low: {prices.safe_low} gwei\n"
            f"Standard: {prices.standard} gwei\n"
            f"Fast: {prices.fast} gwei\n"
            f"Instant: {prices.instant} gwei\n"
            f"Base Fee: {prices.base_fee} gwei\n"
            f"Priority Fee: {prices.priority_fee} gwei\n"
        )
        await self._reply(update, text)

    async def cmd_set_gas(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        args = context.args
        valid = ("auto", "slow", "average", "fast", "instant", "max")
        if not args or args[0] not in valid:
            await self._reply(update,
                "Usage: /setgas `<auto|slow|average|fast|instant|max>`"
            )
            return
        strategy = args[0]
        self.db.set_setting(self._user_id(update), "gas_strategy", strategy)
        await self._reply(update, f"Gas strategy set to **{strategy}**")

    async def cmd_set_chain(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        args = context.args
        chains = {1: "Ethereum", 8453: "Base", 42161: "Arbitrum"}
        if not args:
            current = self._user_chain(uid)
            text = f"**Current Chain:** {chains.get(current, 'Unknown')} (`{current}`)\n\n**Available:**\n"
            for cid, name in chains.items():
                text += f"`{cid}` - {name}\n"
            text += "\nUsage: `/setchain <id>`"
            await self._reply(update, text)
            return
        try:
            cid = int(args[0])
            if cid not in chains:
                await self._reply(update, f"Unsupported chain. Use: {', '.join(f'{k} ({v})' for k, v in chains.items())}")
                return
            self.db.set_setting(uid, "chain_id", str(cid))
            await self._reply(update, f"Switched to **{chains[cid]}** (`{cid}`)")
        except ValueError:
            await self._reply(update, "Chain ID must be a number.")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        wallet_count = len(self.db.get_wallets(uid))
        monitored = len(self.db.get_monitored_contracts(uid))
        jobs = self.db.get_mint_jobs(uid, limit=5)
        gas_strategy = self.db.get_setting(uid, "gas_strategy")
        auto_mint = self.db.get_setting(uid, "auto_mint")
        cid = self._user_chain(uid)
        chain_name = self.chain_mgr.get_chain_name(cid) if self.chain_mgr else "Ethereum"
        text = (
            f"**Bot Status**\n"
            f"Chain: {chain_name} (`{cid}`)\n"
            f"Wallets: {wallet_count}\n"
            f"Monitored Contracts: {monitored}\n"
            f"Gas Strategy: {gas_strategy}\n"
            f"Auto-Mint: {auto_mint}\n"
            f"Recent Jobs: {len(jobs)}\n"
        )
        await self._reply(update, text)

    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        try:
            from web3 import Web3
            w3 = self.engine.w3
            wallets = self.db.get_wallets(uid)
            if not wallets:
                await self._reply(update, "No wallets.")
                return
            lines = ["**Wallet Balances:**"]
            for w in wallets:
                bal = w3.eth.get_balance(w["address"])
                eth = Web3.from_wei(bal, "ether")
                lines.append(f"`{w['label']}`: `{eth:.4f}` ETH")
            await self._reply(update, "\n".join(lines))
        except Exception as e:
            await self._reply(update, f"Error: {e}")

    async def cmd_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        pending = self.db.get_pending_mints(uid, status="pending")
        if not pending:
            await self._reply(update, "No pending mints.")
            return
        lines = ["**Pending Mints (auto when live):**"]
        for p in pending:
            addr = p["contract_address"][:6] + "..." + p["contract_address"][-4:]
            lines.append(f"`{p['id']}`. `{addr}` x{p['quantity']} (retries: {p['retry_count']})")
        await self._reply(update, "\n".join(lines))

    async def cmd_auto_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        uid = self._user_id(update)
        self.db.set_setting(uid, "auto_mint", "true")
        await self._reply(update, "Auto-mint enabled. Will mint when contracts go live.")

    async def cmd_auto_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_auth(update):
            return
        self.db.set_setting(self._user_id(update), "auto_mint", "false")
        await self._reply(update, "Auto-mint disabled.")

    async def cmd_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"Test command from user {update.effective_user.id}")
        if not self._check_auth(update):
            await self._reply(update, "Unauthorized.")
            return
        await self._reply(update, "Bot is working! Send /start for commands.")

    async def cmd_ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"Ping from {update.effective_user.id if update.effective_user else 'unknown'}")
        await self._reply(update, "pong!")

    async def cmd_echo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (update.message.text or "").strip()
        if text in MENU:
            cmd = MENU[text]
            context.args = []
            if cmd in ARGLESS:
                await getattr(self, f"cmd_{cmd[1:]}")(update, context)
            else:
                usage = {
                    "/addwallet": "Usage: /addwallet `<private_key>`\n\nPaste your private key to import a wallet.",
                    "/deletewallet": "Usage: /deletewallet `<id>`\n\nUse /wallets to find the ID.",
                    "/mint": "Usage: /mint `<contract_address>` `[quantity=1]`",
                    "/fastmint": "Usage: /fastmint `<contract>` `[qty=1]` `[rounds=3]`",
                    "/openseamint": "Usage: /openseamint `<opensea_url>` `[qty=1]`",
                    "/monitor": "Usage: /monitor `<contract_address>`",
                    "/setgas": "Usage: /setgas `<auto|slow|average|fast|instant|max>`",
                    "/setchain": "Usage: /setchain `<1|8453|42161>`\n\n1 = Ethereum, 8453 = Base, 42161 = Arbitrum",
                }
                await self._reply(update, usage.get(cmd, f"Type `{cmd}` with the required arguments."))
            return
        await self._reply(update, f"You said: {update.message.text}")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        parts = data.split(":")
        if parts[0] == "mint_now" and len(parts) > 1:
            await self._auto_mint_contract(parts[1], query)
        else:
            await query.edit_message_text(f"Unknown action: {data}")

    async def _auto_mint_contract(self, contract: str, query):
        uid = query.from_user.id if query.from_user else 0
        chain_id = self._user_chain(uid)
        wallets = self.db.get_wallets(uid)
        if not wallets:
            await query.edit_message_text("No wallets configured. Can't mint.")
            return
        wallet = wallets[0]
        pk = self.wallet_mgr.decrypt_private_key(wallet["encrypted_key"])
        gas_strategy = self.db.get_setting(uid, "gas_strategy")
        result = self.engine.mint_single(contract, pk, 1, gas_strategy or "auto", chain_id)
        if result["success"]:
            await self._safe_edit(query.message,
                f"**Auto-Mint Sent!**\n"
                f"Contract: `{contract[:6]}...{contract[-4:]}`\n"
                f"[View Tx]({result['explorer_url']})"
            )
        else:
            await query.edit_message_text(f"Auto-mint failed: {result.get('error')}")

    def _register_monitor_callbacks(self):
        self.monitor.on_new_mint_opportunity(self._on_mint_opportunity)

    def _sync_pending_mints(self):
        pending = self.db.get_all_pending_mints(status="pending")
        for pm in pending:
            try:
                wallet = self.db.get_wallet(pm["wallet_id"])
                if not wallet:
                    continue
                pk = self.wallet_mgr.decrypt_private_key(wallet["encrypted_key"])
                sender = self.engine.w3.eth.account.from_key(pk).address
                self.monitor.register_pending_mint(
                    contract_address=pm["contract_address"],
                    wallet_address=sender,
                    mint_price_wei=int(pm["mint_price_wei"] or "0"),
                    quantity=pm["quantity"],
                    private_key=pk,
                )
            except Exception as e:
                logger.warning(f"Sync pending mint {pm.get('id')}: {e}")

    def _on_mint_opportunity(self, data: dict):
        asyncio.run(self._broadcast_opportunity(data))

    async def _broadcast_opportunity(self, data: dict):
        event_type = data.get("type", "opportunity")
        contract = data.get("contract", "")
        name = data.get("name", "Unknown")
        source = data.get("source", "unknown")

        if event_type == "mint_now_live":
            pk = data.get("private_key")
            quantity = data.get("quantity", 1)
            uids = self.db.get_pending_mint_users(contract)
            if pk and uids:
                gs = self.db.get_setting(uids[0], "gas_strategy") or "auto"
                cid = int(self.db.get_setting(uids[0], "chain_id") or "1")
                result = self.engine.mint_single(contract, pk, quantity, gs, cid)
                if result["success"]:
                    text = (
                        f"**Instant Auto-Mint!**\n"
                        f"Contract: `{contract[:6]}...{contract[-4:]}`\n"
                        f"Qty: {quantity}\n"
                        f"[View Tx]({result['explorer_url']})"
                    )
                    for uid in uids:
                        self.db.update_pending_mint_by_contract(uid, contract, "confirmed")
                    logger.info(f"Instant mint for {contract}: {result['tx_hash']}")
                else:
                    text = f"Instant mint failed for `{contract[:6]}...{contract[-4:]}`: {result.get('error')}"
                    for uid in uids:
                        self.db.update_pending_mint_by_contract(uid, contract, "pending")
                for uid in uids:
                    try:
                        await self.app.bot.send_message(chat_id=uid, text=text)
                    except Exception:
                        pass
            return

        monitored_uids = self.db.get_contract_monitor_users(contract)
        if not monitored_uids:
            logger.warning(f"No users monitoring {contract}")
            return

        for uid in monitored_uids:
            try:
                auto_mint = self.db.get_setting(uid, "auto_mint") == "true"
                wallets = self.db.get_wallets(uid)
                text = (
                    f"**NFT Mint Opportunity!**\n"
                    f"Contract: `{contract[:6]}...{contract[-4:]}`\n"
                    f"Name: {name}\n"
                    f"Source: {source}\n"
                )
                if auto_mint and wallets:
                    wallet = wallets[0]
                    pk = self.wallet_mgr.decrypt_private_key(wallet["encrypted_key"])
                    gs = self.db.get_setting(uid, "gas_strategy") or "auto"
                    cid = int(self.db.get_setting(uid, "chain_id") or "1")
                    result = self.engine.mint_single(contract, pk, 1, gs, cid)
                    if result["success"]:
                        text += f"\n**Minted!** [Tx]({result['explorer_url']})"
                    else:
                        text += f"\nMint failed: {result.get('error')}"
                    try:
                        await self.app.bot.send_message(chat_id=uid, text=text)
                    except Exception as e:
                        logger.error(f"Auto-mint send to {uid}: {e}")
                else:
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("Mint Now", callback_data=f"mint_now:{contract}")]
                    ])
                    try:
                        await self.app.bot.send_message(
                            chat_id=uid, text=text,
                            reply_markup=keyboard,
                        )
                    except Exception as e:
                        logger.error(f"Alert send to {uid}: {e}")
            except Exception as e:
                logger.error(f"Error processing opportunity for user {uid}: {e}")

    async def handle_error(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Handler error: {context.error}", exc_info=context.error)
        if update and update.effective_message:
            await update.effective_message.reply_text(f"Error: {context.error}")

    async def send_alert(self, chat_id: int, text: str):
        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Send alert error: {e}")

    async def _check_pending_mints(self, context: ContextTypes.DEFAULT_TYPE):
        pending = self.db.get_all_pending_mints(status="pending")
        if not pending:
            return
        synced = False
        for pm in pending:
            try:
                wallet = self.db.get_wallet(pm["wallet_id"])
                if not wallet:
                    self.db.update_pending_mint(pm["id"], "failed")
                    continue
                pk = self.wallet_mgr.decrypt_private_key(wallet["encrypted_key"])
                sender = self.engine.w3.eth.account.from_key(pk).address

                if not synced:
                    self.monitor.register_pending_mint(
                        contract_address=pm["contract_address"],
                        wallet_address=sender,
                        mint_price_wei=int(pm["mint_price_wei"] or "0"),
                        quantity=pm["quantity"],
                        private_key=pk,
                    )
                    synced = True
            except Exception as e:
                logger.error(f"Pending mint #{pm.get('id', '?')} sync error: {e}")

    def run(self):
        if self.app.job_queue:
            self.app.job_queue.run_repeating(self._check_pending_mints, interval=15, first=10)
        self.app.run_polling(
            timeout=1,
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
            bootstrap_retries=10,

        )
