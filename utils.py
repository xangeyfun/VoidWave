from discord import app_commands, Interaction
from llm import ask_llm
import discord
import datetime
import asyncio
import random
import time
import json
import os
import sqlite3

# Constants
XP_COOLDOWN = 30
VC_COOLDOWN = 600
LLM_COOLDOWN = 15
SLOW_RESPONSE_THRESHOLD = 30
STATS_LOG_FILE = "stats_history.json"
TOPGG_TOKEN = os.getenv("TOPGG_TOKEN")
DBL_TOKEN = os.getenv("DBL_TOKEN")

# Shared state
startup = time.time()
last_llm = {}
llm_queue = asyncio.Queue(maxsize=10)
llm_queue_size = []
ai_processing = False
last_xp = {}
last_vc = {}
http_session = None


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


def log_stats(bot):
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


async def get_llm_response(msg, display_name, user_id, reply_info=None):
    start = time.time()
    for attempt in range(5):
        reply, info = await asyncio.to_thread(ask_llm, msg, display_name, user_id, reply_info)

        if reply and reply.strip() and isinstance(reply, str):
            if time.time() - start >= SLOW_RESPONSE_THRESHOLD:
                reply += ("\n\n> This was a bit slow because the model was still starting up.\n"
                          "> This might be the first response, next ones should be much faster!")
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


async def add_message_xp(bot, message):
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


async def send_qotd(bot, channel_id, role_id, guild_id):
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
    embed.set_footer(text="New question every day • Powered by VoidWave • Vote for the bot! /vote")

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


class LLMRequest:
    def __init__(self, prompt, ctx, reply_info=None):
        self.prompt = prompt
        self.reply_info = reply_info
        self.ctx = ctx


async def llm_worker(bot):
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
                await ctx.reply(reply, allowed_mentions=discord.AllowedMentions.none())
            except discord.errors.HTTPException:
                pass
            print(f"{date()} INFO  LLM response to {ctx.author} (ID: {ctx.author.id}): {reply} ({info})")
            await asyncio.sleep(1)
            llm_queue_size.pop(0)
            llm_queue.task_done()
