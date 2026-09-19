from discord.ext import commands
from dotenv import load_dotenv
import discord
import sqlite3
import os
import logging
import asyncio

from utils import is_blocked, block_reply, start_admin_event_writer
from logconf import setup_logging
from schema import create_schema

setup_logging()

logger = logging.getLogger("bot")

load_dotenv()

# create bot with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="%", intents=intents, help_command=None, status=discord.Status.online, activity=discord.Activity(type=discord.ActivityType.watching, name="/help • VoidWave"))
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
        await interaction.response.send_message(f"Something went wrong while running that command. Please try again later.", ephemeral=True)
    except discord.HTTPException:
        pass

if __name__ == "__main__":
    conn = sqlite3.connect("database.db")
    create_schema(conn)
    conn.close()

    # Run the bot
    bot.run(TOKEN) # type: ignore