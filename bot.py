from discord import app_commands, Interaction
from discord.ext import commands, tasks
from simpleeval import simple_eval
from llm import ask_llm
from dotenv import load_dotenv
import unicodedata
import traceback
import datetime
import aiohttp
import discord
import sqlite3
import asyncio
import random
import time
import json
import os

startup = time.time()

load_dotenv()

# create bot with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="%", intents=intents, status=discord.Status.online, activity=discord.Activity(type=discord.ActivityType.watching, name="/help • VoidWave"))
TOKEN = os.getenv("TOKEN")
owner_id = int(os.getenv("ALLOWED_USER_ID") or 0)
guild = discord.Object(id=int(os.getenv("GUILD_ID"))) # type: ignore
XP_COOLDOWN = 30
VC_COOLDOWN = 600
LLM_COOLDOWN = 15
STATS_LOG_FILE = "stats_history.json"
last_llm = {}
llm_queue = asyncio.Queue(maxsize=10)
llm_queue_size = []
ai_processing = False
last_xp = {}
last_vc = {}
http_session = None

# Helpers

def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def date():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def format_seconds(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)

def format_minutes(minutes):
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")

    return " ".join(parts)

def log_stats():
    conn = get_db()
    cur = conn.cursor()

    total_guilds = len(bot.guilds)
    total_members = sum(g.member_count or 0 for g in bot.guilds)

    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(total_xp), 0) FROM users")
    total_xp = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(total_messages), 0) FROM users")
    total_messages = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(total_messages_xp), 0) FROM users")
    total_messages_xp = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(vc_minutes), 0) FROM users")
    total_vc_minutes = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(vc_xp_minutes), 0) FROM users")
    total_vc_xp_minutes = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(AVG(level), 0) FROM users")
    avg_level = round(cur.fetchone()[0], 2)

    conn.close()

    snapshot = {
        "timestamp": datetime.datetime.now().isoformat(),
        "total_guilds": total_guilds,
        "total_members": total_members,
        "total_users": total_users,
        "total_xp": total_xp,
        "total_messages": total_messages,
        "total_messages_xp": total_messages_xp,
        "total_vc_minutes": total_vc_minutes,
        "total_vc_xp_minutes": total_vc_xp_minutes,
        "avg_level": avg_level,
    }

    history = []
    if os.path.exists(STATS_LOG_FILE):
        try:
            with open(STATS_LOG_FILE, "r") as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            history = []

    history.append(snapshot)

    with open(STATS_LOG_FILE, "w") as f:
        json.dump(history, f, indent=2)

    print(f"{date()} INFO  Stats snapshot logged ({total_guilds} guilds, {total_members} members, {total_xp} XP)")

async def get_llm_response(msg, display_name, user_id, reply_info = None):
    for attempt in range(5):
        reply, info = await asyncio.to_thread(ask_llm, msg, display_name, user_id, reply_info)

        if reply and reply.strip() and isinstance(reply, str):
            return reply, info + f", Attemps: {attempt + 1}" 

        print(f"{date()} WARN  LLM empty response, retrying ({attempt + 1}/5)")
        await asyncio.sleep(0.5)

    print(f"{date()} ERROR LLM empty response after 5 tries")
    return "VoidWave couldn't generate a response. Please try again.", "Empty response after 5 tries"

async def level_autocomplete(interaction: Interaction, current: str):
    conn = get_db()
    try:
        cur = conn.cursor()

        guild_id = interaction.guild.id if interaction.guild else None

        rows = cur.execute("SELECT level FROM level_roles WHERE guild_id = ?", (guild_id,)).fetchall()

        levels = [str(r[0]) for r in rows]

        return [app_commands.Choice(name=level, value=level) for level in levels if current in level][:25]
    finally:
        conn.close()

def get_command_path(interaction):
    data = interaction.data

    parts = [data["name"]]
    options = data.get("options", [])

    while options:
        opt = options[0]

        if opt.get("type") in (1, 2):  
            parts.append(opt["name"])
            options = opt.get("options", [])
        else:
            break

    return "/" + " ".join(parts)

def extract_options(options):
    if not options:
        return {}

    out = {}

    for opt in options:
        if "value" in opt:
            out[opt["name"]] = opt["value"]

        elif "options" in opt:
            out.update(extract_options(opt["options"]))

    return out

