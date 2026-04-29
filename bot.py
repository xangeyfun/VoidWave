from discord import app_commands, Interaction
from discord.ext import commands, tasks
from simpleeval import simple_eval
from dotenv import load_dotenv
from llm import ask_llm
import datetime
import requests
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
bot = commands.Bot(command_prefix="%", intents=intents, status=discord.Status.online, activity=discord.Activity(type=discord.ActivityType.watching, name="/help | VoidWave"))
TOKEN = os.getenv("TOKEN")
allowed_user = int(os.getenv("ALLOWED_USER_ID") or 0)
guild = discord.Object(id=int(os.getenv("GUILD_ID"))) # type: ignore
COOLDOWN = 30
LLM_COOLDOWN = 15
last_llm = {}
llm_active = False
last_xp = {}
LEVEL_ROLES = {
    1: 1203672643413221397, # cool guy role
    3: 1217379957412593695, # GIF perms
    5: 1206262995223584859, # photo perms
    10: 1203672754843422761 # very cool guy role
}

with open("banned_ids.json", "r") as f:
    banned_ids = json.load(f)

# Helpers

def date():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def get_user(cur, user_id):
    user = cur.execute("SELECT * FROM economy WHERE user_id = ?", (user_id,)).fetchone()

    if user is None:
        cur.execute("INSERT INTO economy (user_id) VALUES (?)", (user_id,))
        return {"user_id": user_id, "wallet": 0, "bank": 0, "last_daily": 0}

    return user

def get_guild_settings(cur, guild_id):
    row = cur.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)).fetchone()

    if row is None:
        cur.execute("INSERT INTO guild_settings (guild_id, coin_emoji) VALUES (?, ?)", (guild_id, "💰"))
        return {"guild_id": guild_id, "coin_emoji": "💰", "currency_name": "coins"}

    return row

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

async def get_llm_response(msg, display_name, user_id, reply_info = None):
    for attempt in range(5):
        reply, info = await asyncio.to_thread(ask_llm, msg, display_name, user_id, reply_info)

        if reply and reply.strip() and isinstance(reply, str):
            return reply, info + f", Attemps: {attempt + 1}" 

        print(f"{date()} WARN  LLM empty response, retrying ({attempt + 1}/5)")
        await asyncio.sleep(0.5)

    print(f"{date()} ERROR LLM empty response after 5 tries")
    return "Error occurred while fetching LLM response. Please try again.\n> Empty response after 5 tries"


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
        command_name = interaction.command.name if interaction.command else "Unknown"
        user_id = interaction.user.id if interaction.user else "Unknown"
        guild_id = interaction.guild.id if interaction.guild else "DM"
        if guild_id != "DM":
            guild_id = f", guild_id: {guild_id}"
        else:
            guild_id = ""

        options_str = ""
        if interaction.data and "options" in interaction.data:
            options = interaction.data["options"]
            parts = []
            for opt in options:
                parts.append(f"{opt['name']}:{opt.get('value', 'N/A')}")
            options_str = " " + " ".join(parts) if parts else ""

        print(f"{date()} COMMAND '/{command_name}{options_str}' used by '{user_name}' in '{guild_name}{channel_name}' (user_id: {user_id}{guild_id})")
        with open("command_logs.txt", "a") as f:
            f.write(f"{date()} COMMAND '/{command_name}{options_str}' used by '{user_name}' in '{guild_name}{channel_name}' (user_id: {user_id}{guild_id})\n")


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
        "> **`/rps <str>`** - Play Rock Paper Scissors.\n"
        "> **`/random <int> <int>`** - Generate a random number between a and b.\n"
        "> **`/userinfo <str>`** - Get info about a user.\n"
        "> **`/quote <str>`** - Get a quote (Today or Random).\n"
        "> **`/meme [str]`** - Get a random meme.\n"
        "> **`/duck`** - Get a random duck picture.\n"
        "> **`/fox`** - Get a random fox picture.\n"
        "> **`/uptime`** - Check the bot's uptime.\n"
        "> **`/fact <str>`** - Get a daily fact.\n"
        "> **`/dog`** - Get a random dog picture.\n"
        "> **`/level [user]`** - Check your server level.\n"
        "> **`/leaderboard <str> [bool]`** - Check the server level leaderboard.\n\n"
        "Some commands have an option to hide the response from others.\n"
        "Use it if you don't want to spam channels or just want some privacy :wink: \n\n"
    )
    await interaction.response.send_message(help_text, ephemeral=True)


@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="ping", description="Test the bot's latency.") #, guild=guild)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"> Pong! {round(bot.latency * 1000)}ms :ping_pong:", ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="calc", description="Simple calculator") #, guild=guild)
@app_commands.describe(expression="an expression like 5*2+3")
async def calc(interaction: Interaction, expression: str):
    allowed = "0123456789+-*/(). "
    if any(c not in allowed for c in expression):
        await interaction.response.send_message("> invalid expression", ephemeral=True)
        return
    try:
        result = simple_eval(expression)
        await interaction.response.send_message(f"> `{expression}` = {result}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"> Error evaluating expression: {e}", ephemeral=True)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="flip", description="Flip a coin.") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others")
