from datetime import datetime, timezone
from typing import Optional, List, Tuple
import discord
from redbot.core import commands


class LoggingHelper:
    """Handles all logging operations, including Discord channel and console output."""

    def __init__(self, bot: commands.Bot, log_channel_id: int):
        self.bot = bot
        self.log_channel_id = log_channel_id
        self._init_log_queue: List[Tuple[str, str]] = []

    async def log_to_discord(self, message: str, level: str = "INFO", embed: Optional[discord.Embed] = None):
        """Sends a formatted log message to the designated Discord log channel."""

        if not self.bot.is_ready():
            self._init_log_queue.append((message, level))
            print(f"[LOG_QUEUE|{level.upper()}] Bot not ready. Queued: {message}")
            return

        log_channel = self.bot.get_channel(self.log_channel_id)

        if not isinstance(log_channel, discord.TextChannel):
            print(
                f"[LOG_ERROR|{level.upper()}] Log channel {self.log_channel_id} not found or not a TextChannel. "
                f"Message: {message}")
            return

        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        log_prefix = f"`[{timestamp}] [{level.upper()}]` "

        try:
            full_message = log_prefix + message

            if len(full_message) <= 2000:
                await log_channel.send(content=full_message, embed=embed,
                                       allowed_mentions=discord.AllowedMentions.none())
            else:
                await log_channel.send(content=f"{log_prefix}Log message exceeds 2000 characters. See chunks below.",
                                       embed=embed, allowed_mentions=discord.AllowedMentions.none())

                for i in range(0, len(message), 1900):
                    await log_channel.send(f"```{level.upper()} Chunk {i // 1900 + 1}```\n{message[i:i + 1900]}")
        except discord.Forbidden:
            print(f"[LOG_FORBIDDEN] No permission to send to log channel {self.log_channel_id}.")
        except discord.HTTPException as e:
            print(f"[LOG_HTTP_ERROR] Failed to send to log channel {self.log_channel_id}: {e}")

    def init_log(self, message: str, level: str = "INFO"):
        """
        Synchronous logger for use during cog initialization. Queues logs to be sent
        once the bot is ready. Also prints to console immediately.
        """

        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[INIT_LOG|{level.upper()}|{timestamp}] {message}")

        if self.bot and hasattr(self.bot, 'loop') and self.bot.loop.is_running():
            self.bot.loop.create_task(self.log_to_discord(message, level=level))
        else:
            self._init_log_queue.append((message, level))

    async def flush_init_log_queue(self):
        """Sends any queued logs generated before the bot was ready."""

        if self._init_log_queue:
            self.init_log(f"Flushing {len(self._init_log_queue)} queued startup logs...", "DEBUG")
            for msg, level in self._init_log_queue:
                await self.log_to_discord(msg, level)
            self._init_log_queue.clear()