import asyncio
import logging
import os
import signal
import sqlite3

import discord
from discord.ext import commands
from dotenv import load_dotenv

import utils
from logconf import setup_logging
from schema import create_schema
from utils import block_reply, is_blocked, start_admin_event_writer

setup_logging()

logger = logging.getLogger("bot")

load_dotenv()

# create bot with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(
    command_prefix="%",
    intents=intents,
    help_command=None,
    status=discord.Status.online,
    activity=discord.Activity(type=discord.ActivityType.watching, name="/help • VoidWave"),
    chunk_guilds_at_startup=False,
)
TOKEN = os.getenv("TOKEN")

async def _command_gate(interaction: discord.Interaction) -> bool:
    if await asyncio.to_thread(is_blocked, interaction.user.id, "commands"):
        logger.blocked("'/%s' attempt by %s (%s)", getattr(interaction.command, 'qualified_name', '?'), interaction.user, interaction.user.id)
        try:
            await interaction.response.send_message(block_reply(interaction.user.id, "commands", "using VoidWave commands"), ephemeral=True)
        except (discord.HTTPException, RuntimeError):
            pass
        return False
    return True

bot.tree.interaction_check = _command_gate

async def setup_hook():
    start_admin_event_writer()
    await bot.load_extension("cogs.general")
    await bot.load_extension("cogs.fun")
    await bot.load_extension("cogs.games")
    await bot.load_extension("cogs.multiplayer_games")
    await bot.load_extension("cogs.leveling")
    await bot.load_extension("cogs.ai")
    await bot.load_extension("cogs.config")
    await bot.load_extension("cogs.events")
    await bot.load_extension("cogs.rating")
    await bot.load_extension("cogs.moderation")
    await bot.load_extension("cogs.reminders")
    await bot.load_extension("cogs.giveaways")
    await bot.load_extension("cogs.music")

bot.setup_hook = setup_hook

# Graceful shutdown: SIGTERM/SIGINT (and cogs) set this event; the runner in
# __main__ closes cogs, the aiohttp session and the Discord gateway cleanly
# before exiting so no connections are left dangling at interpreter shutdown.
bot._exit_code = 0
bot._stop_event = asyncio.Event()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    logger.error("Command error in '/%s' used by %s: %r", getattr(interaction.command, 'qualified_name', '?'), interaction.user, error)
    if interaction.response.is_done():
        return

    if isinstance(error, discord.app_commands.CheckFailure):
        try:
            await interaction.response.send_message(block_reply(interaction.user.id, "commands", "using VoidWave commands"), ephemeral=True)
        except discord.HTTPException:
            pass
        return

    logger.critical("Unhandled command error in '/%s'", getattr(interaction.command, 'qualified_name', '?'), exc_info=error)
    try:
        await interaction.response.send_message("Something went wrong while running that command. Please try again later.", ephemeral=True)
    except discord.HTTPException:
        pass

if __name__ == "__main__":
    conn = sqlite3.connect("database.db")
    create_schema(conn)
    conn.close()

    async def _run_bot() -> None:
        loop = asyncio.get_running_loop()
        stop = bot._stop_event

        def _request_stop():
            if not stop.is_set():
                logger.info("Shutdown signal received; closing the Discord gateway gracefully...")
            stop.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_stop)
            except (NotImplementedError, RuntimeError):
                signal.signal(sig, lambda *_: _request_stop())

        bot_task = asyncio.ensure_future(bot.start(TOKEN))
        try:
            await stop.wait()
        finally:
            music_cog = bot.get_cog("MusicCog")
            if music_cog is not None:
                try:
                    await music_cog.shutdown_all()
                except Exception as e:
                    logger.error("Music shutdown during restart failed: %s", e)
            if not bot.is_closed():
                await bot.close()
            if not bot_task.done():
                bot_task.cancel()
                await asyncio.gather(bot_task, return_exceptions=True)
            try:
                if utils.http_session:
                    await utils.http_session.close()
            except Exception:
                pass

    asyncio.run(_run_bot())
    sys_exit_code = getattr(bot, "_exit_code", 0)
    if sys_exit_code:
        raise SystemExit(sys_exit_code)