async def flip(interaction: Interaction, hidden: bool = False):
    if hidden:
        await interaction.response.send_message("> " + random.choice(["Heads!", "Tails!"]), ephemeral=True)
    else:
        await interaction.response.send_message("> " + random.choice(["Heads!", "Tails!"]))

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="github", description="Find the code on github!") #, guild=guild)
async def github(interaction: discord.Interaction):
    await interaction.response.send_message("Bot made by `xangey` (<@996771607630585856>)\n> <https://github.com/xangeyfun/discord-bot>\n> <https://voidwave.xangey.dev/>", ephemeral=True, allowed_mentions=discord.AllowedMentions(users=False))

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="rps", description="Rock Paper Scissors") #, guild=guild)
@app_commands.describe(hand="Rock / Paper / Scissors", hidden="Hide the command from others")
@app_commands.choices(hand=[
    app_commands.Choice(name="Rock", value="Rock"),
    app_commands.Choice(name="Paper", value="Paper"),
    app_commands.Choice(name="Scissors", value="Scissors")
])
async def rps(interaction: Interaction, hand: str, hidden: bool = False):
    hand = hand.lower()
    choices = ["rock", "paper", "scissors"]

    if hand not in choices:
        await interaction.response.send_message(f"> Invalid input: {hand}", ephemeral=True)
        return

    bot_choice = random.choice(choices)

    if bot_choice == hand:
        result = "Draw!"
    elif (hand == "rock" and bot_choice == "scissors") or (hand == "paper" and bot_choice == "rock") or (hand == "scissors" and bot_choice == "paper"):
        result = "Human won!"
    else:
        result = "Bot won!"
    if hidden:
        await interaction.response.send_message(f"> :robot: {bot_choice.capitalize()}  -  :bust_in_silhouette: {hand.capitalize()}\n> {result}", ephemeral=True)
    else:
        await interaction.response.send_message(f"> :robot: {bot_choice.capitalize()}  -  :bust_in_silhouette: {hand.capitalize()}\n> {result}")

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="random", description="Random number generator") #, guild=guild)
@app_commands.describe(a="Lowest number", b="Highest number", hidden="Hide the command from others")
async def random_number(interaction: Interaction, a: int, b: int, hidden: bool = False):
    if a >= b:
        await interaction.response.send_message("> First number must be less than the second", ephemeral=True)
        return
    result = random.randint(a, b)
    if hidden:
        await interaction.response.send_message(f"> Result: {result}", ephemeral=True)
    else:
        await interaction.response.send_message(f"> Result: {result}")

