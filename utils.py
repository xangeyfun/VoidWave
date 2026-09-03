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
import logging
from zoneinfo import ZoneInfo

logger = logging.getLogger("utils")

# Constants
XP_COOLDOWN = 30
VC_COOLDOWN = 600
LLM_COOLDOWN = 15
SLOW_RESPONSE_THRESHOLD = 30
STATS_LOG_FILE = "stats_history.json"
TOPGG_TOKEN = os.getenv("TOPGG_TOKEN")
DBL_TOKEN = os.getenv("DBL_TOKEN")
VOTE_BOOST_MULTIPLIER = 2.0
VOTE_BOOST_DURATION = 14400
VOTE_BOOST_WEEKEND_DURATION = 21600

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
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


BLOCK_FEATURES = ("ai", "feedback", "leveling", "commands", "music")


def get_block(user_id, feature):
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT blocked_at, expires_at, note FROM user_blocks WHERE user_id=? AND feature=? "
                "AND (expires_at IS NULL OR expires_at > ?)",
                (user_id, feature, int(time.time()))
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def is_blocked(user_id, feature):
    return get_block(user_id, feature) is not None


def block_reply(user_id, feature, action):
    block = get_block(user_id, feature)
    lines = [f"You are blocked from {action}."]
    if block:
        if block["expires_at"] is not None:
            lines.append(f"> This block lifts in <t:{block['expires_at']}:R>")
        if block.get("note"):
            lines.append(f"> Reason: {block['note']}")
    return "\n".join(lines)


def qotd_now(tz_name=None):
    if tz_name:
        try:
            return datetime.datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.datetime.now().astimezone()


def qotd_tz_label(tz_name=None):
    """Short timezone name like CEST, JST or UTC."""
    now = qotd_now(tz_name)
    label = now.strftime("%Z")
    if not label:
        label = now.strftime("%z")
    return label or "server time"


def qotd_minutes(time_str=None):
    """Parse an HH:MM string into minutes of day, or None when invalid."""
    if not time_str:
        return None
    try:
        hours, minutes = time_str.split(":")
        hours, minutes = int(hours), int(minutes)
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            return hours * 60 + minutes
    except (ValueError, AttributeError):
        pass
    return None


def log_admin_event(event_type, detail="", guild_id=None, user_id=None):
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO admin_events (ts, event_type, detail, guild_id, user_id) VALUES (?, ?, ?, ?, ?)",
            (int(time.time()), event_type, detail, guild_id, user_id)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_vote_boost(user_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT multiplier FROM vote_boosts WHERE user_id=? AND expires_at > ?",
            (user_id, int(time.time()))
        ).fetchone()
        return row["multiplier"] if row else 1.0
    except sqlite3.OperationalError:
        return 1.0
    finally:
        conn.close()


LEVEL_TIERS = [
    (1, "✨", "Stardust", 0x95A5A6),
    (5, "☄️", "Nova", 0xE67E22),
    (10, "🪐", "Orbit", 0xF1C40F),
    (15, "🌠", "Comet", 0x00BCD4),
    (20, "🌀", "Pulsar", 0x9B59B6),
    (25, "🌫️", "Nebula", 0x3498DB),
    (30, "🌒", "Eclipse", 0x2ECC71),
    (40, "💫", "Supernova", 0xE74C3C),
    (50, "🔆", "Quasar", 0xF39C12),
    (60, "🕳️", "Singularity", 0xE84393),
    (80, "🌌", "Cosmic", 0x8E44AD),
    (100, "🌑", "Voidborne", 0x16A085),
]
LEVEL_RANK_UP_LEVELS = {tier[0] for tier in LEVEL_TIERS} - {1}


