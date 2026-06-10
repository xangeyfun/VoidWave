from discord import app_commands, Interaction
from discord.ext import commands, tasks
from simpleeval import simple_eval
from llm import ask_llm, llm_stats
from dotenv import load_dotenv
import subprocess
import traceback
import datetime
import requests
import discord
import sqlite3
import asyncio
import random
import psutil
import time
import json
import os

startup = time.time()

load_dotenv()

# create bot with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="%", intents=intents, status=discord.Status.online, activity=discord.Activity(type=discord.ActivityType.watching, name="/help | VoidWave"))
TOKEN = os.getenv("TOKEN")
allowed_user = int(os.getenv("ALLOWED_USER_ID") or 0)
guild = discord.Object(id=int(os.getenv("GUILD_ID"))) # type: ignore
XP_COOLDOWN = 30
VC_COOLDOWN = 300
LLM_COOLDOWN = 15
last_llm = {}
llm_queue = asyncio.Queue(maxsize=10)
llm_queue_size = []
last_xp = {}
last_vc = {}
CATEGORIES = {
    "S1": "Violent Crimes",
    "S2": "Non-Violent Crimes",
    "S3": "Sex Crimes",
    "S4": "Child Exploitation",
    "S5": "Defamation",
    "S6": "Specialized Advice",
    "S7": "Privacy",
    "S8": "Intellectual Property",
    "S9": "Indiscriminate Weapons",
    "S10": "Hate",
    "S11": "Self-Harm",
    "S12": "Sexual Content",
    "S13": "Elections"
}

if os.path.exists("banned_ids.json"):
    with open("banned_ids.json", "r") as f:
        banned_ids = json.load(f)
else:
    with open("banned_ids.json", "w") as f:
        json.dump([], f)
    banned_ids = []

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

async def get_llm_response(msg, display_name, user_id, reply_info = None):
    for attempt in range(5):
        reply, info = await asyncio.to_thread(ask_llm, msg, display_name, user_id, reply_info)

        if reply and reply.strip() and isinstance(reply, str):
            return reply, info + f", Attemps: {attempt + 1}" 

        print(f"{date()} WARN  LLM empty response, retrying ({attempt + 1}/5)")
        await asyncio.sleep(0.5)

    print(f"{date()} ERROR LLM empty response after 5 tries")
    return "Error occurred while fetching LLM response. Please try again.", "Empty response after 5 tries"