@discord.app_commands.allowed_installs(guilds=True, users=False)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@bot.tree.command(name="userinfo", description="Get info about a user") #, guild=guild)
@app_commands.describe(user="The user you want info about", hidden="Hide the command from others")
async def userinfo(interaction: discord.Interaction, user: discord.Member, hidden: bool = False):
    if not interaction.guild:
        await interaction.response.send_message("This command only works in servers.", ephemeral=True)
        return
    roles = [role.name for role in user.roles if role.name != "@everyone"]
    embed = discord.Embed(title=f"{user.name}", color=discord.Color.blue())
    embed.add_field(name="ID", value=user.id)
    embed.add_field(name="Account created", value=user.created_at.strftime("%Y-%m-%d") if user.created_at else "Unknown")
    embed.add_field(name="Joined server", value=user.joined_at.strftime("%Y-%m-%d") if user.joined_at else "Unknown")
    embed.add_field(name="Roles", value=", ".join(roles) or "None")
    embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
    embed.set_footer(text=f"Requested by {interaction.user.name} • {datetime.datetime.now()}")
    if hidden:
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed)

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
    if hidden:
        await interaction.followup.send(f"> \"{data[0]['q']}\" - {data[0]['a']}", ephemeral=True)
    else:
        await interaction.followup.send(f"> \"{data[0]['q']}\" - {data[0]['a']}")

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="meme", description="Get a random meme") #, guild=guild)
@app_commands.describe(subreddit="Subreddit to get meme from (optional)", hidden="Hide the command from others")
async def meme(interaction: discord.Interaction, subreddit: str | None = None, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    url = f"https://meme-api.com/gimme/{subreddit}" if subreddit else "https://meme-api.com/gimme"
    try:
        r = requests.get(url)
        print(f"{date()} INFO  Meme API response status: {r.status_code}")
    except Exception as e:
        embed = discord.Embed(title="Error", description="Could not fetch meme. Please try again later.", color=discord.Color.red())
        embed.add_field(name="Details", value=str(e))
        embed.set_footer(text=f"{datetime.datetime.now()}")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    if r.status_code != 200:
        embed = discord.Embed(title="Error", description="Could not fetch meme. Please try again later.", color=discord.Color.red())
        embed.add_field(name="Details", value=f"Status code: {r.status_code}")
        embed.set_footer(text=f"{datetime.datetime.now()}")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    data = r.json()
    embed = discord.Embed(title=data['title'], url=data['postLink'], color=discord.Color.green())
    embed.set_image(url=data['url'])
    embed.set_footer(text=f"{datetime.datetime.now()} - From r/{data['subreddit']}")
    if hidden:
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(embed=embed)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="duck", description="Get a random duck picture") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others")
async def duck(interaction: discord.Interaction, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    try:
        r = requests.get("https://random-d.uk/api/v2/random")
        print(f"{date()} INFO  Duck API response status: {r.status_code}")
    except Exception as e:
        embed = discord.Embed(title="Error", description="Could not fetch duck image. Please try again later.", color=discord.Color.red())
        embed.add_field(name="Details", value=str(e))
        embed.set_footer(text=f"{datetime.datetime.now()}")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    data = r.json()
    embed = discord.Embed(title="Random Duck", color=discord.Color.blue())
    embed.set_image(url=data['url'])
    if hidden:
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(embed=embed)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="fox", description="Get a random fox picture") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others")
async def fox(interaction: discord.Interaction, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    try:
        r = requests.get("https://randomfox.ca/floof/")
        print(f"{date()} INFO  Fox API response status: {r.status_code}")
    except Exception as e:
        embed = discord.Embed(title="Error", description="Could not fetch fox image. Please try again later.", color=discord.Color.red())
        embed.add_field(name="Details", value=str(e))
        embed.set_footer(text=f"{datetime.datetime.now()}")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    data = r.json()
    embed = discord.Embed(title="Random Fox", color=discord.Color.orange())
    embed.set_image(url=data['image'])
    if hidden:
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(embed=embed)

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="uptime", description="Check the bot's uptime.") #, guild=guild)
async def uptime(interaction: discord.Interaction):
    current_time = time.time()
    uptime_seconds = int(current_time - startup)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
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
        await interaction.followup.send(f"> Invalid input: {choice}", ephemeral=True)
        return
    try:
        r = requests.get(f"https://uselessfacts.jsph.pl/{'today' if choice.lower() == 'today' else 'random'}.json?language=en")
        print(f"{date()} INFO  Fact API response status: {r.status_code}")
    except Exception as e:
        await interaction.followup.send(f"> Could not fetch fact. Please try again later.\nDetails: {e}", ephemeral=True)
        return
    data = r.json()
    if hidden:
        await interaction.followup.send(f"> {data['text']}", ephemeral=True)
    else:
        await interaction.followup.send(f"> {data['text']}")