def build_level_up_embed(member, level, progress, out_of, boost=None, new_roles=None):
    idx = 0
    for i, tier in enumerate(LEVEL_TIERS):
        if level >= tier[0]:
            idx = i
    icon, rank, color = LEVEL_TIERS[idx][1:]
    is_rank_up = level in LEVEL_RANK_UP_LEVELS
    percent = (progress / out_of) * 100 if out_of else 0
    filled_blocks = round(percent / 100 * 10)
    bar = f"{'▰' * filled_blocks}{'▱' * (10 - filled_blocks)}"

    embed = discord.Embed(
        title=f"{icon} {'Rank Up!' if is_rank_up else 'Level Up!'}",
        description=f"{member.mention} reached **Level {level}** and {'ascended to' if is_rank_up else 'is now a'} **{rank}**!",
        color=color,
    )

    if idx + 1 < len(LEVEL_TIERS):
        next_min, next_icon, next_name, _ = LEVEL_TIERS[idx + 1]
        levels_left = next_min - level
        embed.description += f"\n{next_icon} **{levels_left}** level{'s' if levels_left != 1 else ''} until **{next_name}**!"

    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(
        name=f"Progress to Level {level + 1}",
        value=(
            f"[{bar}] `{progress:,} / {out_of:,} XP` • {percent:.1f}%\n"
            + (
                f"⚡ **{boost['multiplier']:.1f}x XP boost** active for **{int((boost['expires_at'] - time.time()) // 60)} min**!"
                if boost
                else "⚡ Vote for **2x XP** for **4 hours**! `/vote`"
            )
        ),
        inline=False,
    )

    if new_roles:
        roles = " ".join(role.mention for role in new_roles)
        embed.add_field(
            name="🏅 New Role" if len(new_roles) == 1 else "🏅 New Roles",
            value=f"You've earned the **{roles}** role{'s' if len(new_roles) > 1 else ''}!",
            inline=False,
        )

    embed.set_footer(text="VoidWave • Vote for 2x XP! /vote")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return embed


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

    cur.execute("SELECT COUNT(*) FROM user_ratings")
    total_ratings = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(AVG(rating), 0) FROM user_ratings")
    avg_rating = round(cur.fetchone()[0], 1)

    rating_distribution = {rating: 0 for rating in range(1, 6)}
    for r in cur.execute("SELECT rating, COUNT(*) c FROM user_ratings GROUP BY rating"):
        if 1 <= r["rating"] <= 5:
            rating_distribution[r["rating"]] = r["c"]

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
        "total_ratings": total_ratings,
        "avg_rating": avg_rating,
        "rating_distribution": rating_distribution,
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

    logger.info("Stats snapshot logged (%s guilds, %s members, %s XP)", total_guilds, total_members, total_xp)


