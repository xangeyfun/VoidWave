from discord import app_commands, Interaction
from discord.ext import commands
from dotenv import load_dotenv
from simpleeval import simple_eval
import datetime
import requests
import discord
import sqlite3
import random
import time
import os

startup = time.time()

load_dotenv()

# create bot with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, status=discord.Status.online, activity=discord.Activity(type=discord.ActivityType.watching, name="/help | VoidWave"))
TOKEN = os.getenv("TOKEN")
allowed_user = os.getenv("ALLOWED_USER_ID")
guild = discord.Object(id=int(os.getenv("GUILD_ID")))
COOLDOWN = 30
last_xp = {}
LEVEL_ROLES = {
    1: 1203672643413221397, # cool guy role
    3: 1217379957412593695, # GIF perms
    5: 1206262995223584859, # photo perms
    10: 1203672754843422761 # very cool guy role
}

def date():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

print(f"{date()} DEBUG  Starting bot...\n")

@bot.event
async def on_ready():
    print(f"\n{date()} DEBUG  Logged in as {bot.user}")
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
    print(f"\n{date()} DEBUG  --- Bot is ready! ---")
    if bot.user:
        print(f"{date()} DEBUG  Invite link: https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot%20applications.commands")
    else:
        exit(1)
    print(f"{date()} DEBUG  Connected to {total_guilds} guilds ({total_members} members)")
    print(f"{date()} DEBUG  Synced {len(synced)} slash commands in {sync_time}")
    print(f"{date()} DEBUG  Startup time: {done - startup:.4f} seconds")
    print(f"{date()} DEBUG ---------------------\n")

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


@bot.tree.command(name="help", description="Get help about the bot.") #, guild=guild)
async def help(interaction: discord.Interaction):
    help_text = (
        "## **Available Commands:**\n"
        "> **<required>**  |  **[optional]**\n\n"
        "> `/ping` - Test the bot's latency.\n"
        "> `/calc <expression>` - Simple calculator.\n"
        "> `/flip` - Flip a coin.\n"
        "> `/github` - Find the code on GitHub.\n"
        "> `/rps <str>` - Play Rock Paper Scissors.\n"
        "> `/random <int> <int>` - Generate a random number between a and b.\n"
        "> `/userinfo <str>` - Get info about a user.\n"
        "> `/quote <str>` - Get a quote (Today or Random).\n"
        "> `/meme [str]` - Get a random meme.\n"
        "> `/duck` - Get a random duck picture.\n"
        "> `/fox` - Get a random fox picture.\n"
        "> `/uptime` - Check the bot's uptime.\n"
        "> `/fact <str>` - Get a daily fact.\n"
        "> `/dog` - Get a random dog picture.\n"
    )
    await interaction.response.send_message(help_text, ephemeral=True)

@bot.tree.command(name="ping", description="Test the bot's latency.") #, guild=guild)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"> Pong! {round(bot.latency * 1000)}ms :ping_pong:", ephemeral=True)

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

@bot.tree.command(name="flip", description="Flip a coin.") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others")
async def flip(interaction: Interaction, hidden: bool = False):
    if hidden:
        await interaction.response.send_message("> " + random.choice(["Heads!", "Tails!"]), ephemeral=True)
    else:
        await interaction.response.send_message("> " + random.choice(["Heads!", "Tails!"]))

@bot.tree.command(name="github", description="Find the code on github!") #, guild=guild)
async def github(interaction: discord.Interaction):
    await interaction.response.send_message(f"> Bot made by xangey_fun <@996771607630585856>\n> <https://github.com/xangeyfun/discord-bot>")

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
        print(f"{date()} DEBUG  Quote API response status: {r.status_code}")
    except Exception as e:
        await interaction.followup.send(f"> Could not fetch quote. Please try again later.\nDetails: {e}", ephemeral=True)
        return
    data = r.json()
    if hidden:
        await interaction.followup.send(f"> \"{data[0]['q']}\" - {data[0]['a']}", ephemeral=True)
    else:
        await interaction.followup.send(f"> \"{data[0]['q']}\" - {data[0]['a']}")