@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="dog", description="Get a random dog picture") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others")
async def dog(interaction: discord.Interaction, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    try:
        r = requests.get("https://random.dog/woof.json")
        print(f"{date()} INFO  Dog API response status: {r.status_code}")
    except Exception as e:
        embed = discord.Embed(title="Error", description="Could not fetch dog image. Please try again later.", color=discord.Color.red())
        embed.add_field(name="Details", value=str(e))
        embed.set_footer(text=f"{datetime.datetime.now()}")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    data = r.json()
    embed = discord.Embed(title="Random Dog", color=discord.Color.green())
    embed.set_image(url=data['url'])
    if hidden:
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(embed=embed)

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

        data = cur.execute(
            "SELECT * FROM users WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, user.id) # type: ignore
        ).fetchone()

        if not data:
            await interaction.followup.send(
                f"{user.display_name}'s data file was not found! Try sending a message to create one.", # type: ignore
                ephemeral=hidden
            )
            conn.close()
            return

        rank = cur.execute(
            "SELECT COUNT(*) + 1 FROM users WHERE guild_id=? AND total_xp > ?",
            (interaction.guild.id, data["total_xp"])
        ).fetchone()[0]

        global_rank = cur.execute(
            "SELECT COUNT(*) + 1 FROM users WHERE total_xp > ?",
            (data["total_xp"],)
        ).fetchone()[0]

    except Exception as e:
        await interaction.followup.send(
            f"Something went wrong... Please DM <@996771607630585856> about this\n> {e}",
            ephemeral=hidden,
            allowed_mentions=discord.AllowedMentions(users=False)
        )
        conn.close()
        return

    progress = data["progress"]
    out_of = data["out_of"]
    percent = (progress / out_of) * 100 if out_of else 0
    global_rank = f" (`#{global_rank}` Global)"

    filled_blocks = round(percent / 100 * 10)
    bar = f"{'▰'*filled_blocks}{'▱'*(10-filled_blocks)}"

    extra = ""
    if percent >= 90:
        extra = "\n🔥 almost leveling up!"

    embed = discord.Embed(
        title=f"{user.display_name}'s Level", # type: ignore
        color=discord.Color(0x7128fc)
    )

    embed.description = (
        f"**Level {data['level']}** • `#{rank}`{global_rank}{extra}\n"
        f"`{progress:,} / {out_of:,} XP` • {percent:.1f}%\n"
        f"[{bar}]"
    )

    embed.add_field(
        name="",
        value=(
            f"**Total XP:** `{data['total_xp']:,}`\n"
            f"**Messages (XP):** `{data['total_messages_xp']:,}`\n"
            f"**Total Messages:** `{data['total_messages']:,}`\n\n"
            f"**View online:** [Dashboard](https://voidwave.xangey.dev/stats/{interaction.guild.id}/{user.id})" # type: ignore
        ),
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
        app_commands.Choice(name="Total Messages", value="Total Messages")
    ]
)
async def fact(interaction: discord.Interaction, sort: str, global_lb: bool = False, hidden: bool = False):
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
            if sort == "Total XP":
                leaderboad = cur.execute("SELECT username, total_xp, guild_id FROM users WHERE guild_id=? ORDER BY total_xp DESC LIMIT 10", (interaction.guild.id,)).fetchall()
            if sort == "Total Messages":
                leaderboad = cur.execute("SELECT username, total_messages, guild_id FROM users WHERE guild_id=? ORDER BY total_messages DESC LIMIT 10", (interaction.guild.id,)).fetchall()
        else:
            if sort == "Level":
                leaderboad = cur.execute("SELECT username, level, guild_id FROM users ORDER BY level DESC LIMIT 10").fetchall()
            if sort == "Total XP":
                leaderboad = cur.execute("SELECT username, total_xp, guild_id FROM users ORDER BY total_xp DESC LIMIT 10").fetchall()
            if sort == "Total Messages":
                leaderboad = cur.execute("SELECT username, total_messages, guild_id FROM users ORDER BY total_messages DESC LIMIT 10").fetchall()
        

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
        username, level, guild_id = row[0], row[1], row[2]

        if i == 0:
            rank = "🥇"
        elif i == 1:
            rank = "🥈"
        elif i == 2:
            rank = "🥉"
        else:
            rank = f"`#{i+1}`"

        server_name = ""
        if global_lb:
            server = bot.get_guild(guild_id)
            server_name = f" • *{server.name}*" if server else " • *Unknown Server*"

        # build line
        line = f"{rank} **{username}** | `{level}`{server_name}"
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
@bot.tree.command(name="ai", description="Chat with the bot using AI (powered by Llama 3.2)") #, guild=guild)
@app_commands.describe(prompt="What do you want to say to the bot?", stats="Show LLM statistics", hidden="Hide the command from others")
async def ai(interaction: Interaction, prompt: str, stats: bool = False, hidden: bool = False):
    global llm_active, last_llm
    await interaction.response.defer(ephemeral=hidden)

    if llm_active:
        return await interaction.followup.send("LLM is currently busy. Please wait a moment and try again.")

    if interaction.user.id in last_llm and time.time() - last_llm[interaction.user.id] < LLM_COOLDOWN and interaction.user.id != 996771607630585856:
        return await interaction.followup.send(f"Please wait before using the LLM again. Cooldown: `{LLM_COOLDOWN - (time.time() - last_llm[interaction.user.id]):.1f} seconds left.`")

    llm_active = True
    last_llm[interaction.user.id] = time.time()
    response, info = await get_llm_response(prompt, interaction.user.display_name, interaction.user.id) 
    llm_active = False

    if stats:
        response += f"\n> {info}"
    
    await interaction.followup.send(f"{response}", ephemeral=hidden)
    
# Economy

@bot.group(invoke_without_command=True, description="Manage your virtual economy - balance, daily rewards, transfers and more!")
async def eco(ctx):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")

    msg = [
        "**💰 Economy Commands**",
        "`%eco` - show this menu",
        "`%eco balance` - check your money",
        "`%eco daily` - claim daily reward",
        "`%eco deposit <amount>` - put money in bank",
        "`%eco withdraw <amount>` - take money out",
        "`%eco transfer <user> <amount>` - send money",
        "\n**Command Help:**",
        "`%eco help <command>` - view command help page"
    ]

    if ctx.author.guild_permissions.administrator or ctx.author.id == allowed_user:
        msg.append("\n**Server Admin Commands:**")
        msg.append("`%eco settings` - show settings menu")

    if ctx.author.id == allowed_user:
        msg.append("`%eco admin` - show admin menu")

    await ctx.reply("\n".join(msg))

@eco.group(invoke_without_command=True)
async def help(ctx, command: str | None = None):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")

    help_data = {
        "balance": (
            "**`%eco balance [user]`**\n"
            "check your or someone else's balance\n\n"
            "**args:**\n"
            "`[user]` optional user\n\n"
            "**aliases:** `%eco bal`, `%eco b`"
        ),

        "daily": (
            "**`%eco daily`**\n"
            "claim your daily coins reward 🎁"
        ),

        "deposit": (
            "**`%eco deposit <amount>`**\n"
            "move money from wallet → bank\n\n"
            "**args:**\n"
            "`<amount>` number or `all`\n\n"
            "**aliases:** `%eco dep`, `%eco d`"
        ),

        "withdraw": (
            "**`%eco withdraw <amount>`**\n"
            "move money from bank → wallet\n\n"
            "**args:**\n"
            "`<amount>` number or `all`\n\n"
            "**aliases:** `%eco with`, `%eco w`"
        ),

        "transfer": (
            "**`%eco transfer <user> <amount>`**\n"
            "send money to another player\n\n"
            "**args:**\n"
            "`<user>` target user\n"
            "`<amount>` amount to send"
        ),
    }

    if not command:
        return await ctx.reply(
            "**💰 Economy Help**\n"
            "use `%eco help <command>`\n\n"
            "**commands:**\n"
            "`balance`, `daily`, `deposit`, `withdraw`, `transfer`"
        )

    command = command.lower()

    if command not in help_data:
        return await ctx.reply("unknown command")

    await ctx.reply(help_data[command])