async def get_llm_response(msg, display_name, user_id, reply_info=None):
    start = time.time()
    for attempt in range(5):
        reply, info = await asyncio.to_thread(ask_llm, msg, display_name, user_id, reply_info)

        if reply and reply.strip() and isinstance(reply, str):
            if time.time() - start >= SLOW_RESPONSE_THRESHOLD:
                reply += ("\n\n> This was a bit slow because the model was still starting up.\n"
                          "> This might be the first response, next ones should be much faster!")
            return reply, info + f", Attempts: {attempt + 1}"

        logger.warning("LLM empty response, retrying (%s/5)", attempt + 1)
        await asyncio.sleep(0.5)

    logger.error("LLM empty response after 5 tries")
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

    if is_blocked(user_id, "leveling"):
        return

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
        multiplier = get_vote_boost(user_id)
        if multiplier > 1:
            xp = int(xp * multiplier)
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
            has_channel = bool(channel and isinstance(channel, discord.TextChannel))

            boost = cur.execute("SELECT multiplier, expires_at FROM vote_boosts WHERE user_id=? AND expires_at > ?", (user_id, int(time.time()))).fetchone()

            level_roles = (cur.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ?", (guild_id,)).fetchall())
            level_roles = dict(level_roles) if level_roles else None

            new_roles = []
            if level_roles:
                for req_level, role_id in level_roles.items():
                    if level >= req_level:
                        role = message.guild.get_role(role_id)

                        if role and role not in message.author.roles:
                            try:
                                await message.author.add_roles(role)
                                new_roles.append(role)
                            except discord.Forbidden:
                                logger.warning("Missing permissions to assign role %s in guild %s", role_id, guild_id)
                            except Exception as e:
                                logger.error("Failed to assign role: %s", e)

            if has_channel:
                embed = build_level_up_embed(
                    member=message.author,
                    level=level,
                    progress=progress,
                    out_of=out_of,
                    boost=dict(boost) if boost else None,
                    new_roles=new_roles or None,
                )
                try:
                    await channel.send(content=f"{message.author.mention} reached Level {level}!", embed=embed)
                except discord.Forbidden:
                    logger.warning("Missing permissions to send level-up message in %s for guild %s", channel.id, guild_id)
                except Exception as e:
                    logger.error("Failed to send level-up message: %s", e)

                log_admin_event(
                    "level_up",
                    f"{message.author.display_name} reached level {level}",
                    guild_id=guild_id,
                    user_id=user_id,
                )

        cur.execute("UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?", (level, progress, out_of, guild_id, user_id))
        conn.commit()
    finally:
        conn.close()


async def send_qotd(bot, channel_id, role_id, guild_id):
    channel = bot.get_channel(channel_id)

    if not channel or not isinstance(channel, discord.TextChannel):
        logger.warning("QOTD channel with ID %s not found for guild %s, disabling QOTD", channel_id, guild_id)
        try:
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute("UPDATE guild_settings SET qotd_enabled=0 WHERE guild_id=?", (guild_id,))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error("Failed to disable QOTD for guild %s: %s", guild_id, e)
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
            except discord.Forbidden:
                logger.warning("Missing permissions to delete old QOTD thread for guild %s", guild_id)
            except Exception as e:
                logger.error("Failed to delete old QOTD thread: %s", e)

            try:
                old_msg = await channel.fetch_message(guild_settings["last_qotd_id"])
                await old_msg.delete()

            except discord.Forbidden:
                logger.warning("Missing permissions to delete old QOTD message for guild %s", guild_id)
            except Exception as e:
                logger.error("Failed to delete old QOTD message: %s", e)

        if guild_settings and guild_settings["qotd_queue"]:
            queue = json.loads(guild_settings["qotd_queue"])

    except Exception as e:
        logger.error("Failed to clean up old QOTD: %s", e)

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
        color=0x7128fc,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.set_footer(text="New question every day • Powered by VoidWave • Vote for 2x XP! /vote")

    msg = None
    try:
        msg = await channel.send(embed=embed)
    except discord.Forbidden:
        logger.error("Missing permissions to send QOTD in channel %s for guild %s", channel_id, guild_id)
        conn.close()
        return
    except Exception as e:
        logger.error("Failed to send QOTD message: %s", e)
        conn.close()
        return

    thread = None
    try:
        thread = await msg.create_thread(name=f"💬 QOTD • {datetime.datetime.now().strftime('%b %d')}", auto_archive_duration=1440)
    except discord.Forbidden:
        logger.warning("Missing permissions to create thread in channel %s for guild %s", channel_id, guild_id)
    except Exception as e:
        logger.error("Failed to create QOTD thread: %s", e)

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
            logger.warning("Missing permissions to send QOTD ping in thread for guild %s", guild_id)
        except Exception as e:
            logger.error("Failed to send QOTD ping: %s", e)

    try:
        cur.execute("UPDATE guild_settings SET last_qotd_id=?, last_qotd_thread_id=?, qotd_queue=? WHERE guild_id=?", (msg.id, thread.id if thread else None, json.dumps(queue), guild_id))
        conn.commit()

    except Exception as e:
        logger.error("Failed to save QOTD info to database: %s", e)

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
            if os.getenv("DEBUG") == "true":
                logger.info("LLM response to %s (ID: %s): %s (%s)", ctx.author, ctx.author.id, reply, info)
            await asyncio.sleep(1)
            llm_queue_size.pop(0)
            llm_queue.task_done()