async def level_autocomplete(interaction: Interaction, current: str):
    conn = get_db()
    cur = conn.cursor()

    guild_id = interaction.guild.id if interaction.guild else None

    rows = cur.execute("SELECT level FROM level_roles WHERE guild_id = ?", (guild_id,)).fetchall()

    levels = [str(r[0]) for r in rows]

    return [app_commands.Choice(name=level, value=level) for level in levels if current in level][:25]

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

    if len(message.content) < 5:
        cur.execute("UPDATE users SET total_messages = total_messages + 1, last_message=?, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?", (str(datetime.datetime.now()), message.author.display_name, message.author.name, message.author.avatar.key if message.author.avatar else None, guild_id, user_id))
        conn.commit()
        conn.close()
        return
    
    if user_id in last_xp:
        if now - last_xp[user_id] < XP_COOLDOWN:
            cur.execute("UPDATE users SET total_messages = total_messages + 1, last_message=?, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?", (str(datetime.datetime.now()), message.author.display_name, message.author.name, message.author.avatar.key if message.author.avatar else None, guild_id, user_id))
            conn.commit()
            conn.close()
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
    """, (xp, xp, str(datetime.datetime.now()), message.author.avatar.key if message.author.avatar else None, message.author.name, message.author.display_name, guild_id, user_id))
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
            await channel.send(f"🎊 {message.author.mention} reached **Level {level}**! {emoji*count}")

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
                    await message.author.add_roles(role)

                    if channel and isinstance(channel, discord.TextChannel):
                        await channel.send(f"🎖️ Congrats {message.author.mention}! You've earned the **`{role.name}`** role!")

    cur.execute("UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?", (level, progress, out_of, guild_id, user_id))
    conn.commit()

async def send_qotd(channel_id, guild_id):
    channel = bot.get_channel(channel_id)

    if not channel or not isinstance(channel, discord.TextChannel):
        print(f"{date()} ERROR  QOTD channel with ID {channel_id} not found or is not a text channel.")
        return
    
    conn = get_db()
    cur = conn.cursor()

    try:
        guild_settings = cur.execute("SELECT last_qotd_id, last_qotd_thread_id FROM guild_settings WHERE guild_id = ?", (guild_id,)).fetchone()

        if guild_settings and guild_settings["last_qotd_id"] and guild_settings["last_qotd_thread_id"]:
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

    except Exception as e:
        print(f"{date()} ERROR  Failed to clean up old QOTD: {e}")

    with open("questions.json", "r") as f:
        questions = json.load(f)

    question = random.choice(questions)
    
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

    msg = await channel.send(embed=embed)

    thread = await msg.create_thread(name=f"💬 QOTD • {datetime.datetime.now().strftime('%b %d')}", auto_archive_duration=1440) 

    await thread.send(
        f"Hey <@&1491188025898832125>! ✨\n\n"
        f"Today's question:\n"
        f"> **{question}**\n\n"
        f"Reply with your thoughts, stories, or hot takes :3"
    )

    try:
        cur.execute("UPDATE guild_settings SET last_qotd_id=?, last_qotd_thread_id=? WHERE guild_id=?", (msg.id, thread.id, guild_id))
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
            reply = f"Error occurred while fetching LLM response. Please try again later.\n> {e}"

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
        print(f"{date()} INFO  Invite link: https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot%20applications.commands")
    else:
        exit(1) 
    print(f"{date()} DEBUG  Connected to {total_guilds} guilds ({total_members} members)")
    print(f"{date()} DEBUG  Synced {len(synced)} slash commands in {sync_time}")
    print(f"{date()} DEBUG  Startup time: {done - startup:.4f} seconds")
    print(f"{date()} INFO ----------------------\n")
    for guild in bot.guilds:
        print(f"{date()} INFO  {guild.name:<30} | {guild.id:<20} | {str(guild.owner):<20} [{guild.owner_id:<20}] | {guild.member_count:<5} members")
    print(f"{date()} INFO ----------------------\n")
    qotd.start()
    update_stats.start()
    vc_xp_loop.start()
    bot.loop.create_task(llm_worker())

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
async def help_command(interaction: discord.Interaction):
    help_text = (
        "## **Available Commands:**\n"
        "> **<required>**  |  **[optional]**\n\n"
        "> **`/ping`** - Test the bot's latency.\n"
        "> **`/calc <expression>`** - Simple calculator.\n"
        "> **`/flip`** - Flip a coin.\n"
        "> **`/github`** - Find the code on GitHub.\n"
        "> **`/random <int> <int>`** - Generate a random number between a and b.\n"
        "> **`/userinfo <user>`** - Get info about a user.\n"
        "> **`/quote <choice>`** - Get a quote (Today or Random).\n"
        "> **`/animal <animal>`** - Get a random animal picture (dog, cat, duck, fox).\n"
        "> **`/uptime`** - Check the bot's uptime.\n"
        "> **`/fact <choice>`** - Get a daily fact (Today or Random).\n"
        "> **`/level [user]`** - Check your server level.\n"
        "> **`/leaderboard <sort> [global_lb]`** - Check the server level leaderboard.\n"
        "> **`/profile [user]`** - Check your profile.\n\n"
        "Some commands have an option to hide the response from others.\n"
        "Use it if you don't want to spam channels or just want some privacy :wink: \n\n"
    )
    await interaction.response.send_message(help_text, ephemeral=True)


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
    app_commands.Choice(name="Dog", value="dog"),
    app_commands.Choice(name="Cat", value="cat"),
    app_commands.Choice(name="Duck", value="duck"),
    app_commands.Choice(name="Fox", value="fox")
])
async def animal(interaction: discord.Interaction, animal: str, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    if animal == "dog":
        url = "https://random.dog/woof.json"
        r = requests.get(url)
        if r.status_code != 200:
            await interaction.followup.send("> Could not fetch dog picture. Please try again later.", ephemeral=hidden)
            return
        data = r.json()
        embed = discord.Embed(title="🐶 Woof!", color=discord.Color.orange())
        embed.set_image(url=data["url"])
        embed.set_footer(text=f"{datetime.datetime.now()}")
        return await interaction.followup.send(embed=embed, ephemeral=hidden)

    if animal == "cat":
        url = "https://cataas.com/cat?json=True"
        r = requests.get(url)
        if r.status_code != 200:
            await interaction.followup.send("> Could not fetch cat picture. Please try again later.", ephemeral=hidden)
            return
        data = r.json()
        embed = discord.Embed(title="🐱 Meow!", color=discord.Color.orange())
        embed.set_image(url=data["url"])
        embed.set_footer(text=f"{datetime.datetime.now()}")
        return await interaction.followup.send(embed=embed, ephemeral=hidden)

    if animal == "duck":
        url = "https://random-d.uk/api/v2/quack"
        r = requests.get(url)
        if r.status_code != 200:
            await interaction.followup.send("> Could not fetch duck picture. Please try again later.", ephemeral=hidden)
            return
        data = r.json()
        embed = discord.Embed(title="🦆 Quack!", color=discord.Color.orange())
        embed.set_image(url=data["url"])
        embed.set_footer(text=f"{datetime.datetime.now()}")
        return await interaction.followup.send(embed=embed, ephemeral=hidden)
    
    if animal == "fox":
        url = "https://randomfox.ca/floof/"
        r = requests.get(url)
        if r.status_code != 200:
            await interaction.followup.send("> Could not fetch fox picture. Please try again later.", ephemeral=hidden)
            return
        data = r.json()
        embed = discord.Embed(title="🦊 What does the fox say?", color=discord.Color.orange())
        embed.set_image(url=data["image"])
        embed.set_footer(text=f"{datetime.datetime.now()}")
        return await interaction.followup.send(embed=embed, ephemeral=hidden)

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
        await interaction.response.send_message(f"> Error evaluating expression: {e}", ephemeral=hidden)

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
        await interaction.followup.send(f"> Invalid input: {choice}", ephemeral=True)
        return
    try:
        r = requests.get(f"https://zenquotes.io/api/{choice.lower()}")
        print(f"{date()} INFO  Quote API response status: {r.status_code}")
    except Exception as e:
        await interaction.followup.send(f"> Could not fetch quote. Please try again later.\nDetails: {e}", ephemeral=True)
        return
    data = r.json()
    await interaction.followup.send(f"> \"{data[0]['q']}\" - {data[0]['a']}", ephemeral=hidden)

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
@bot.tree.command(name="debug", description="Get bot's debug info (owner only)")
async def debug(interaction: discord.Interaction):
    if interaction.user.id != allowed_user:
        return await interaction.response.send_message("> You do not have permission to use this command.", ephemeral=True)

    queue_size = llm_queue.qsize()
    total_tokens, avg_tps, avg_response_time = llm_stats()

    cpu_usage = psutil.cpu_percent(interval=0.5)
    memory_usage = psutil.virtual_memory().percent
    disk_usage = psutil.disk_usage('/').percent
    system_uptime = int(time.time() - psutil.boot_time())
    h, r = divmod(system_uptime, 3600)
    m, s = divmod(r, 60)
    d, h = divmod(h, 24)

    try:
        git_commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode().strip()
        git_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).decode().strip()
    except Exception:
        git_commit = "unknown"
        git_branch = "unknown"

    embed = discord.Embed(title="🛠️ Bot Debug Info", color=discord.Color.blurple())

    embed.add_field(
        name="⏱️ Server Uptime",
        value=f"{d}d {h}h {m}m {s}s",
        inline=False
    )

    embed.add_field(
        name="🧠 LLM",
        value=(
            f"Queue: {queue_size}\n"
            f"Total Tokens: {total_tokens}\n"
            f"Avg TPS: {avg_tps:.2f}\n"
            f"Avg Response: {avg_response_time:.2f}s"
        ),
        inline=False
    )

    embed.add_field(
        name="💻 System",
        value=(
            f"CPU: {cpu_usage}%\n"
            f"RAM: {memory_usage}%\n"
            f"Disk: {disk_usage}%"
        ),
        inline=False
    )

    embed.add_field(
        name="🌿 Git",
        value=f"{git_branch} @ `{git_commit}`",
        inline=False
    )

    embed.set_footer(text="debug command • owner only")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)   

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
        await interaction.followup.send(f"> Invalid input: {choice}", ephemeral=True)
        return
    try:
        r = requests.get(f"https://uselessfacts.jsph.pl/{'today' if choice.lower() == 'today' else 'random'}.json?language=en")
        print(f"{date()} INFO  Fact API response status: {r.status_code}")
    except Exception as e:
        await interaction.followup.send(f"> Could not fetch fact. Please try again later.\nDetails: {e}", ephemeral=True)
        return
    data = r.json()
    await interaction.followup.send(f"{data['text']}", ephemeral=hidden)

@bot.tree.command(name="shutdown", description="Shut down the bot (owner only).") #, guild=guild)
async def shutdown(interaction: discord.Interaction):
    if interaction.user.id != allowed_user:
        await interaction.response.send_message("> You do not have permission to use this command.", ephemeral=True)
        return
    await interaction.response.send_message("> Shutting down...")
    print(f"{date()} INFO  Shutdown command issued by {interaction.user.name} (ID: {interaction.user.id})")
    await bot.close()

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
                leaderboad = cur.execute("SELECT username, level, guild_id FROM users WHERE guild_id=? ORDER BY level DESC LIMIT 10", (interaction.guild.id,)).fetchall()
            elif sort == "Total XP":
                leaderboad = cur.execute("SELECT username, total_xp, guild_id FROM users WHERE guild_id=? ORDER BY total_xp DESC LIMIT 10", (interaction.guild.id,)).fetchall()
            elif sort == "Total Messages":
                leaderboad = cur.execute("SELECT username, total_messages, guild_id FROM users WHERE guild_id=? ORDER BY total_messages DESC LIMIT 10", (interaction.guild.id,)).fetchall()
            elif sort == "Total Voice":
                leaderboad = cur.execute("SELECT username, vc_minutes, guild_id FROM users WHERE guild_id=? ORDER BY vc_minutes DESC LIMIT 10", (interaction.guild.id,)).fetchall()
        else:
            if sort == "Level":
                leaderboad = cur.execute("SELECT username, level, guild_id FROM users ORDER BY level DESC LIMIT 10").fetchall()
            elif sort == "Total XP":
                leaderboad = cur.execute("SELECT username, total_xp, guild_id FROM users ORDER BY total_xp DESC LIMIT 10").fetchall()
            elif sort == "Total Messages":
                leaderboad = cur.execute("SELECT username, total_messages, guild_id FROM users ORDER BY total_messages DESC LIMIT 10").fetchall()
            elif sort == "Total Voice":
                leaderboad = cur.execute("SELECT username, vc_minutes, guild_id FROM users ORDER BY vc_minutes DESC LIMIT 10").fetchall()

    except Exception as e:
        await interaction.followup.send(f"Something went wrong... Please DM <@996771607630585856> about this\n> {e}", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
        conn.close()
        return
    
    embed = discord.Embed(
        title=f"🏆 {'Global' if global_lb else 'Server'} {sort} Leaderboard",
        color=discord.Color(0x7128fc)
    )

    lines = []

    for i, row in enumerate(leaderboad):
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
            f"> hey {user.mention} :3"
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
@bot.tree.command(name="ai", description="Chat with the bot's LLM (powered by Llama 3.2)") #, guild=guild)
@app_commands.describe(message="The message to send to the LLM", stats="Show additional information about the LLM response", hidden="Hide the command from others")
async def ai(interaction: discord.Interaction, message: str, stats: bool = False, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)

    if interaction.user.id in last_llm and time.time() - last_llm[interaction.user.id] < LLM_COOLDOWN and interaction.user.id != 996771607630585856:
        await interaction.followup.send(f"Please wait before using the LLM again. Cooldown: `{LLM_COOLDOWN - (time.time() - last_llm[interaction.user.id]):.1f} seconds left.`", ephemeral=True)
        return

    if llm_queue.qsize() > 0:
        await interaction.followup.send(f"The LLM is currently busy. Please try again later. Current queue size: `{llm_queue.qsize()}`", ephemeral=True)
        return
    
    reply, info = await get_llm_response(message, interaction.user.name, interaction.user.id) 

    if stats:
        reply += f"\n> {info}"

    await interaction.followup.send(reply, ephemeral=hidden)

# Admin config commands

config = discord.app_commands.Group(name="config", description="Admin commands for configuring the bot", allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=False), allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False))
level = discord.app_commands.Group(name="level", description="Configure level system settings", parent=config) #, guild=guild)
qotd = discord.app_commands.Group(name="qotd", description="Configure quote of the day settings", parent=config) #, guild=guild)
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
    except Exception as e:
        print(f"{date()} ERROR  Failed to fetch config: {e}")
        await interaction.response.send_message(f"Failed to fetch config. Please try again later.\n> {e}", ephemeral=True)
        return
    finally:
        conn.close()

    embed = discord.Embed(title="⚙️ Current Configuration", color=discord.Color(0x7128fc))

    if level_channel:
        channel = interaction.guild.get_channel(level_channel[0])
        channel_name = channel.mention if channel else "`Deleted Channel`"
        embed.add_field(name="Level Up Channel", value=f"{channel_name} ({'Enabled' if level_channel[1] else 'Disabled'})", inline=False)
    else:
        embed.add_field(name="Level Up Channel", value="Not set", inline=False)

    if level_roles:
        roles_str = "\n".join([f"Level {row[0]}: <@&{row[1]}>" for row in level_roles])
        embed.add_field(name="Level Roles", value=roles_str, inline=False)
    else:
        embed.add_field(name="Level Roles", value="No level roles set", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@level.command(name="set_channel", description="Set the channel for level up messages") #, guild=guild)
@app_commands.describe(channel="The channel to send level up messages in", enabled="Whether to enable level up messages")
async def set_level_channel(interaction: discord.Interaction, channel: discord.TextChannel, enabled: bool | None = None):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO guild_settings (guild_id, level_channel_id, level_channel_enabled) VALUES (?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET level_channel_id = excluded.level_channel_id, level_channel_enabled = excluded.level_channel_enabled", (interaction.guild.id, channel.id, int(enabled))) # type: ignore
        conn.commit()
    except Exception as e:
        print(f"{date()} ERROR  Failed to set level channel: {e}")
    finally:
        conn.close()

    await interaction.response.send_message(f"Level up channel set to {channel.mention} and {'enabled' if enabled else 'disabled'}", ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@discord.app_commands.checks.has_permissions(administrator=True)
@level.command(name="add_role", description="Add a role to be given on level up") #, guild=guild)
@app_commands.describe(level="The level to give the role at", role="The role to give")
async def add_level_role(interaction: discord.Interaction, level: int, role: discord.Role):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)", (interaction.guild.id, level, role.id)) # type: ignore
        conn.commit()
    except Exception as e:
        print(f"{date()} ERROR  Failed to add level role: {e}")
    finally:
        conn.close()

    await interaction.response.send_message(f"Role {role.mention} will now be given at level {level}", ephemeral=True)

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

    if "https://cdn.discordapp.com/stickers/1488531621996134430.png" in [sticker.url for sticker in message.stickers] and message.author.id not in banned_ids:
        await message.add_reaction("❓")
        await message.channel.send("<@&1488533311776227469>")
        
    if "https://cdn.discordapp.com/stickers/1488531621996134430.png" in [sticker.url for sticker in message.stickers] and message.author.id in banned_ids:
        await message.delete()
        await message.author.send(f"<@{message.author.id}> You have been banned from using the sticker for repeatedly spamming it. If you think this is a mistake, please DM the admins")
        print(f"{date()} INFO  Deleted message from banned user {message.author} (ID: {message.author.id}) for using the sticker.")

    message_reference = False

    if message.reference and message.reference.message_id:
        ref_msg = await message.channel.fetch_message(message.reference.message_id)
        message_reference = ref_msg.author.id == 1442229230384709752

    if message.content.startswith("<@1442229230384709752>") or message_reference or message.channel.id == 1494361038420709466: 
        if message.author.id in last_llm and time.time() - last_llm[message.author.id] < LLM_COOLDOWN and message.author.id != 996771607630585856:
            await message.reply(f"Please wait before using the LLM again. Cooldown: `{LLM_COOLDOWN - (time.time() - last_llm[message.author.id]):.1f} seconds left.`")
            return

        msg = message.content.replace("<@1442229230384709752>", "").strip()
        msg = msg.replace("--stats", "").strip()

        for mention in message.mentions:
            msg = msg.replace(f"<@{mention.id}>", mention.name)

        for channel in message.channel_mentions:
            msg = msg.replace(f"<#{channel.id}>", channel.name)

        if not msg:
            await message.reply("Please provide a message for the LLM to respond to.")
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
        conn.close()
        await bot.process_commands(message)

@tasks.loop(minutes=1)
async def vc_xp_loop():
    conn = get_db()
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
                    xp = random.randint(5, 20)
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
                            emojis = ['⭐', '🔥', '🌟', '💎', '⚡', '🛡️', '🏹', '🎯', '👑', '🌈']
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

    conn.close()

@tasks.loop(minutes=1)
async def qotd_loop():
    now = datetime.datetime.now()
    if now.hour != 16 or now.minute != 0:
        return

    conn = get_db()
    cur = conn.cursor()

    try:
        guilds = cur.execute("SELECT guild_id, qotd_channel FROM guild_settings WHERE qotd_enabled = 1").fetchall()
    except Exception as e:
        print(f"{date()} ERROR  Failed to fetch QOTD guilds: {e}")
        return

    for guild in guilds:
        await send_qotd(guild["guild_id"], guild["qotd_channel"])

@tasks.loop(minutes=1)
async def update_stats():
    conn = get_db()
    cur = conn.cursor()

    total_guilds = len(bot.guilds)
    total_members = sum(guild.member_count or 0 for guild in bot.guilds)

    cur.execute("UPDATE bot_stats SET total_guilds = ?, total_members = ?", (total_guilds, total_members))

    conn.commit()
    conn.close()

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
        level_channel_enabled BOOLEAN DEFAULT 1,
        qotd_enabled BOOLEAN DEFAULT 0,
        qotd_channel INTEGER,
        last_qotd_id INTEGER,
        last_qotd_thread_id INTEGER,
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

    conn.close()

    # Run the bot
    bot.run(TOKEN) # type: ignore