@eco.command(aliases=["bal", "b"], description="Check your or another user's wallet and bank balance")
async def balance(ctx, member: discord.Member | None = None):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")

    conn = get_db()
    cur = conn.cursor()

    user = get_user(cur, ctx.author.id if not member else member.id)
    settings = get_guild_settings(cur, ctx.guild.id)

    await ctx.reply(f"{settings['coin_emoji']} {ctx.author.display_name if not member else member.display_name}'s Balance Info\n> **Wallet: {user['wallet']:,}**\n> **Bank: {user['bank']:,}**")

    conn.commit()
    conn.close()

@eco.command(aliases=["dep", "d"], description="Deposit money from your wallet to the bank")
async def deposit(ctx, amount: str):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")
        
    conn = get_db()
    cur = conn.cursor()

    user = get_user(cur, ctx.author.id)
    settings = get_guild_settings(cur, ctx.guild.id)

    if amount.lower() == "all":
        amount = user["wallet"]
    else:
        try:
            amount = int(amount)
        except ValueError:
            return await ctx.reply("invalid amount")

    if amount <= 0:
        return await ctx.reply("invalid amount")

    if amount > user["wallet"]:
        return await ctx.reply("you dont have that much in wallet")

    cur.execute("UPDATE economy SET wallet = wallet - ?, bank = bank + ? WHERE user_id = ?", (amount, amount, ctx.author.id))

    conn.commit()
    conn.close()

    await ctx.reply(f"⬆️ deposited +{amount:,} {settings['coin_emoji']} into your bank")

@eco.command(aliases=["with", "w"], description="Withdraw money from your bank to your wallet")
async def withdraw(ctx, amount: str):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")
        
    conn = get_db()
    cur = conn.cursor()

    user = get_user(cur, ctx.author.id)
    settings = get_guild_settings(cur, ctx.guild.id)

    if user["bank"] <= 0:
        return await ctx.reply("you have nothing in bank")

    if amount.lower() == "all":
        amount = user["bank"]
    else:
        try:
            amount = int(amount)
        except ValueError:
            return await ctx.reply("invalid amount")

    if amount <= 0:
        return await ctx.reply("invalid amount")

    if amount > user["bank"]:
        return await ctx.reply("you dont have that much in bank")

    cur.execute("UPDATE economy SET wallet = wallet + ?, bank = bank - ? WHERE user_id = ?", (amount, amount, ctx.author.id))

    conn.commit()
    conn.close()

    await ctx.reply(f"⬇️ withdrew -{amount:,} {settings['coin_emoji']} from your bank")

@eco.command(description="Transfer money from your wallet to another user")
async def transfer(ctx, member: discord.Member, amount: int):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")
        
    if member.bot:
        return await ctx.reply("no bots :sob:")

    conn = get_db()
    cur = conn.cursor()

    user = get_user(cur, ctx.author.id)
    settings = get_guild_settings(cur, ctx.guild.id)

    if amount <= 0 or amount > user["wallet"]:
        return await ctx.reply("invalid amount")

    if user["wallet"] < amount:
        return await ctx.reply("not enough money in wallet")

    cur.execute("UPDATE economy SET wallet = wallet - ? WHERE user_id = ?", (amount, ctx.author.id))

    cur.execute("UPDATE economy SET wallet = wallet + ? WHERE user_id = ?", (amount, member.id))

    conn.commit()
    conn.close()

    await ctx.reply(f"🔁 sent -{amount:,} {settings['coin_emoji']} to {member.mention}")

# Economy settings

@eco.group(invoke_without_command=True, description="Manage server economy settings (admin only)")
async def settings(ctx):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")
        
    if not ctx.author.guild_permissions.administrator and ctx.author.id != allowed_user:
        return await ctx.reply("no permission :3")
    await ctx.reply(
        "⚙️ Server Settings:\n"
        "`%eco settings emoji <emoji>`"
    )

@settings.command(description="Set the coin emoji for the server")
async def emoji(ctx, emoji: str):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")
        
    if not ctx.author.guild_permissions.administrator and ctx.author.id != allowed_user:
        return await ctx.reply("no permission :3")

    if not emoji:
        return await ctx.reply("invalid emoji")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("INSERT INTO guild_settings (guild_id, coin_emoji) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET coin_emoji = excluded.coin_emoji", (ctx.guild.id, emoji))

    conn.commit()
    conn.close()

    await ctx.reply(f"coin emoji set to {emoji}")