@bot.tree.command(name="meme", description="Get a random meme") #, guild=guild)
@app_commands.describe(subreddit="Subreddit to get meme from (optional)", hidden="Hide the command from others")
async def meme(interaction: discord.Interaction, subreddit: str | None = None, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    url = f"https://meme-api.com/gimme/{subreddit}" if subreddit else "https://meme-api.com/gimme"
    try:
        r = requests.get(url)
        print(f"{date()} DEBUG  Meme API response status: {r.status_code}")
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

@bot.tree.command(name="duck", description="Get a random duck picture") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others")
async def duck(interaction: discord.Interaction, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    try:
        r = requests.get("https://random-d.uk/api/v2/random")
        print(f"{date()} DEBUG  Duck API response status: {r.status_code}")
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

@bot.tree.command(name="fox", description="Get a random fox picture") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others")
async def fox(interaction: discord.Interaction, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    try:
        r = requests.get("https://randomfox.ca/floof/")
        print(f"{date()} DEBUG  Fox API response status: {r.status_code}")
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

@bot.tree.command(name="uptime", description="Check the bot's uptime.") #, guild=guild)
async def uptime(interaction: discord.Interaction):
    current_time = time.time()
    uptime_seconds = int(current_time - startup)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    await interaction.response.send_message(f"> Uptime: {uptime_str}", ephemeral=True)

@bot.tree.command(name="fact", description="Get a daily fact.") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others", choice='"Today" or "Random"')
@app_commands.choices(choice=[
    app_commands.Choice(name="Today", value="Today"),
    app_commands.Choice(name="Random", value="Random")
])
async def fact(interaction: discord.Interaction, choice: str, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    if choice.lower() != "today" and choice.lower() != "random":
        await interaction.followup.send(f"> Invalid input: {choice}", ephemeral=True)
        return
    try:
        r = requests.get(f"https://uselessfacts.jsph.pl/{'today' if choice.lower() == 'today' else 'random'}.json?language=en")
        print(f"{date()} DEBUG  Fact API response status: {r.status_code}")
    except Exception as e:
        await interaction.followup.send(f"> Could not fetch fact. Please try again later.\nDetails: {e}", ephemeral=True)
        return
    data = r.json()
    if hidden:
        await interaction.followup.send(f"> {data['text']}", ephemeral=True)
    else:
        await interaction.followup.send(f"> {data['text']}")

@bot.tree.command(name="dog", description="Get a random dog picture") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others")
async def dog(interaction: discord.Interaction, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    try:
        r = requests.get("https://random.dog/woof.json")
        print(f"{date()} DEBUG  Dog API response status: {r.status_code}")
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
    if str(interaction.user.id) != allowed_user:
        await interaction.response.send_message("> You do not have permission to use this command.", ephemeral=True)
        return
    await interaction.response.send_message("> Shutting down...", ephemeral=True)
    print(f"{date()} DEBUG  Shutdown command issued by {interaction.user.name} (ID: {interaction.user.id})")
    await bot.close()

@bot.tree.command(name="level", description="Check your server level") #, guild=guild)
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
        data = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (interaction.guild.id, user.id)).fetchone()
        if not data:
            await interaction.followup.send(f"{user.display_name}'s data file was not found! Try sending a message to create one.", ephemeral=hidden) # type: ignore
            conn.close()
            return
    except Exception as e:
        await interaction.followup.send(f"Something went wrong... Please DM <@996771607630585856> about this\n> {e}", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
        conn.close()
        return
    filled_blocks = round(data["progress"] / data["out_of"] * 20)
    bar = f"{'█'*filled_blocks:<20}".replace(" ", "░")
    await interaction.followup.send(f"**{user.mention} is level {data['level']}** ({data['progress']}/{data['out_of']} XP)\n> [{bar}] {data['progress'] / data['out_of'] * 100:.1f}%\n> {data['total_xp']} total XP | {data['total_messages_xp']} messages counted for XP (out of {data['total_messages']} total messages)", allowed_mentions=discord.AllowedMentions(users=False)) # type: ignore

@bot.tree.command(name="leaderboard", description="Check the server level leaderboard") #, guild=guild)
@app_commands.describe(hidden="Hide the command from others", sort='What to sort by')
@app_commands.choices(
    sort=[
        app_commands.Choice(name="Level", value="Level"),
        app_commands.Choice(name="Total XP", value="Total XP"),
        app_commands.Choice(name="Total Messages", value="Total Messages")
    ]
)
async def fact(interaction: discord.Interaction, sort: str, hidden: bool = False):
    await interaction.response.defer(ephemeral=hidden)
    if not interaction.guild:
        await interaction.followup.send("This command only works in servers.", ephemeral=True)
        return
    
    conn = get_db()
    cur = conn.cursor()

    try:
        if sort == "Level":
            leaderboad = cur.execute(f"SELECT username, level FROM users WHERE guild_id=? ORDER BY level DESC LIMIT 10", (interaction.guild.id,)).fetchall()
        if sort == "Total XP":
            leaderboad = cur.execute(f"SELECT username, total_xp FROM users WHERE guild_id=? ORDER BY total_xp DESC LIMIT 10", (interaction.guild.id,)).fetchall()
        if sort == "Total Messages":
            leaderboad = cur.execute(f"SELECT username, total_messages FROM users WHERE guild_id=? ORDER BY total_messages DESC LIMIT 10", (interaction.guild.id,)).fetchall()

    except Exception as e:
        await interaction.followup.send(f"Something went wrong... Please DM <@996771607630585856> about this\n> {e}", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
        conn.close()
        return

    embed = discord.Embed(
        title=f"🏆 {sort} Leaderboard",
        color=discord.Color(0x7128fc)
    )

    for i, row in enumerate(leaderboad):
        username, level = row[0], row[1]

        # top 3 emojis
        if i == 0:
            rank = "🥇"
        elif i == 1:
            rank = "🥈"
        elif i == 2:
            rank = "🥉"
        else:
            rank = f"#{i+1}"

        # add each as a field
        embed.add_field(
            name=f"{rank} `{username}` - {level}",
            value=f"",
            inline=False  # one per line
        )
    conn.close()
    await interaction.followup.send(embed=embed, ephemeral=hidden)
    
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # duck reaction
    if any(word in message.content.lower() for word in ["duck", "quack"]):
        await message.add_reaction("🦆")
        await message.channel.send("Quack! 🦆")
        return

    # DM message
    if isinstance(message.channel, discord.DMChannel):
        await message.channel.send(
            "Hello! I'm a bot. Please use slash commands to interact with me."
        )
        return

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
                    last_message, total_messages, total_messages_xp, total_xp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                guild_id, user_id, message.author.display_name, message.author.name,
                0, 0, 100,
                "", 0, 0, 0
            ))

            conn.commit()

        now = time.time()

        if len(message.content) < 5:
            cur.execute("UPDATE users SET total_messages = total_messages + 1, last_message=? WHERE guild_id=? AND user_id=?", (str(datetime.datetime.now()), guild_id, user_id))
            conn.commit()
            conn.close()
            return
        
        if user_id in last_xp:
            if now - last_xp[user_id] < COOLDOWN:
                cur.execute("UPDATE users SET total_messages = total_messages + 1, last_message=? WHERE guild_id=? AND user_id=?", (str(datetime.datetime.now()), guild_id, user_id))
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
            total_messages = total_messages + 1
        WHERE guild_id=? AND user_id=?
        """, (xp, xp, str(datetime.datetime.now()), guild_id, user_id))
        conn.commit()
        user = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
        progress = user["progress"]
        out_of = user["out_of"]
        level = user["level"]

        if progress >= out_of:
            progress -= out_of
            level += 1
            out_of = int(100 + level * 20)

            if message.guild.id != 1203657476306894868:
                cur.execute("UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?", (level, progress, out_of, guild_id, user_id))
                conn.commit()
                conn.close()
                return

            level_channel = bot.get_channel(1450192627478564916)

            if level_channel and isinstance(level_channel, discord.TextChannel):
                emojis = ['⭐', '🔥', '🌟', '💎', '⚡', '🛡️', '🏹', '🎯', '👑', '🌈']
                index = min((level - 1) // 10, len(emojis) - 1)  # cap at last emoji
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
        return

    conn.close()
    await bot.process_commands(message)

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
        PRIMARY KEY (guild_id, user_id)
    )
    """)

    conn.commit()
    conn.close()

    # Run the bot
    bot.run(TOKEN) # type: ignore