async def add_message_xp(message):
    guild_id = message.guild.id
    user_id = message.author.id

    conn = get_db()
    try:
        cur = conn.cursor()

        user = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()

        if not user:
            cur.execute("""
                INSERT INTO users (
                    guild_id, user_id, display_name, username,
                    level, progress, out_of,
                    last_message, total_messages, total_messages_xp, total_xp,
                    vc_minutes, vc_xp_minutes,
                    avatar_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                guild_id, user_id, message.author.display_name, message.author.name,
                0, 0, 100,
                "", 0, 0, 0,
                0, 0,
                message.author.avatar.key if message.author.avatar else None
            ))

            conn.commit()

        now = time.time()
        avatar = message.author.avatar.key if message.author.avatar else None
        metadata_update = (str(datetime.datetime.now()), message.author.display_name, message.author.name, avatar, guild_id, user_id)

        if len(message.content) < 5 or (user_id in last_xp and now - last_xp[user_id] < XP_COOLDOWN):
            cur.execute("UPDATE users SET total_messages = total_messages + 1, last_message=?, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?", metadata_update)
            conn.commit()
            return

        xp = random.randint(1, 15)
        last_xp[user_id] = now

        cur.execute("""
        UPDATE users
        SET progress = progress + ?,
            total_xp = total_xp + ?,
            last_message = ?,
            total_messages_xp = total_messages_xp + 1,
            total_messages = total_messages + 1,
            avatar_hash = ?,
            username = ?,
            display_name = ?
        WHERE guild_id=? AND user_id=?
        """, (xp, xp, str(datetime.datetime.now()), avatar, message.author.name, message.author.display_name, guild_id, user_id))
        conn.commit()
        user = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
        progress = user["progress"]
        out_of = user["out_of"]
        level = user["level"]

        if progress >= out_of:
            progress -= out_of
            level += 1
            out_of = int(100 + level * 20)
            level_channel = (cur.execute("SELECT level_channel_id, level_channel_enabled FROM guild_settings WHERE guild_id = ?", (guild_id,)).fetchone())
            level_channel = dict(level_channel) if level_channel else None

            channel = bot.get_channel(level_channel["level_channel_id"]) if level_channel and level_channel["level_channel_id"] and level_channel["level_channel_enabled"] else None

            if channel and isinstance(channel, discord.TextChannel) and level_channel and level_channel["level_channel_enabled"]:
                emojis = ['⭐', '🔥', '🌟', '💎', '⚡', '🛡️', '🏹', '🎯', '👑', '🌈']
                index = min((level - 1) // 10, len(emojis) - 1)
                emoji = emojis[index]
                count = min((level - 1) % 10 + 1, 10)
                try:
                    await channel.send(f"🎊 {message.author.mention} reached **Level {level}**! {emoji*count}")
                except discord.Forbidden:
                    print(f"{date()} WARN  Missing permissions to send level-up message in {channel.id} for guild {guild_id}")
                except Exception as e:
                    print(f"{date()} ERROR  Failed to send level-up message: {e}")

            level_roles = (cur.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ?", (guild_id,)).fetchall())
            level_roles = dict(level_roles) if level_roles else None
            if not level_roles:
                cur.execute("UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?", (level, progress, out_of, guild_id, user_id))
                conn.commit()
                return
            for req_level, role_id in level_roles.items():
                if level >= req_level:
                    role = message.guild.get_role(role_id)

                    if role and role not in message.author.roles:
                        try:
                            await message.author.add_roles(role)
                        except discord.Forbidden:
                            print(f"{date()} WARN  Missing permissions to assign role {role_id} in guild {guild_id}")
                        except Exception as e:
                            print(f"{date()} ERROR  Failed to assign role: {e}")

                        if channel and isinstance(channel, discord.TextChannel):
                            try:
                                await channel.send(f"🎖️ Congrats {message.author.mention}! You've earned the **`{role.name}`** role!")
                            except discord.Forbidden:
                                print(f"{date()} WARN  Missing permissions to send role message in {channel.id} for guild {guild_id}")
                            except Exception as e:
                                print(f"{date()} ERROR  Failed to send role message: {e}")

        cur.execute("UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?", (level, progress, out_of, guild_id, user_id))
        conn.commit()
    finally:
        conn.close()

async def send_qotd(channel_id, role_id, guild_id):
    channel = bot.get_channel(channel_id)

    if not channel or not isinstance(channel, discord.TextChannel):
        print(f"{date()} ERROR  QOTD channel with ID {channel_id} not found or is not a text channel.")
        return
    
    conn = get_db()
    cur = conn.cursor()

    queue = []

    try:
        guild_settings = cur.execute("SELECT last_qotd_id, last_qotd_thread_id, qotd_queue, delete_old_qotd FROM guild_settings WHERE guild_id = ?", (guild_id,)).fetchone()

        if guild_settings and guild_settings["last_qotd_id"] and guild_settings["last_qotd_thread_id"] and guild_settings["delete_old_qotd"]:
            try:
                thread = channel.get_thread(guild_settings["last_qotd_thread_id"])
                if thread:
                    await thread.delete() # type: ignore
            except Exception as e:
                print(f"{date()} ERROR  Failed to delete old QOTD thread: {e}")

            try:
                old_msg = await channel.fetch_message(guild_settings["last_qotd_id"])
                await old_msg.delete() 

            except Exception as e:
                print(f"{date()} ERROR  Failed to delete old QOTD message: {e}")

        if guild_settings and guild_settings["qotd_queue"]:
            queue = json.loads(guild_settings["qotd_queue"])

    except Exception as e:
        print(f"{date()} ERROR  Failed to clean up old QOTD: {e}")

    with open("questions.json", "r") as f:
        questions = json.load(f)

    if not queue:
        queue = list(range(len(questions)))
        random.shuffle(queue)

    question_index = queue.pop(0)
    question = questions[question_index]
    
    embed = discord.Embed(
        title="🧠 Question of the Day",
        description=(
            f"**{question}**\n\n"
            "> reply in the thread below 👀"
        ),
        color=0x5865F2,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.set_footer(text="New question every day • Powered by VoidWave")

    msg = None
    try:
        msg = await channel.send(embed=embed)
    except discord.Forbidden:
        print(f"{date()} ERROR  Missing permissions to send QOTD in channel {channel_id} for guild {guild_id}")
        conn.close()
        return
    except Exception as e:
        print(f"{date()} ERROR  Failed to send QOTD message: {e}")
        conn.close()
        return

    thread = None
    try:
        thread = await msg.create_thread(name=f"💬 QOTD • {datetime.datetime.now().strftime('%b %d')}", auto_archive_duration=1440)
    except discord.Forbidden:
        print(f"{date()} WARN  Missing permissions to create thread in channel {channel_id} for guild {guild_id}")
    except Exception as e:
        print(f"{date()} ERROR  Failed to create QOTD thread: {e}")

    role = channel.guild.get_role(role_id)
    if role and role.is_default():
        role_text = "@everyone"
    elif role:
        role_text = role.mention
    else:
        role_text = "everyone"

    if thread:
        try:
            await thread.send(
                f"Hey {role_text}! ✨\n\n"
                f"Today's question:\n"
                f"> **{question}**\n\n"
                f"What's your answer? Feel free to share your thoughts, stories, or hot takes!"
            )
        except discord.Forbidden:
            print(f"{date()} WARN  Missing permissions to send QOTD ping in thread for guild {guild_id}")
        except Exception as e:
            print(f"{date()} ERROR  Failed to send QOTD ping: {e}")

    try:
        cur.execute("UPDATE guild_settings SET last_qotd_id=?, last_qotd_thread_id=?, qotd_queue=? WHERE guild_id=?", (msg.id, thread.id, json.dumps(queue), guild_id))
        conn.commit()

    except Exception as e:
        print(f"{date()} ERROR  Failed to save QOTD info to database: {e}")

    finally:
        conn.close()


# Classes

class LLMRequest:
    def __init__(self, prompt, ctx, reply_info = None):
        self.prompt = prompt
        self.reply_info = reply_info
        self.ctx = ctx

# Workers

async def llm_worker():
    while True:
        req = await llm_queue.get()
        prompt = req.prompt
        reply_info = req.reply_info
        ctx = req.ctx

        reply = ""
        info = ""

        try:
            async with ctx.channel.typing():
                reply, info = await get_llm_response(prompt, ctx.author.name, ctx.author.id, reply_info)

                if ctx.content.endswith("--stats"):
                    reply += f"\n> {info}"

        except Exception as e:
            reply = f"VoidWave couldn't generate a response. Please try again later.\n> {e}"

        finally:
            try:
                await ctx.reply(reply)
            except discord.errors.HTTPException:
                pass
            print(f"{date()} INFO  LLM response to {ctx.author} (ID: {ctx.author.id}): {reply} ({info})")
            await asyncio.sleep(1)
            llm_queue_size.pop(0)
            llm_queue.task_done()

# Bot

print(f"{date()} INFO  Starting bot...\n")

@bot.event
async def on_ready():
    global http_session
    http_session = aiohttp.ClientSession()
    print(f"\n{date()} INFO  Logged in as {bot.user}")
    try:
        print(f"{date()} DEBUG  Syncing commands...")
        start_sync = time.time()
        synced = await bot.tree.sync() # guild=guild)
        done = time.time()
    except Exception as e:
        print(f"{date()} ERROR  Error while syncing commands: {e}")
        exit(1)
    total_guilds = len(bot.guilds)
    total_members = sum(guild.member_count or 0 for guild in bot.guilds)
    sync_time = f"{done - start_sync:.2f}s"
    print(f"\n{date()} INFO  --- Bot is ready! ---")
    if bot.user:
        print(f"{date()} INFO  Invite link: https://discord.com/api/oauth2/authorize?client_id={bot.user.id}")
    else:
        exit(1) 
    print(f"{date()} DEBUG  Connected to {total_guilds} guilds ({total_members} members)")
    print(f"{date()} DEBUG  Synced {len(synced)} slash commands in {sync_time}")
    print(f"{date()} DEBUG  Startup time: {done - startup:.4f} seconds")
    print(f"{date()} INFO ----------------------\n")
    for guild in bot.guilds:
        print(f"{date()} INFO  {''.join(c for c in guild.name if unicodedata.category(c) != 'So')[:49].strip():<50} | {guild.id:<20} | {str(guild.owner)[:19]:<20} [{guild.owner_id:<20}] | {guild.member_count:<5} members")
    print(f"{date()} INFO ----------------------\n")
    qotd_loop.start()
    update_stats.start()
    stats_log_loop.start()
    vc_xp_loop.start()
    bot.loop.create_task(llm_worker())
    rotate_status.start()

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.application_command:
        guild_name = interaction.guild.name if interaction.guild else "DM"
        channel_name = getattr(interaction.channel, 'name', 'Unknown') if interaction.channel else ""
        if channel_name != "Unknown":
            channel_name = f"/#{channel_name}"
        else:
            channel_name = ""
        user_name = interaction.user.name if interaction.user else "Unknown"
        command_name = get_command_path(interaction)
        command_options = extract_options(interaction.data.get("options", []))
        user_id = interaction.user.id if interaction.user else "Unknown"
        guild_id = interaction.guild.id if interaction.guild else "DM"
        if guild_id != "DM":
            guild_id = f", guild_id: {guild_id}"
        else:
            guild_id = ""

        options_str = " ".join(f"{k}:{v}" for k, v in command_options.items())

        print(f"{date()} COMMAND '{command_name} {options_str}' used by '{user_name}' in '{guild_name}{channel_name}' (user_id: {user_id}{guild_id})")
        with open("command_logs.txt", "a") as f:
            f.write(f"{date()} COMMAND '{command_name} {options_str}' used by '{user_name}' in '{guild_name}{channel_name}' (user_id: {user_id}{guild_id})\n")


@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="help", description="Get help about the bot.") #, guild=guild)
@app_commands.describe(topic="Get help for a specific category")
@app_commands.choices(topic=[
    app_commands.Choice(name="Leveling", value="leveling"),
    app_commands.Choice(name="Utilities", value="utilities"),
    app_commands.Choice(name="Fun", value="fun"),
    app_commands.Choice(name="Configuration", value="configuration"),
])
async def help_command(interaction: discord.Interaction, topic: str = None):
    if topic == "leveling":
        embed = discord.Embed(title="📊 Leveling Commands", color=discord.Color(0x7128fc))
        embed.add_field(
            name="Commands",
            value=(
                "`/level [user] [hidden]` - Check your server level\n"
                "`/leaderboard <sort> [global_lb]` - Check the server level leaderboard\n"
                "`/profile [user]` - Check your profile"
            ),
            inline=False
        )
    elif topic == "utilities":
        embed = discord.Embed(title="🔧 Utility Commands", color=discord.Color(0x7128fc))
        embed.add_field(
            name="Commands",
            value=(
                "`/ping` - Test the bot's latency\n"
                "`/uptime` - Check the bot's uptime\n"
                "`/calc <expression>` - Simple calculator\n"
                "`/ai <message> [stats] [hidden]` - Chat with the bot's AI\n"
                "`/userinfo <user> [hidden]` - Get info about a user"
            ),
            inline=False
        )
    elif topic == "fun":
        embed = discord.Embed(title="🎉 Fun Commands", color=discord.Color(0x7128fc))
        embed.add_field(
            name="Commands",
            value=(
                "`/flip [hidden]` - Flip a coin\n"
                "`/random <int> <int> [hidden]` - Generate a random number\n"
                "`/quote <choice>` - Get a quote (Today or Random)\n"
                "`/fact <choice>` - Get a daily fact (Today or Random)\n"
                "`/animal <animal> [hidden]` - Get a random animal picture"
            ),
            inline=False
        )
    elif topic == "configuration":
        embed = discord.Embed(title="⚙️ Configuration Commands", color=discord.Color(0x7128fc))
        embed.add_field(
            name="Commands",
            value=(
                "`/config auto [level] [qotd]` - Automatically set up features\n"
                "`/config view` - View current configuration\n"
                "`/config help` - View all configuration commands"
            ),
            inline=False
        )
        embed.set_footer(text="Only available to server admins")
    else:
        embed = discord.Embed(
            title="VoidWave Help",
            description="Select a category below or use `/help topic:<category>` for details.",
            color=discord.Color(0x7128fc)
        )
        embed.add_field(
            name="📊 Leveling",
            value="`/level`, `/leaderboard`, `/profile`",
            inline=True
        )
        embed.add_field(
            name="🔧 Utilities",
            value="`/ping`, `/uptime`, `/calc`, `/ai`, `/userinfo`",
            inline=True
        )
        embed.add_field(
            name="🎉 Fun",
            value="`/flip`, `/random`, `/quote`, `/fact`, `/animal`",
            inline=True
        )
        embed.add_field(
            name="⚙️ Configuration",
            value="`/config auto`, `/config view`, `/config help`",
            inline=True
        )
        embed.set_footer(text="Use /help topic:<category> for details • Some commands have a [hidden] option")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="ping", description="Test the bot's latency.") #, guild=guild)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! {round(bot.latency * 1000)}ms :ping_pong:", ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="animal", description="Get a random animal picture") #, guild=guild)
@app_commands.describe(animal="The type of animal", hidden="Hide the command from others")
@app_commands.choices(animal=[
    app_commands.Choice(name="🐕 Dog", value="dog"),
    app_commands.Choice(name="🐱 Cat", value="cat"),
    app_commands.Choice(name="🦆 Duck", value="duck"),
    app_commands.Choice(name="🦊 Fox", value="fox"),
    app_commands.Choice(name="🐼 Panda", value="panda"),
    app_commands.Choice(name="🐨 Koala", value="koala"),
    app_commands.Choice(name="🦘 Kangaroo", value="kangaroo"),
    app_commands.Choice(name="🦝 Raccoon", value="raccoon"),
    app_commands.Choice(name="🐋 Whale", value="whale"),
])
async def animal(interaction: discord.Interaction, animal: str, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)

    animal_handlers = {
        "dog": ("https://random.dog/woof.json", "url", "🐶 Woof!"),
        "cat": ("https://cataas.com/cat?json=True", "url", "🐱 Meow!"),
        "duck": ("https://random-d.uk/api/v2/quack", "url", "🦆 Quack!"),
        "fox": ("https://randomfox.ca/floof/", "image", "🦊 Floof!"),
        "panda": ("https://some-random-api.com/animal/panda", "image", "🐼 Bamboo crunch!"),
        "koala": ("https://some-random-api.com/animal/koala", "image", "🐨 Eucalyptus nap!"),
        "kangaroo": ("https://some-random-api.com/animal/kangaroo", "image", "🦘 Boing!"),
        "raccoon": ("https://some-random-api.com/animal/racoon", "image", "🦝 Trash panda!"),
        "whale": ("https://some-random-api.com/animal/whale", "image", "🐋 Sploosh!"),
    }

    url, key, title = animal_handlers[animal]
    try:
        async with http_session.get(url) as r:
            if r.status != 200:
                await interaction.followup.send(f"> Could not fetch {animal} picture. Please try again later.", ephemeral=hidden)
                return
            data = await r.json()
    except Exception as e:
        await interaction.followup.send(f"> Could not fetch {animal} picture. Please try again later.\n> {e}", ephemeral=hidden)
        return

    image_url = data[key]
    embed = discord.Embed(title=title, color=discord.Color.orange())
    embed.set_image(url=image_url)
    embed.set_footer(text=f"{datetime.datetime.now()}")
    await interaction.followup.send(embed=embed, ephemeral=hidden)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="calc", description="Simple calculator") #, guild=guild)
@app_commands.describe(expression="an expression like 5*2+3", hidden="Hide the command from others")
async def calc(interaction: Interaction, expression: str, hidden: bool = False):
    allowed = "0123456789+-*/(). "
    if any(c not in allowed for c in expression):
        await interaction.response.send_message("> invalid expression", ephemeral=hidden)
        return
    try:
        result = simple_eval(expression)
        await interaction.response.send_message(f"`{expression}` = {result}", ephemeral=hidden)
    except Exception as e:
        await interaction.response.send_message(f"Error evaluating expression: {e}", ephemeral=hidden)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="flip", description="Flip a coin.") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others")
async def flip(interaction: Interaction, hidden: bool = False):
    await interaction.response.send_message(random.choice(["Heads!", "Tails!"]), ephemeral=hidden)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="github", description="Find the code on github!") #, guild=guild)
async def github(interaction: discord.Interaction):
    await interaction.response.send_message("Bot made by `xangey` (<@996771607630585856>)\n> <https://github.com/xangeyfun/VoidWave>\n> <https://voidwave.xangey.dev/>", ephemeral=True, allowed_mentions=discord.AllowedMentions(users=False))

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="random", description="Random number generator") #, guild=guild)
@app_commands.describe(a="Lowest number", b="Highest number", hidden="Hide the command from others")
async def random_number(interaction: Interaction, a: int, b: int, hidden: bool = False):
    if a >= b:
        await interaction.response.send_message("> First number must be less than the second", ephemeral=True)
        return
    result = random.randint(a, b)
    await interaction.response.send_message(f"Result: {result}", ephemeral=hidden)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="userinfo", description="Get info about a user") #, guild=guild)
@app_commands.describe(user="The user you want info about", hidden="Hide the command from others")
async def userinfo(interaction: discord.Interaction, user: discord.Member | discord.User, hidden: bool = False):
    roles = []
    joined_server = "Unknown"

    if isinstance(user, discord.Member):
        roles = [role.name for role in user.roles if role.name != "@everyone"]
        joined_server = user.joined_at.strftime("%Y-%m-%d") if user.joined_at else "Unknown"

    embed = discord.Embed(
        title=user.name,
        color=discord.Color.blue()
    )

    embed.add_field(name="ID", value=user.id)
    embed.add_field(
        name="Account created",
        value=user.created_at.strftime("%Y-%m-%d") if user.created_at else "Unknown"
    )

    if isinstance(user, discord.Member):
        embed.add_field(name="Joined server", value=joined_server)
        embed.add_field(name="Roles", value=", ".join(roles) or "None")

    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text=f"Requested by {interaction.user.name} • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    await interaction.response.send_message(embed=embed, ephemeral=hidden)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="quote", description="Get a quote") #, guild=guild)
@app_commands.describe(choice='"Today" or "Random"', hidden="Hide the command from others")
@app_commands.choices(choice=[
    app_commands.Choice(name="Today", value="Today"),
    app_commands.Choice(name="Random", value="Random")
])
async def quote(interaction: discord.Interaction, choice: str, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    if choice.lower() != "today" and choice.lower() != "random":
        await interaction.followup.send(f"Invalid input: {choice}", ephemeral=True)
        return
    try:
        async with http_session.get(f"https://zenquotes.io/api/{choice.lower()}") as r:
            print(f"{date()} INFO  Quote API response status: {r.status}")
            data = await r.json()
    except Exception as e:
        await interaction.followup.send(f"Could not fetch quote. Please try again later.\nDetails: {e}", ephemeral=True)
        return
    await interaction.followup.send(f"\"{data[0]['q']}\" - {data[0]['a']}", ephemeral=hidden)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="uptime", description="Check the bot's uptime.") #, guild=guild)
async def uptime(interaction: discord.Interaction):
    current_time = time.time()
    uptime_seconds = int(current_time - startup)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    days, hours = divmod(hours, 24)
    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
    await interaction.response.send_message(f"⏱️ **Bot Uptime**\n> {uptime_str}\n\n🔗 Status Page: <https://status.xangey.dev/>", ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="fact", description="Get a daily fact.") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others", choice='"Today" or "Random"')
@app_commands.choices(choice=[
    app_commands.Choice(name="Today", value="Today"),
    app_commands.Choice(name="Random", value="Random")
])
async def get_fact(interaction: discord.Interaction, choice: str, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    if choice.lower() != "today" and choice.lower() != "random":
        await interaction.followup.send(f"Invalid input: {choice}", ephemeral=True)
        return
    try:
        async with http_session.get(f"https://uselessfacts.jsph.pl/{'today' if choice.lower() == 'today' else 'random'}.json?language=en") as r:
            print(f"{date()} INFO  Fact API response status: {r.status}")
            data = await r.json()
    except Exception as e:
        await interaction.followup.send(f"Could not fetch fact. Please try again later.\nDetails: {e}", ephemeral=True)
        return
    await interaction.followup.send(f"{data['text']}", ephemeral=hidden)

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@bot.tree.command(name="level", description="Check your server level")
@app_commands.describe(hidden="Hide the command from others", user='Select a user to view their level')
async def level(interaction: discord.Interaction, hidden: bool = False, user: discord.Member | None = None):
    if not interaction.guild:
        await interaction.followup.send("This command only works in servers.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=hidden)

    user = user or interaction.user # type: ignore

    try:
        conn = get_db()
        cur = conn.cursor()

        data = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (interaction.guild.id, user.id)).fetchone() # type: ignore

        if not data:
            await interaction.followup.send(f"{user.display_name}'s data file was not found! Try sending a message to create one.", ephemeral=hidden)
            conn.close()
            return

        rank = cur.execute("SELECT COUNT(*) + 1 FROM users WHERE guild_id=? AND total_xp > ?", (interaction.guild.id, data["total_xp"])).fetchone()[0]

        global_rank = cur.execute("SELECT COUNT(*) + 1 FROM users WHERE total_xp > ?", (data["total_xp"],)).fetchone()[0]

    except Exception as e:
        await interaction.followup.send(f"Something went wrong... Please DM <@996771607630585856> about this\n> {e}", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
        conn.close()
        return

    progress = data["progress"]
    out_of = data["out_of"]
    percent = (progress / out_of) * 100 if out_of else 0
    global_rank = f" (`#{global_rank}` Global)"

    filled_blocks = round(percent / 100 * 10)
    bar = f"{'▰'*filled_blocks}{'▱'*(10-filled_blocks)}"

    embed = discord.Embed(
        title=f"{user.display_name}'s Level", # type: ignore
        color=discord.Color(0x7128fc)
    )

    embed.description = (
        f"**Level {data['level']}** • `#{rank}`{global_rank}\n"
        f"`{progress:,} / {out_of:,} XP` • {percent:.1f}%\n"
        f"[{bar}]"
    )

    embed.add_field(
        name="💬 Message Stats",
        value=(
            f"**Messages (XP):** `{data['total_messages_xp']:,}`\n"
            f"**Total Messages:** `{data['total_messages']:,}`"
        ),
        inline=True
    )

    embed.add_field(
        name="🎤 Voice Stats",
        value=(
            f"**Voice (XP):** `{format_minutes(data['vc_xp_minutes'])}`\n"
            f"**Total Voice:** `{format_minutes(data['vc_minutes'])}`"
        ),
        inline=True
    )

    embed.add_field(
        name="🔗 Website",
        value=f"**View online:** [Dashboard](https://voidwave.xangey.dev/stats/{interaction.guild.id}/{user.id})", # type: ignore
        inline=False
    )

    embed.set_thumbnail(url=user.display_avatar.url) # type: ignore

    embed.set_footer(
        text=f"{interaction.guild.name} • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        icon_url=interaction.guild.icon.url if interaction.guild.icon else None
    )

    conn.close()

    await interaction.followup.send(
        embed=embed,
        ephemeral=hidden,
        allowed_mentions=discord.AllowedMentions(users=False)
    )

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@bot.tree.command(name="leaderboard", description="Check the server level leaderboard") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others", sort='What to sort by', global_lb='Show global leaderboard')
@app_commands.choices(
    sort=[
        app_commands.Choice(name="Level", value="Level"),
        app_commands.Choice(name="Total XP", value="Total XP"),
        app_commands.Choice(name="Total Messages", value="Total Messages"),
        app_commands.Choice(name="Total Voice", value="Total Voice")
    ]
)
async def leaderboard(interaction: discord.Interaction, sort: str, global_lb: bool = False, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    if not interaction.guild:
        await interaction.followup.send("This command only works in servers.", ephemeral=True)
        return
    
    conn = get_db()
    cur = conn.cursor()

    try:
        if not global_lb:
            if sort == "Level":
                leaderboard = cur.execute("SELECT username, level, guild_id FROM users WHERE guild_id=? ORDER BY level DESC LIMIT 10", (interaction.guild.id,)).fetchall()
            elif sort == "Total XP":
                leaderboard = cur.execute("SELECT username, total_xp, guild_id FROM users WHERE guild_id=? ORDER BY total_xp DESC LIMIT 10", (interaction.guild.id,)).fetchall()
            elif sort == "Total Messages":
                leaderboard = cur.execute("SELECT username, total_messages, guild_id FROM users WHERE guild_id=? ORDER BY total_messages DESC LIMIT 10", (interaction.guild.id,)).fetchall()
            elif sort == "Total Voice":
                leaderboard = cur.execute("SELECT username, vc_minutes, guild_id FROM users WHERE guild_id=? ORDER BY vc_minutes DESC LIMIT 10", (interaction.guild.id,)).fetchall()
        else:
            if sort == "Level":
                leaderboard = cur.execute("SELECT username, level, guild_id FROM users ORDER BY level DESC LIMIT 10").fetchall()
            elif sort == "Total XP":
                leaderboard = cur.execute("SELECT username, total_xp, guild_id FROM users ORDER BY total_xp DESC LIMIT 10").fetchall()
            elif sort == "Total Messages":
                leaderboard = cur.execute("SELECT username, total_messages, guild_id FROM users ORDER BY total_messages DESC LIMIT 10").fetchall()
            elif sort == "Total Voice":
                leaderboard = cur.execute("SELECT username, vc_minutes, guild_id FROM users ORDER BY vc_minutes DESC LIMIT 10").fetchall()

    except Exception as e:
        await interaction.followup.send(f"Something went wrong... Please DM <@996771607630585856> about this\n> {e}", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
        conn.close()
        return
    
    embed = discord.Embed(
        title=f"🏆 {'Global' if global_lb else 'Server'} {sort} Leaderboard",
        color=discord.Color(0x7128fc)
    )

    lines = []

    for i, row in enumerate(leaderboard):
        username, level = row[0], row[1]

        if i == 0:
            rank = "🥇"
        elif i == 1:
            rank = "🥈"
        elif i == 2:
            rank = "🥉"
        else:
            rank = f"`#{i+1}`"

        line = f"{rank} **{username}** | `{format_minutes(level) if sort == 'Total Voice' else f'{level:,}'}`"
        lines.append(line)

    embed.description = "\n".join(lines) + "\n\n**View online:** [Leaderboard](https://voidwave.xangey.dev/leaderboard)" if lines else "no data yet :("

    embed.set_footer(
        text=f"{interaction.guild.name if interaction.guild and not global_lb else 'Global'} Leaderboard • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon and not global_lb else None
    )

    conn.close()
    await interaction.followup.send(embed=embed, ephemeral=hidden)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="profile", description="Check your profile") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others", user='Select a user to view their profile')
async def profile(interaction: discord.Interaction, hidden: bool = False, user: discord.User | discord.Member | None = None):
    await interaction.response.defer(ephemeral=hidden)
    user = user if user else interaction.user

    try:
        conn = get_db()
        cur = conn.cursor()

        total_xp = cur.execute("SELECT SUM(total_xp) FROM users WHERE user_id=?", (user.id,)).fetchone()[0] or 0
        total_messages = cur.execute("SELECT SUM(total_messages) FROM users WHERE user_id=?", (user.id,)).fetchone()[0] or 0
        total_vc_minutes = cur.execute("SELECT SUM(vc_minutes) FROM users WHERE user_id=?", (user.id,)).fetchone()[0] or 0

    except Exception as e:
        await interaction.followup.send(f"Something went wrong... Please DM <@996771607630585856> about this\n> {e}", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
        return

    finally:
        if conn:
            conn.close()

    embed = discord.Embed(
        title=f"{user.display_name}'s Profile",
        description=(
            f"### 🌌 Global Profile\n"
            f"> hey {user.mention}!"
        ),
        color=discord.Color(0x7128fc)
    )

    embed.add_field(
        name="",
        value=(
            "Hey there! This is your global profile, showing your combined stats across all servers that use the bot. Keep chatting and hanging out in voice channels to level up and earn XP! :D\n"
        ),
        inline=False
    )

    embed.add_field(
        name="⭐ Leveling",
        value=(
            f"**Total XP:** `{total_xp:,}`"
        ),
        inline=True
    )

    embed.add_field(
        name="💬 Messages",
        value=(
            f"**Messages:** `{total_messages:,}`\n"
        ),
        inline=True
    )

    embed.add_field(
        name="🎤 Voice",
        value=(
            f"**Time:** `{format_minutes(total_vc_minutes)}`\n"
        ),
        inline=True
    )

    embed.set_thumbnail(url=user.display_avatar.url)

    embed.set_footer(
        text=f"user id: {user.id}",
        icon_url=user.display_avatar.url
    )

    embed.timestamp = discord.utils.utcnow()

    await interaction.followup.send(embed=embed, ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="ai", description="Chat with the bot's AI (powered by Llama 3.2)") #, guild=guild)
@app_commands.describe(message="The message to send to the AI", stats="Show additional information about the AI response", hidden="Hide the command from others")
async def ai(interaction: discord.Interaction, message: str, stats: bool = False, hidden: bool = False):
    global ai_processing
    await interaction.response.defer(ephemeral=hidden)

    if interaction.user.id in last_llm and time.time() - last_llm[interaction.user.id] < LLM_COOLDOWN and interaction.user.id != 996771607630585856:
        await interaction.followup.send(f"Slow down! VoidWave needs a breather. Try again in `{LLM_COOLDOWN - (time.time() - last_llm[interaction.user.id]):.1f} seconds.`", ephemeral=True)
        return

    if len(llm_queue_size) > 0 or ai_processing:
        await interaction.followup.send(f"VoidWave is busy right now. Try again in a bit! (Queue: `{len(llm_queue_size) + (1 if ai_processing else 0)}`)", ephemeral=True)
        return

    ai_processing = True
    try:
        reply, info = await get_llm_response(message, interaction.user.name, interaction.user.id)

        if stats:
            reply += f"\n> {info}"

        await interaction.followup.send(reply, ephemeral=hidden)
    finally:
        ai_processing = False

# Admin config commands

config = discord.app_commands.Group(name="config", description="Admin commands for configuring the bot", allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=False), allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False))
level = discord.app_commands.Group(name="level", description="Configure level system settings", parent=config) #, guild=guild)
qotd = discord.app_commands.Group(name="qotd", description="Configure QOTD settings", parent=config) #, guild=guild)
bot.tree.add_command(config)

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@config.command(name="view", description="View current configuration") #, guild=guild)
async def view_config(interaction: discord.Interaction):
    try:
        conn = get_db()
        cur = conn.cursor()
        level_channel = cur.execute("SELECT level_channel_id, level_channel_enabled FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
        level_roles = cur.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ?", (interaction.guild.id,)).fetchall() # type: ignore
        qotd_channel = cur.execute("SELECT qotd_channel, qotd_enabled, delete_old_qotd FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
    except Exception as e:
        print(f"{date()} ERROR  Failed to fetch config: {e}")
        await interaction.response.send_message(f"Failed to fetch config. Please try again later.\n> {e}", ephemeral=True)
        return
    finally:
        conn.close()

    embed = discord.Embed(title="⚙️ Current Configuration", color=discord.Color(0x7128fc))

    if level_channel:
        channel = interaction.guild.get_channel(level_channel[0])
        channel_name = channel.mention if channel else "`No Channel Set`"
        embed.add_field(name="Level Up Channel", value=f"{channel_name} ({'Enabled' if level_channel[1] else 'Disabled'})", inline=False)
    else:
        embed.add_field(name="Level Up Channel", value="Not set", inline=False)

    if qotd_channel:
        channel = interaction.guild.get_channel(qotd_channel[0])
        channel_name = channel.mention if channel else "`No Channel Set`"
        embed.add_field(name="QOTD Channel", value=f"{channel_name} ({'Enabled' if qotd_channel[1] else 'Disabled'})", inline=False)
        embed.add_field(name="Delete Old QOTD", value=f"{'Enabled' if qotd_channel[2] else 'Disabled'}", inline=False)
    else:
        embed.add_field(name="QOTD Channel", value="Not set", inline=False)

    if level_roles:
        roles_str = "\n".join([f"Level {row[0]}: <@&{row[1]}>" for row in level_roles])
        embed.add_field(name="Level Roles", value=roles_str, inline=False)
    else:
        embed.add_field(name="Level Roles", value="No level roles set", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@config.command(name="help", description="Get help with configuration commands") #, guild=guild)
@app_commands.describe(topic="Get help for a specific feature")
@app_commands.choices(topic=[
    app_commands.Choice(name="Leveling", value="leveling"),
    app_commands.Choice(name="Question of the Day", value="qotd"),
])
async def config_help(interaction: discord.Interaction, topic: str = None):
    if topic == "leveling":
        embed = discord.Embed(
            title="⚙️ Leveling Configuration",
            description="Set up level-up announcements and auto-roles for your server.",
            color=discord.Color(0x7128fc)
        )
        embed.add_field(
            name="Quick Setup",
            value="`/config auto level:true` - Create channel and enable announcements instantly",
            inline=False
        )
        embed.add_field(
            name="Level Up Channel",
            value=(
                "`/config level set_channel [channel]` - Set the channel for level up messages\n"
                "`/config level toggle_channel [enabled]` - Enable or disable level up messages"
            ),
            inline=False
        )
        embed.add_field(
            name="Level Roles",
            value=(
                "`/config level add_role [level] [role]` - Add a role to be given on level up\n"
                "`/config level remove_role [level]` - Remove a level role"
            ),
            inline=False
        )
    elif topic == "qotd":
        embed = discord.Embed(
            title="⚙️ QOTD Configuration",
            description="Set up a daily question with auto-threads and role pings.",
            color=discord.Color(0x7128fc)
        )
        embed.add_field(
            name="Quick Setup",
            value="`/config auto qotd:true` - Create channel, role, and enable QOTD instantly",
            inline=False
        )
        embed.add_field(
            name="QOTD Settings",
            value=(
                "`/config qotd set_channel [channel]` - Set the channel for QOTD messages\n"
                "`/config qotd set_role [role]` - Set a role to ping with the QOTD\n"
                "`/config qotd enable [enabled]` - Enable or disable QOTD messages\n"
                "`/config qotd delete_old [enabled]` - Enable or disable deletion of old QOTD messages"
            ),
            inline=False
        )
    else:
        embed = discord.Embed(
            title="⚙️ Configuration Help",
            description=(
                "Use these commands to configure your server. "
                "You can also find full setup documentation at https://voidwave.xangey.dev/setup"
            ),
            color=discord.Color(0x7128fc)
        )
        embed.add_field(
            name="Quick Setup",
            value=(
                "`/config auto [level] [qotd]` - Automatically create channels, roles, and enable features\n"
                "Example: `/config auto level:true qotd:true`"
            ),
            inline=False
        )
        embed.add_field(
            name="General",
            value=(
                "`/config view` - View current configuration\n"
                "`/config help topic:Leveling` - View leveling commands\n"
                "`/config help topic:Question of the Day` - View QOTD commands"
            ),
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@config.command(name="auto", description="Automatically set up features for your server")
@app_commands.describe(level="Set up leveling channel and enable announcements", qotd="Set up QOTD channel, role, and enable QOTD")
async def auto_config(interaction: discord.Interaction, level: bool = True, qotd: bool = True):
    if not level and not qotd:
        await interaction.response.send_message("Enable at least one feature! Use `/config auto level:true qotd:true`", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    guild_obj = interaction.guild
    bot_member = guild_obj.me
    created_items = []
    errors = []

    bot_perms = bot_member.guild_permissions
    missing = []
    if not bot_perms.manage_channels:
        missing.append("Manage Channels")
    if not bot_perms.manage_roles:
        missing.append("Manage Roles")
    if missing:
        await interaction.followup.send(f"I need the following permissions to set up features:\n> **{'**, **'.join(missing)}**\n\nPlease add these permissions and try again.", ephemeral=True)
        return

    conn = get_db()
    cur = conn.cursor()
    existing = cur.execute("SELECT level_channel_id, qotd_channel, qotd_role_id FROM guild_settings WHERE guild_id = ?", (guild_obj.id,)).fetchone()
    conn.close()

    existing_level = existing and existing[0]
    existing_qotd_channel = existing and existing[1]
    existing_qotd_role = existing and existing[2]

    if level:
        if existing_level:
            await interaction.followup.send("Leveling is already configured. Use `/config level set_channel` to change it.", ephemeral=True)
        else:
            try:
                overwrites = {
                    guild_obj.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False, create_public_threads=False),
                    bot_member: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True, create_public_threads=True)
                }
                level_channel = await guild_obj.create_text_channel(
                    "level-ups",
                    topic="Level up announcements",
                    overwrites=overwrites,
                    reason="VoidWave auto config"
                )
                created_items.append(f"Channel: {level_channel.mention}")

                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO guild_settings (guild_id, level_channel_id, level_channel_enabled) VALUES (?, ?, 1) ON CONFLICT(guild_id) DO UPDATE SET level_channel_id = excluded.level_channel_id, level_channel_enabled = 1",
                    (guild_obj.id, level_channel.id)
                )
                conn.commit()
                conn.close()
            except Exception as e:
                errors.append(f"Failed to create level-ups channel: {e}")

    if qotd:
        if existing_qotd_channel and existing_qotd_role:
            await interaction.followup.send("QOTD is already configured. Use `/config qotd set_channel` to change it.", ephemeral=True)
        else:
            try:
                overwrites = {
                    guild_obj.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False, create_public_threads=False, send_messages_in_threads=True),
                    bot_member: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True, create_public_threads=True)
                }
                qotd_channel = await guild_obj.create_text_channel(
                    "qotd",
                    topic="Question of the Day",
                    overwrites=overwrites,
                    reason="VoidWave auto config"
                )
                created_items.append(f"Channel: {qotd_channel.mention}")

                qotd_role = await guild_obj.create_role(
                    name="QOTD Ping",
                    mentionable=True,
                    reason="VoidWave auto config"
                )
                created_items.append(f"Role: {qotd_role.mention}")

                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO guild_settings (guild_id, qotd_channel, qotd_role_id, qotd_enabled) VALUES (?, ?, ?, 1) ON CONFLICT(guild_id) DO UPDATE SET qotd_channel = excluded.qotd_channel, qotd_role_id = excluded.qotd_role_id, qotd_enabled = 1",
                    (guild_obj.id, qotd_channel.id, qotd_role.id)
                )
                conn.commit()
                conn.close()
            except Exception as e:
                errors.append(f"Failed to create QOTD setup: {e}")

    if errors:
        error_text = "\n".join(errors)
        if created_items:
            items_text = "\n".join(created_items)
            await interaction.followup.send(
                f"### Partially configured!\n**Created:**\n{items_text}\n\n**Errors:**\n```\n{error_text}\n```\nMake sure VoidWave has **Manage Channels** and **Manage Roles** permissions.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"### Setup failed!\n```\n{error_text}\n```\nMake sure VoidWave has **Manage Channels** and **Manage Roles** permissions.",
                ephemeral=True
            )
    else:
        items_text = "\n".join(created_items)
        await interaction.followup.send(
            f"### All set up!\n**Created:**\n{items_text}\n\nBoth features are now enabled. Customize further with `/config help`.",
            ephemeral=True
        )

# Levelup channel config

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@level.command(name="set_channel", description="Set the channel for level up messages") #, guild=guild)
@app_commands.describe(channel="The channel to send level up messages in")
async def set_level_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    permissions = channel.permissions_for(interaction.guild.me)
    if not permissions.send_messages or not permissions.view_channel:
        await interaction.response.send_message(f"I don't have permission to send messages in {channel.mention}. Please update my permissions for that channel.", ephemeral=True)
        return

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO guild_settings (guild_id, level_channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET level_channel_id = excluded.level_channel_id", (interaction.guild.id, channel.id)) # type: ignore
        conn.commit()
    except Exception as e:
        print(f"{date()} ERROR  Failed to set level channel: {e}")
    finally:
        conn.close()

    await interaction.response.send_message(f"Level up channel set to {channel.mention}\n\n**Don't forget:** Enable level-up messages with `/config level toggle_channel` to start announcing them!", ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@level.command(name="toggle_channel", description="Enable or disable level up messages") #, guild=guild)
@app_commands.describe(enabled="Whether to enable level up messages")
async def toggle_level_channel(interaction: discord.Interaction, enabled: bool):
    conn = get_db()
    try:
        cur = conn.cursor()
        channel = cur.execute("SELECT level_channel_id FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
        channel = bot.get_channel(channel[0]) if channel and channel[0] else None
        if not channel:
            await interaction.response.send_message("Please set a level up channel first using `/config level set_channel`", ephemeral=True)
            return

        cur.execute("INSERT INTO guild_settings (guild_id, level_channel_enabled) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET level_channel_enabled = excluded.level_channel_enabled", (interaction.guild.id, int(enabled))) # type: ignore
        conn.commit()

    except Exception as e:
        print(f"{date()} ERROR  Failed to toggle level channel: {e}")
        await interaction.response.send_message(f"Failed to update level up message setting. Please try again later.\n> {e}", ephemeral=True)
        return
    finally:
        conn.close()

    await interaction.response.send_message(f"Level up messages have been **{'enabled' if enabled else 'disabled'}**", ephemeral=True)

# Levelup roles config

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@level.command(name="add_role", description="Add a role to be given on level up") #, guild=guild)
@app_commands.describe(level="The level to give the role at", role="The role to give")
async def add_level_role(interaction: discord.Interaction, level: int, role: discord.Role):
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(f"I can't assign {role.mention} because it's higher than or equal to my highest role. Please move my role above it in the server settings.", ephemeral=True)
        return

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)", (interaction.guild.id, level, role.id)) # type: ignore
        conn.commit()
    except Exception as e:
        print(f"{date()} ERROR  Failed to add level role: {e}")
    finally:
        conn.close()

    role_text = role.name if role.is_default() else role.mention
    await interaction.response.send_message(f"Role {role_text} will now be given at level {level}", ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@level.command(name="remove_role", description="Remove a level role") #, guild=guild)
@app_commands.describe(level="The level of the role to remove")
@app_commands.autocomplete(level=level_autocomplete)
async def remove_level_role(interaction: discord.Interaction, level: int):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (interaction.guild.id, level)) # type: ignore
        conn.commit()
    except Exception as e:
        print(f"{date()} ERROR  Failed to remove level role: {e}")
    finally:
        conn.close()

    await interaction.response.send_message(f"Level role for level {level} has been removed", ephemeral=True)

# QOTD config

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@qotd.command(name="set_channel", description="Set the channel for QOTD") #, guild=guild)
@app_commands.describe(channel="The channel to send the QOTD in")
async def set_qotd_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    permissions = channel.permissions_for(interaction.guild.me)
    if not permissions.send_messages or not permissions.view_channel:
        await interaction.response.send_message(f"I don't have permission to send messages in {channel.mention}. Please update my permissions for that channel.", ephemeral=True)
        return

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO guild_settings (guild_id, qotd_channel) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET qotd_channel = excluded.qotd_channel", (interaction.guild.id, channel.id)) # type: ignore
        conn.commit()

        role_row = cur.execute("SELECT qotd_role_id FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone()
        has_role = role_row and role_row[0]

    except Exception as e:
        print(f"{date()} ERROR  Failed to set QOTD channel: {e}")
        await interaction.response.send_message(f"Failed to set QOTD channel. Please try again later.\n> {e}", ephemeral=True)
        return
    finally:
        conn.close()

    msg = f"QOTD channel set to {channel.mention}"
    if not has_role:
        msg += "\n\n**Next steps:**\n1. Set a role to ping with `/config qotd set_role`\n2. Enable QOTD with `/config qotd enable`"
    else:
        msg += "\n\n**Don't forget:** Enable QOTD with `/config qotd enable` to start posting daily questions!"
    await interaction.response.send_message(msg, ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@qotd.command(name="enable", description="Enable or disable the QOTD") #, guild=guild)
@app_commands.describe(enabled="Whether to enable the QOTD")
async def enable_qotd(interaction: discord.Interaction, enabled: bool):
    conn = get_db()
    try:
        cur = conn.cursor()
        channel = cur.execute("SELECT qotd_channel FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
        channel = bot.get_channel(channel[0]) if channel and channel[0] else None
        if not channel:
            await interaction.response.send_message("Please set a QOTD channel first using `/config qotd set_channel`", ephemeral=True)
            return
        
        permissions = channel.permissions_for(interaction.guild.me)
        if not permissions.send_messages or not permissions.view_channel:
            await interaction.response.send_message(f"I don't have permission to send messages in {channel.mention}. Please update my permissions for that channel.", ephemeral=True)
            return

        role = cur.execute("SELECT qotd_role_id FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
        role = interaction.guild.get_role(role[0]) if role and role[0] else None
        if not role:
            await interaction.response.send_message("Please set a QOTD role first using `/config qotd set_role`", ephemeral=True)
            return

        cur.execute("INSERT INTO guild_settings (guild_id, qotd_enabled) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET qotd_enabled = excluded.qotd_enabled", (interaction.guild.id, int(enabled))) # type: ignore
        conn.commit()

    except Exception as e:
        print(f"{date()} ERROR  Failed to set QOTD enabled: {e}")
        await interaction.response.send_message(f"Failed to update QOTD setting. Please try again later.\n> {e}", ephemeral=True)
        return
    finally:
        conn.close()

    await interaction.response.send_message(f"QOTD has been {'enabled' if enabled else 'disabled'}", ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@qotd.command(name="set_role", description="Set a role to be pinged with the QOTD") #, guild=guild)
@app_commands.describe(role="The role to ping with the QOTD")
async def set_qotd_role(interaction: discord.Interaction, role: discord.Role):
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(f"I can't use {role.mention} because it's higher than or equal to my highest role. Please move my role above it in the server settings.", ephemeral=True)
        return

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO guild_settings (guild_id, qotd_role_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET qotd_role_id = excluded.qotd_role_id", (interaction.guild.id, role.id)) # type: ignore
        conn.commit()

    except Exception as e:
        print(f"{date()} ERROR  Failed to set QOTD role: {e}")
        await interaction.response.send_message(f"Failed to set QOTD role. Please try again later.\n> {e}", ephemeral=True)
        return
    finally:
        conn.close()

    role_text = role.name if role.is_default() else role.mention
    msg = f"QOTD role set to {role_text}"
    channel_row = None
    try:
        conn2 = get_db()
        cur2 = conn2.cursor()
        channel_row = cur2.execute("SELECT qotd_channel, qotd_enabled FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone()
    except Exception:
        pass
    finally:
        conn2.close()

    if not channel_row or not channel_row[0]:
        msg += "\n\n**Next step:** Set a QOTD channel with `/config qotd set_channel`"
    elif not channel_row[1]:
        msg += "\n\n**Don't forget:** Enable QOTD with `/config qotd enable` to start posting daily questions!"
    await interaction.response.send_message(msg, ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@qotd.command(name="delete_old", description="Enable or disable deletion of old QOTD messages") #, guild=guild)
@app_commands.describe(enabled="Whether to delete old QOTD messages")
async def delete_old_qotd(interaction: discord.Interaction, enabled: bool):
    conn = get_db()
    try:
        cur = conn.cursor()
        channel = cur.execute("SELECT qotd_channel FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
        channel = bot.get_channel(channel[0]) if channel and channel[0] else None
        if not channel:
            await interaction.response.send_message("Please set a QOTD channel first using `/config qotd set_channel`", ephemeral=True)
            return

        cur.execute("INSERT INTO guild_settings (guild_id, delete_old_qotd) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET delete_old_qotd = excluded.delete_old_qotd", (interaction.guild.id, int(enabled))) # type: ignore
        conn.commit()

    except Exception as e:
        print(f"{date()} ERROR  Failed to set delete old QOTD: {e}")
        await interaction.response.send_message(f"Failed to update delete old QOTD setting. Please try again later.\n> {e}", ephemeral=True)
        return
    finally:
        conn.close()

    await interaction.response.send_message(f"Delete old QOTD messages has been {'enabled' if enabled else 'disabled'}", ephemeral=True)

# Message events

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    print(f"{date()} MESSAGE  from {message.author} in {message.guild.name if message.guild else 'DM'}{'/' + message.channel.name if message.guild else ''}: {message.content} [{message.attachments[0].url if message.attachments else ''}] [{message.embeds[0].url if message.embeds else ''}] [{message.stickers[0].url if message.stickers else ''}]")

    if isinstance(message.channel, discord.DMChannel):
        await message.channel.send(
            "## 👋 Hi! I'm **VoidWave**!\n\n"
            "Most of my features are available through slash commands (`/`).\n"
            "Some commands also work in DMs, so try typing `/` to see what's available! 🤖"
        )
        return

    message_reference = False

    if message.reference and message.reference.message_id:
        ref_msg = await message.channel.fetch_message(message.reference.message_id)
        message_reference = ref_msg.author.id == 1442229230384709752

    if message.content.startswith("<@1442229230384709752>") or message_reference or message.channel.id == 1494361038420709466: 
        if message.author.id in last_llm and time.time() - last_llm[message.author.id] < LLM_COOLDOWN and message.author.id != 996771607630585856:
            await message.reply(f"Slow down! VoidWave needs a breather. Try again in `{LLM_COOLDOWN - (time.time() - last_llm[message.author.id]):.1f} seconds.`")
            return

        if len(llm_queue_size) >= 10:
            await message.reply(f"VoidWave is busy right now. Try again in a bit! (Queue: `{len(llm_queue_size) + 1}`)")
            return

        msg = message.content.replace("<@1442229230384709752>", "").strip()
        msg = msg.replace("--stats", "").strip()

        for mention in message.mentions:
            msg = msg.replace(f"<@{mention.id}>", mention.name)

        for channel in message.channel_mentions:
            msg = msg.replace(f"<#{channel.id}>", channel.name)

        if not msg:
            await message.reply("Please provide a message for VoidWave to respond to.")
            return

        reply_info = None
        if message.reference and message.reference.message_id:
            replied_msg = await message.channel.fetch_message(message.reference.message_id)
            reply_info = {
                "author": replied_msg.author.name,
                "content": replied_msg.content
            }

        req = LLMRequest(msg, message, reply_info)

        await llm_queue.put(req)
        llm_queue_size.append(message.author.id)

        last_llm[message.author.id] = time.time()

        position = len(llm_queue_size) - 1
        if position > 0:
            await message.reply(f"You are queued! Position in queue: **{position}**", delete_after=3)

    try:
        await add_message_xp(message)

    except Exception as e:
        e = str(e)
        trace = traceback.format_exc()
        print(f"{date()} ERROR  Failed to process message for leveling: {e}\n```\n{trace}```")
        await message.reply(f"Something went wrong... Please DM <@996771607630585856> about this\n> {e}\n> {trace}", allowed_mentions=discord.AllowedMentions(users=False))
        return

    finally:
        await bot.process_commands(message)

@bot.event
async def on_guild_join(guild):
    print(f"{date()} GUILD  Joined guild: {guild.name} | {guild.member_count} members | ID: {guild.id}")
    log_channel = bot.get_channel(1475562384860119196)
    total_members = sum(g.member_count or 0 for g in bot.guilds)
    total_guilds = len(bot.guilds)
    embed = discord.Embed(
        title=" Joined a new guild!",
        color=discord.Color.green(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="Guild Members", value=f"`{guild.member_count or 0}`", inline=True)
    embed.add_field(name="Total Members", value=f"`{total_members}`", inline=True)
    embed.add_field(name="Total Guilds", value=f"`{total_guilds}`", inline=True)
    await log_channel.send(embed=embed)

    welcome_channel = guild.system_channel
    if not welcome_channel or not welcome_channel.permissions_for(guild.me).send_messages:
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                welcome_channel = ch
                break
    if not welcome_channel:
        return

    welcome_embed = discord.Embed(
        title="Hey! Thanks for adding VoidWave!",
        description=(
            "I'm here to make your server more fun with **levels**, **questions of the day**, and more.\n\n"
            "**Works out of the box (no setup needed):**\n"
            "> **Leveling** - Members earn XP by chatting and hanging out in voice channels.\n"
            "> **Stat cards** - Use `/level` to see your level and XP progress.\n"
            "> **Leaderboard** - Use `/leaderboard` to see who's the most active.\n\n"
            "**Quick setup (easiest):**\n"
            "> **`/config auto`** - Automatically creates channels, roles, and enables leveling + QOTD in one command.\n\n"
            "**Manual setup (all under `/config`):**\n"
            "> **Level-up channel** - `/config level set_channel` - Pick a channel and enable level-up announcements.\n"
            "> **Level-up roles** - `/config level add_role` - Reward members with roles at certain levels.\n"
            "> **Question of the Day** - `/config qotd set_channel` - Post a daily question and ping a role.\n\n"
            "**Need help?** Use `/help` for all commands, `/config help` for configuration, or visit [voidwave.xangey.dev/setup](https://voidwave.xangey.dev/setup) for the full guide."
        ),
        color=0x5865F2,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    welcome_embed.set_thumbnail(url=bot.user.display_avatar.url)
    await welcome_channel.send(embed=welcome_embed)

@bot.event
async def on_guild_remove(guild):
    print(f"{date()} GUILD  Removed from guild: {guild.name} | {guild.member_count} members | ID: {guild.id}")
    channel = bot.get_channel(1475562384860119196)
    total_members = sum(g.member_count or 0 for g in bot.guilds)
    total_guilds = len(bot.guilds)
    embed = discord.Embed(
        title=" Removed from a guild!",
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="Guild Members", value=f"`{guild.member_count or 0}`", inline=True)
    embed.add_field(name="Total Members", value=f"`{total_members}`", inline=True)
    embed.add_field(name="Total Guilds", value=f"`{total_guilds}`", inline=True)
    await channel.send(embed=embed)

@tasks.loop(minutes=1)
async def vc_xp_loop():
    conn = get_db()
    try:
        cur = conn.cursor()
        for guild in bot.guilds:
            for channel in guild.voice_channels:
                members = [m for m in channel.members if not m.bot]


                for member in members:
                    user = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild.id, member.id)).fetchone()
                    if not user:
                        cur.execute("""
                            INSERT INTO users (
                                guild_id, user_id, display_name, username,
                                level, progress, out_of,
                                last_message, total_messages, total_messages_xp, total_xp,
                                vc_minutes, vc_xp_minutes,
                                avatar_hash
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            guild.id, member.id, member.display_name, member.name,
                            0, 0, 100,
                            "", 0, 0, 0,
                            0, 0,
                            member.avatar.key if member.avatar else None
                        ))
                        conn.commit()
                    
                    if len(members) < 2:
                        cur.execute("UPDATE users SET vc_minutes = vc_minutes + 1, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?", (member.display_name, member.name, member.avatar.key if member.avatar else None, guild.id, member.id))
                        conn.commit()
                        continue

                    if member.id in last_vc and time.time() - last_vc[member.id] < VC_COOLDOWN:
                        cur.execute("UPDATE users SET vc_minutes = vc_minutes + 1, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?", (member.display_name, member.name, member.avatar.key if member.avatar else None, guild.id, member.id))
                        conn.commit()
                        continue

                    if member.voice.self_deaf:
                        cur.execute("UPDATE users SET vc_minutes = vc_minutes + 1, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?", (member.display_name, member.name, member.avatar.key if member.avatar else None, guild.id, member.id))
                        conn.commit()
                        continue
                    
                    try:
                        xp = random.randint(1, 8)
                        last_vc[member.id] = time.time()
                        cur.execute("""
                        UPDATE users
                        SET vc_minutes = vc_minutes + 1,
                            vc_xp_minutes = vc_xp_minutes + ?,
                            progress = progress + ?,
                            total_xp = total_xp + ?,
                            avatar_hash = ?,
                            username = ?,
                            display_name = ?
                        WHERE guild_id=? AND user_id=?
                        """, (1, xp, xp, member.avatar.key if member.avatar else None, member.name, member.display_name, guild.id, member.id))
                        conn.commit()
                        user = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild.id, member.id)).fetchone()
                        progress = user["progress"]
                        out_of = user["out_of"]
                        level = user["level"]
                        if progress >= out_of:
                            progress -= out_of
                            level += 1
                            out_of = int(100 + level * 20)
                            
                            level_channel = (cur.execute("SELECT level_channel_id, level_channel_enabled FROM guild_settings WHERE guild_id = ?", (guild.id,)).fetchone())
                            level_channel = dict(level_channel) if level_channel else None

                            channel = bot.get_channel(level_channel["level_channel_id"]) if level_channel and level_channel["level_channel_id"] and level_channel["level_channel_enabled"] else None

                            if channel and isinstance(channel, discord.TextChannel) and level_channel["level_channel_enabled"]:
                                emojis = ['⭐', '🔥', '🌟', '💎', '⚡', '🏆', '🚀', '💫', '🐉', '👸']
                                index = min((level - 1) // 10, len(emojis) - 1)
                                emoji = emojis[index]
                                count = min((level - 1) % 10 + 1, 10)
                                await channel.send(f"🎊 {member.mention} reached **Level {level}**! {emoji*count}")

                            level_roles = (cur.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ?", (guild.id,)).fetchall())
                            level_roles = dict(level_roles) if level_roles else None
                            if not level_roles:
                                cur.execute("UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?", (level, progress, out_of, guild.id, member.id))
                                conn.commit()
                                continue
                            for req_level, role_id in level_roles.items():
                                if level >= req_level:
                                    role = guild.get_role(role_id)

                                    if role and role not in member.roles:
                                        await member.add_roles(role)

                                        if channel and isinstance(channel, discord.TextChannel):
                                            await channel.send(f"🎖️ Congrats {member.mention}! You've earned the **`{role.name}`** role!")
                        conn.commit()
                    except Exception as e:
                        print(f"{date()} ERROR  Failed to update VC XP for {member} in {guild}: {e}")
                        await member.send(f"Something went wrong while updating your voice channel XP. Please DM <@996771607630585856> about this.\n> {e}")
    finally:
        conn.close()

@tasks.loop(minutes=1)
async def qotd_loop():
    now = datetime.datetime.now()
    if now.hour != 16 or now.minute != 0:
        return

    conn = get_db()
    try:
        cur = conn.cursor()

        try:
            guilds = cur.execute("SELECT guild_id, qotd_channel, qotd_role_id FROM guild_settings WHERE qotd_enabled = 1").fetchall()
        except Exception as e:
            print(f"{date()} ERROR  Failed to fetch QOTD guilds: {e}")
            return

        tasks = [send_qotd(g["qotd_channel"], g["qotd_role_id"], g["guild_id"]) for g in guilds]
        await asyncio.gather(*tasks, return_exceptions=True)
        print(f"{date()} INFO  Sent QOTD for {len(guilds)} guilds")
    finally:
        conn.close()

@tasks.loop(minutes=1)
async def update_stats():
    conn = get_db()
    cur = conn.cursor()

    total_guilds = len(bot.guilds)
    total_members = sum(guild.member_count or 0 for guild in bot.guilds)

    cur.execute("UPDATE bot_stats SET total_guilds = ?, total_members = ?", (total_guilds, total_members))

    conn.commit()
    conn.close()

@tasks.loop(minutes=10)
async def stats_log_loop():
    try:
        log_stats()
    except Exception as e:
        print(f"{date()} ERROR  Failed to log stats: {e}")

@tasks.loop(seconds=15)
async def rotate_status():
    guilds = len(bot.guilds)
    members = sum(g.member_count or 0 for g in bot.guilds)

    statuses = [
        f"/help • {guilds} Servers",
        f"/help • {members:,} Members",
        f"/help • voidwave.xangey.dev",
        f"/help • VoidWave",
    ]

    activity = discord.CustomActivity(
        name=statuses[rotate_status.current_loop % len(statuses)]
    )

    await bot.change_presence(activity=activity)

# Error handling

@bot.tree.error
async def on_app_command_error(interaction, error):
    if isinstance(error, discord.app_commands.MissingPermissions):
        return await interaction.response.send_message("> You do not have permission to use this command.", ephemeral=True)

if __name__ == "__main__":
    # Setup DB
    conn = get_db()
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

    conn.close()

    # Run the bot
    bot.run(TOKEN) # type: ignore
