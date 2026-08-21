from discord.ext import commands
from dotenv import load_dotenv
import discord
import sqlite3
import os
import traceback
from datetime import datetime

load_dotenv()

# create bot with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="%", intents=intents, status=discord.Status.online, activity=discord.Activity(type=discord.ActivityType.watching, name="/help • VoidWave"))
TOKEN = os.getenv("TOKEN")

async def setup_hook():
    await bot.load_extension("cogs.general")
    await bot.load_extension("cogs.fun")
    await bot.load_extension("cogs.leveling")
    await bot.load_extension("cogs.ai")
    await bot.load_extension("cogs.config")
    await bot.load_extension("cogs.events")
    await bot.load_extension("cogs.moderation")

bot.setup_hook = setup_hook

def date():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    print(f"{date()} ERROR  Command error in '/{getattr(interaction.command, 'qualified_name', '?')}' used by {interaction.user}: {error!r}")
    if interaction.response.is_done():
        return

    traceback.print_exception(type(error), error, error.__traceback__)
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
        expires_at INTEGER
    )
    """)
    conn.commit()

    conn.close()

    # Run the bot
    bot.run(TOKEN) # type: ignore
