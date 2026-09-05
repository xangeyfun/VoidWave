from discord.ext import commands
from dotenv import load_dotenv
import discord
import sqlite3
import os
import logging

from utils import is_blocked, block_reply
from logconf import setup_logging

setup_logging()

logger = logging.getLogger("bot")

load_dotenv()

# create bot with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="%", intents=intents, status=discord.Status.online, activity=discord.Activity(type=discord.ActivityType.watching, name="/help • VoidWave"))
TOKEN = os.getenv("TOKEN")

async def _command_gate(interaction: discord.Interaction) -> bool:
    if is_blocked(interaction.user.id, "commands"):
        logger.blocked("'/%s' attempt by %s (%s)", getattr(interaction.command, 'qualified_name', '?'), interaction.user, interaction.user.id)
        try:
            await interaction.response.send_message(block_reply(interaction.user.id, "commands", "using VoidWave commands"), ephemeral=True)
        except (discord.HTTPException, RuntimeError):
            pass
        return False
    return True

bot.tree.interaction_check = _command_gate

async def setup_hook():
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

    logger.exception("Unhandled command error in '/%s'", getattr(interaction.command, 'qualified_name', '?'))
    try:
        await interaction.response.send_message(f"Something went wrong while running that command. Please try again later.", ephemeral=True)
    except discord.HTTPException:
        pass

if __name__ == "__main__":
    # Setup DB
    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        guild_id INTEGER,
        user_id INTEGER,
        display_name TEXT,
        username TEXT,
        level INTEGER,
        progress INTEGER,
        out_of INTEGER,
        last_message TEXT,
        total_messages INTEGER,
        total_messages_xp INTEGER,
        total_xp INTEGER,
        vc_minutes INTEGER,
        vc_xp_minutes INTEGER,
        avatar_hash TEXT,
        PRIMARY KEY (guild_id, user_id)
    )
    """)
    conn.commit()

    try:
        cur.execute("ALTER TABLE users ADD COLUMN command_uses INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE users ADD COLUMN rated INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE users ADD COLUMN prompt_sent INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    cur.execute("""
        UPDATE users SET
            level = COALESCE(level, 0),
            progress = COALESCE(progress, 0),
            out_of = COALESCE(out_of, 100),
            last_message = COALESCE(last_message, ''),
            total_messages = COALESCE(total_messages, 0),
            total_messages_xp = COALESCE(total_messages_xp, 0),
            total_xp = COALESCE(total_xp, 0),
            vc_minutes = COALESCE(vc_minutes, 0),
            vc_xp_minutes = COALESCE(vc_xp_minutes, 0)
        WHERE level IS NULL OR progress IS NULL OR out_of IS NULL
           OR last_message IS NULL OR total_messages IS NULL
           OR total_messages_xp IS NULL OR total_xp IS NULL
           OR vc_minutes IS NULL OR vc_xp_minutes IS NULL
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        rating INTEGER,
        feedback TEXT,
        guild_name TEXT,
        created_at INTEGER
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_stats (
        total_guilds INTEGER DEFAULT 0,
        total_members INTEGER DEFAULT 0
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id INTEGER PRIMARY KEY,
        level_channel_id INTEGER,
        level_channel_enabled BOOLEAN DEFAULT 0,
        qotd_enabled BOOLEAN DEFAULT 0,
        qotd_channel INTEGER,
        qotd_role_id INTEGER,
        last_qotd_id INTEGER,
        last_qotd_thread_id INTEGER
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS level_roles (
        guild_id INTEGER,
        level INTEGER,
        role_id INTEGER,
        UNIQUE(guild_id, level)
    )
    """)
    conn.commit()

    try:
        cur.execute("ALTER TABLE guild_settings ADD COLUMN qotd_queue TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE guild_settings ADD COLUMN delete_old_qotd BOOLEAN DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE guild_settings ADD COLUMN qotd_time TEXT DEFAULT '16:00'")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE guild_settings ADD COLUMN qotd_tz TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE guild_settings ADD COLUMN last_qotd_date TEXT")
    except sqlite3.OperationalError:
        pass

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vote_boosts (
        user_id INTEGER PRIMARY KEY,
        multiplier REAL DEFAULT 2.0,
        expires_at INTEGER,
        last_vote_at INTEGER
    )
    """)
    conn.commit()

    try:
        cur.execute("ALTER TABLE vote_boosts ADD COLUMN last_vote_at INTEGER")
    except sqlite3.OperationalError:
        pass
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vote_reminders (
        user_id INTEGER PRIMARY KEY,
        remind_at INTEGER
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pending_dms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kind TEXT,
        payload TEXT,
        created_at INTEGER
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pending_vote_announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        payload TEXT,
        created_at INTEGER
    )
    """)
    conn.commit()

    try:
        cur.execute("ALTER TABLE guild_settings ADD COLUMN vote_announce_enabled BOOLEAN DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE guild_settings ADD COLUMN ai_enabled BOOLEAN DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_prefs (
        user_id INTEGER PRIMARY KEY,
        ai_enabled BOOLEAN DEFAULT 1
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_blocks (
        user_id INTEGER,
        feature TEXT,
        blocked_at INTEGER,
        expires_at INTEGER,
        note TEXT,
        PRIMARY KEY (user_id, feature)
    )
    """)
    conn.commit()

    for column in ("expires_at INTEGER", "note TEXT"):
        try:
            cur.execute(f"ALTER TABLE user_blocks ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass
    conn.commit()

    conn.close()

    # Run the bot
    bot.run(TOKEN) # type: ignore