# Economy Money Makers

@eco.command(description="Claim your daily reward of 500-1000 coins")
async def daily(ctx):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")

    conn = get_db()
    cur = conn.cursor()

    user = get_user(cur, ctx.author.id)
    settings = get_guild_settings(cur, ctx.guild.id)

    now = int(time.time())
    cooldown = 86400

    if now - user["last_daily"] < cooldown:
        remaining = cooldown - (now - user["last_daily"])
        return await ctx.reply(f"come back in {format_seconds(remaining)} :3")

    reward = random.randint(500, 1000)

    cur.execute("UPDATE economy SET wallet = wallet + ?, last_daily = ? WHERE user_id = ?", (reward, now, ctx.author.id))

    conn.commit()
    conn.close()

    await ctx.reply(f"🎁 you got +{reward:,} {settings['coin_emoji']} :D")

# Economy admin

@eco.group(invoke_without_command=True, description="Admin commands for managing the economy (bot owner only)")
async def admin(ctx):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")
        
    if ctx.author.id != allowed_user:
        return await ctx.reply("no permission :3")

    await ctx.reply(
        f"**{bot.get_emoji(1488541008261288088)} Admin Commands**\n"
        "`%eco admin addmoney <user> <amount>`\n"
        "`%eco admin removemoney <user> <amount>`\n"
        "`%eco admin setmoney <user> <amount>`\n"
        "`%eco admin reseteco <user>`"
    )

@admin.command(description="Add money to a user's wallet")
async def addmoney(ctx, member: discord.Member, amount: int):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")
        
    if ctx.author.id != allowed_user:
        return await ctx.reply("no permission :3")

    if amount <= 0:
        return await ctx.reply("invalid amount")

    conn = get_db()
    cur = conn.cursor()
    settings = get_guild_settings(cur, ctx.guild.id)

    cur.execute("INSERT INTO economy (user_id, wallet, bank, last_daily) VALUES (?, 0, 0, 0) ON CONFLICT(user_id) DO NOTHING", (member.id,))

    cur.execute("UPDATE economy SET wallet = wallet + ? WHERE user_id = ?", (amount, member.id))

    conn.commit()
    conn.close()

    await ctx.reply(f"➕ added +{amount:,} {settings['coin_emoji']} to {member.display_name}")

@admin.command(description="Remove money from a user's wallet")
async def removemoney(ctx, member: discord.Member, amount: int):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")
        
    if ctx.author.id != allowed_user:
        return await ctx.reply("no permission :3")

    conn = get_db()
    cur = conn.cursor()
    settings = get_guild_settings(cur, ctx.guild.id)

    cur.execute("INSERT INTO economy (user_id, wallet, bank, last_daily) VALUES (?, 0, 0, 0) ON CONFLICT(user_id) DO NOTHING", (member.id,))

    cur.execute("UPDATE economy SET wallet = MAX(wallet - ?, 0) WHERE user_id = ?", (amount, member.id)
    )

    conn.commit()
    conn.close()

    await ctx.reply(f"➖ removed -{amount:,} {settings['coin_emoji']} from {member.display_name}")

@admin.command(description="Set a user's wallet to a specific amount")
async def setmoney(ctx, member: discord.Member, amount: int):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")
        
    if ctx.author.id != allowed_user:
        return await ctx.reply("no permission :3")

    conn = get_db()
    cur = conn.cursor()
    settings = get_guild_settings(cur, ctx.guild.id)

    cur.execute("INSERT INTO economy (user_id, wallet, bank, last_daily) VALUES (?, 0, 0, 0) ON CONFLICT(user_id) DO NOTHING", (member.id,))

    cur.execute("UPDATE economy SET wallet = ? WHERE user_id = ?", (amount, member.id))

    conn.commit()
    conn.close()

    await ctx.reply(f"🛠️ set {member.display_name}'s wallet to {amount:,} {settings['coin_emoji']}")

@admin.command(description="Reset all economy data for a specific user")
async def reseteco(ctx, member: discord.Member):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")
        
    if ctx.author.id != allowed_user:
        return await ctx.reply("no permission :3")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM economy WHERE user_id = ?", (member.id,))

    conn.commit()
    conn.close()

    await ctx.reply(f"🧨 reset economy for {member.display_name}")

@admin.command(description="Reset all economy data")
async def resetall(ctx, confirm: str | None = None):
    if not ctx.guild:
        return await ctx.reply("this only works in servers")
    
    if ctx.author.id != allowed_user:
        return await ctx.reply("no permission :3")
    
    if confirm != "YES" or not confirm:
        return await ctx.reply("please type `%eco admin resetall YES` to confirm")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM economy")

    conn.commit()
    conn.close()

    await ctx.reply("🧨 reset all economy data")

