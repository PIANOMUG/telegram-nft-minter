import logging
import asyncio
import discord
from discord.ext import commands

from config import DISCORD_BOT_TOKEN, ALLOWED_CHANNELS, COOLDOWN_SECONDS
from .llm import LLMClient
from .memory import ConversationMemory

logger = logging.getLogger(__name__)


class AIBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.llm = LLMClient()
        self.memory = ConversationMemory()
        self._cooldowns = {}

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} servers:")
        for g in self.guilds:
            logger.info(f"  - {g.name} ({g.id})")

    async def on_message(self, msg: discord.Message):
        if msg.author.bot:
            return
        if msg.content.startswith("!"):
            await self._handle_command(msg)
            return
        await self._handle_conversation(msg)

    async def _handle_conversation(self, msg: discord.Message):
        if not self._should_respond(msg):
            return
        cooldown_key = f"{msg.guild.id}:{msg.channel.id}" if msg.guild else str(msg.channel.id)
        now = asyncio.get_event_loop().time()
        last = self._cooldowns.get(cooldown_key, 0)
        if now - last < COOLDOWN_SECONDS:
            return
        self._cooldowns[cooldown_key] = now

        channel_name = f"#{msg.channel.name}" if hasattr(msg.channel, "name") else "DM"
        server_name = msg.guild.name if msg.guild else "DM"
        ctx_label = f"{server_name}/{channel_name}"

        async with msg.channel.typing():
            sid = msg.guild.id if msg.guild else 0
            self.memory.add(sid, "user", f"{msg.author.display_name}: {msg.content}")
            context = self.memory.get_context(sid)
            reply = self.llm.chat(context, server_name)
            if reply:
                self.memory.add(sid, "assistant", reply)
                chunks = [reply[i:i+1900] for i in range(0, len(reply), 1900)]
                for chunk in chunks:
                    await msg.reply(chunk, mention_author=False)
                    await asyncio.sleep(0.5)
                logger.info(f"[{ctx_label}] {msg.author}: {msg.content[:60]}... -> replied")

    def _should_respond(self, msg: discord.Message) -> bool:
        if ALLOWED_CHANNELS and msg.channel.id not in ALLOWED_CHANNELS:
            return False
        if self.user in msg.mentions:
            return True
        if isinstance(msg.channel, discord.DMChannel):
            return True
        if msg.reference and msg.reference.resolved:
            resolved = msg.reference.resolved
            if isinstance(resolved, discord.Message) and resolved.author == self.user:
                return True
        return False

    async def _handle_command(self, msg: discord.Message):
        cmd = msg.content.lower().split()[0]
        if cmd == "!clear":
            sid = msg.guild.id if msg.guild else 0
            self.memory.clear(sid)
            await msg.reply("Conversation memory cleared.", mention_author=False)
        elif cmd == "!ping":
            await msg.reply("pong!", mention_author=False)

    def run_bot(self):
        if not DISCORD_BOT_TOKEN:
            logger.error("DISCORD_BOT_TOKEN not set")
            return
        self.run(DISCORD_BOT_TOKEN, log_handler=None)