# Message events

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    print(f"{date()} MESSAGE  from {message.author} in {message.guild.name if message.guild else 'DM'}{'/' + message.channel.name if message.guild else ''}: {message.content} [{message.attachments[0].url if message.attachments else ''}] [{message.embeds[0].url if message.embeds else ''}] [{message.stickers[0].url if message.stickers else ''}]")

    # duck reaction
    if message.content.lower() in ["duck", "quack"]:
        await message.add_reaction("🦆")
        await message.channel.send("Quack! 🦆")

    if message.content.lower() in ["cat", "meow"]:
        await message.add_reaction("😼")
        await message.channel.send("Meow! 😼")

    if message.content.lower() in ["dog", "woof"]:
        await message.add_reaction("🐶")
        await message.channel.send("Woof! 🐶")

    if message.content.lower() == "defenestration":
        await message.add_reaction("⁉")
        await message.channel.send("Secret Word!!")

    if any(word in message.content.lower() for word in [":3"]) and message.guild.id not in [1448685763960115202, 1203657476306894868]:
        await message.add_reaction(bot.get_emoji(1488541008261288088) or "😺")

    # DM message
    if isinstance(message.channel, discord.DMChannel):
        await message.channel.send("Hello! I'm a bot. 🤖\n> Please use slash commands (/) to interact with me!")
        await bot.process_commands(message)
        return

    if "https://cdn.discordapp.com/stickers/1488531621996134430.png" in [sticker.url for sticker in message.stickers] and message.author.id not in banned_ids:
        await message.add_reaction("❓")
        await message.channel.send("<@&1488533311776227469>")
        
    if "https://cdn.discordapp.com/stickers/1488531621996134430.png" in [sticker.url for sticker in message.stickers] and message.author.id in banned_ids:
        await message.delete()
        await message.author.send(f"<@{message.author.id}> You have been banned from using the sticker for repeatedly spamming it. If you think this is a mistake, please DM the admins")
        print(f"{date()} INFO  Deleted message from banned user {message.author} (ID: {message.author.id}) for using the sticker.")

    global llm_active
    global llm_history

    message_reference = False

    if message.reference and message.reference.message_id:
        ref_msg = await message.channel.fetch_message(message.reference.message_id)
        message_reference = ref_msg.author.id == 1442229230384709752

    if message.content.startswith("<@1442229230384709752>") or message_reference or message.channel.id == 1494361038420709466: 
        if llm_active:
            await message.reply("LLM is currently busy. Please wait a moment and try again.")
            await bot.process_commands(message)
            return
        llm_active = True
        if message.author.id in last_llm and time.time() - last_llm[message.author.id] < LLM_COOLDOWN and message.author.id != 996771607630585856:
            await message.reply(f"Please wait before using the LLM again. Cooldown: `{LLM_COOLDOWN - (time.time() - last_llm[message.author.id]):.1f} seconds left.`")
            llm_active = False
            await bot.process_commands(message)
            return
        last_llm[message.author.id] = time.time()
        msg = message.content.replace("<@1442229230384709752>", "").strip()
        msg = msg.replace("--stats", "").strip()
        if not msg:
            await message.reply("Please provide a message for the LLM to respond to.")
            llm_active = False
            await bot.process_commands(message)
            return
        try:
            async with message.channel.typing():
                reply_info = None
                if message.reference and message.reference.message_id:
                    replied_msg = await message.channel.fetch_message(message.reference.message_id)
                    reply_info = {
                        "author": replied_msg.author.display_name,
                        "content": replied_msg.content
                    }
                reply, info = await get_llm_response(msg, message.author.display_name, message.author.id, reply_info)
        except Exception as e:
            reply = f"Error occurred while fetching LLM response. Please try again later.\n> {e}"
            info = e
        if reply.strip() == "":
            reply = "Error occurred while fetching LLM response. Please try again.\n> Empty response"
        llm_active = False
        if message.content.endswith("--stats"):
            reply += f"\n> {info}"
        await message.reply(reply)
        print(f"{date()} INFO  LLM response to {message.author} (ID: {message.author.id}): {reply} ({info})")

    guild_id = message.guild.id
    user_id = message.author.id

    conn = get_db()
    cur = conn.cursor()

    try:
        user = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()

        if not user:
            cur.execute("""
                INSERT INTO users (
                    guild_id, user_id, display_name, username,
                    level, progress, out_of,
                    last_message, total_messages, total_messages_xp, total_xp,
                    avatar_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                guild_id, user_id, message.author.display_name, message.author.name,
                0, 0, 100,
                "", 0, 0, 0,
                message.author.avatar.key if message.author.avatar else None
            ))

            conn.commit()

        now = time.time()

        if len(message.content) < 5:
            cur.execute("UPDATE users SET total_messages = total_messages + 1, last_message=?, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?", (str(datetime.datetime.now()), message.author.display_name, message.author.name, message.author.avatar.key if message.author.avatar else None, guild_id, user_id))
            conn.commit()
            conn.close()
            await bot.process_commands(message)
            return
        
        if user_id in last_xp:
            if now - last_xp[user_id] < COOLDOWN:
                cur.execute("UPDATE users SET total_messages = total_messages + 1, last_message=?, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?", (str(datetime.datetime.now()), message.author.display_name, message.author.name, message.author.avatar.key if message.author.avatar else None, guild_id, user_id))
                conn.commit()
                conn.close()
                await bot.process_commands(message)
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

            if message.guild.id not in [1203657476306894868, 1487803811178352832]:
                cur.execute("UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?", (level, progress, out_of, guild_id, user_id))
                conn.commit()
                conn.close()
                return

            level_channel = bot.get_channel(1450192627478564916 if message.guild.id == 1203657476306894868 else 1487803937254801408)

            if level_channel and isinstance(level_channel, discord.TextChannel):
                emojis = ['⭐', '🔥', '🌟', '💎', '⚡', '🛡️', '🏹', '🎯', '👑', '🌈']
                index = min((level - 1) // 10, len(emojis) - 1)
                emoji = emojis[index]
                count = min((level - 1) % 10 + 1, 10)
                await level_channel.send(f"🎊 {message.author.mention} reached **Level {level}**! {emoji*count}")

            if level in LEVEL_ROLES:
                role_id = LEVEL_ROLES[level]
                role = message.guild.get_role(role_id)

                if role:
                    await message.author.add_roles(role)

                    if level_channel and isinstance(level_channel, discord.TextChannel):
                        await level_channel.send(f"🎖️ Congrats {message.author.mention}! You've earned the **`{role.name}`** role!")

        cur.execute("UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?", (level, progress, out_of, guild_id, user_id))
        conn.commit()
    
    except Exception as e:
        await message.reply(f"Something went wrong... Please DM <@996771607630585856> about this\n> {e}", allowed_mentions=discord.AllowedMentions(users=False))
        conn.close()
        await bot.process_commands(message)
        return

    conn.close()
    await bot.process_commands(message)

@tasks.loop(minutes=1)
async def qotd():
    now = datetime.datetime.now()
    if now.hour != 16 or now.minute != 0:
        print(f"{date()} INFO  Not time for QOTD yet. Current time: {now.hour}:{now.minute:02d}/16:00 - sleeping...")
        return

    # make sure the file exists
    if not os.path.exists("qotd.json"):
        with open("qotd.json", "w") as f:
            json.dump({}, f)

    # load last QOTD IDs
    with open("qotd.json", "r") as f:
        data = json.load(f)
        last_qotd_id = data.get("last_qotd")
        last_qotd_thread_id = data.get("last_qotd_thread")

    channel = bot.get_channel(1488186829562970334)
    if not channel:
        print(f"{date()} ERROR  QOTD channel not found!")
        return

    print(f"{date()} INFO  Fetching QOTD...")
    r = requests.get("https://zenquotes.io/api/random").json()

    quote = r[0]['q']
    author = r[0]['a']

    # cleanup old QOTD
    if last_qotd_thread_id:
        try:
            thread = await bot.fetch_channel(last_qotd_thread_id)
            await thread.delete() # type: ignore
        except Exception as e:
            print(f"{date()} ERROR  Failed to delete old QOTD thread: {e}")

    if last_qotd_id:
        try:
            old_msg = await channel.fetch_message(last_qotd_id) # type: ignore
            await old_msg.delete()
        except Exception as e:
            print(f"{date()} ERROR  Failed to delete old QOTD message: {e}")

    # create embed
    embed = discord.Embed(
        title="🧠 Question of the Day",
        description=(
            f"**{quote}**\n\n"
            "*Do you agree with this? Why or why not?*"
        ),
        color=0x5865F2,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="✍️ Quote Author", value=f"`{author}`", inline=True)
    embed.set_footer(text="New question every day • Powered by ZenQuotes")

    # send message & ping role
    msg = await channel.send(embed=embed) # type: ignore

    # create thread
    thread = await msg.create_thread(
        name=f"💬 QOTD • {datetime.datetime.now().strftime('%b %d')}",
        auto_archive_duration=1440
    )
    await thread.send(f"""
# 💬 QOTD Discussion

Hey <@&1491188025898832125>! :3

What do you think about today’s question?  
There’s no right or wrong answer, just share your thoughts, opinions, or experiences 👀

Feel free to:
* agree or disagree  
* explain your reasoning  
* respond to others and start a discussion  

🕒 **Posted:** <t:{int(datetime.datetime.now().timestamp())}:F> (<t:{int(datetime.datetime.now().timestamp())}:R>)

Have fun and keep it respectful! ✨
    """)

    # save last QOTD IDs
    with open("qotd.json", "w") as f:
        json.dump({
            "last_qotd": msg.id,
            "last_qotd_thread": thread.id
        }, f)

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
        avatar_hash TEXT,
        PRIMARY KEY (guild_id, user_id)
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS economy (
        user_id INTEGER PRIMARY KEY,
        wallet INTEGER DEFAULT 0,
        bank INTEGER DEFAULT 0,
        last_daily INTEGER DEFAULT 0
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id INTEGER PRIMARY KEY,
        coin_emoji TEXT DEFAULT "💰",
        currency_name TEXT DEFAULT "coins"
    )
    """)
    conn.commit()

    conn.close()

    # Run the bot
    bot.run(TOKEN) # type: ignore
