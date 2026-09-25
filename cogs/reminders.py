import calendar
import datetime
import logging
import re
import time as time_module
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.config import _timezone_autocomplete
from utils import get_db, get_user_pref, log_admin_event, qotd_now, qotd_tz_label, set_user_pref

logger = logging.getLogger("cogs.reminders")

DEFAULT_TIMEZONE = "UTC"

_DEFAULT_TIME_RE = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")

DURATION_UNITS = {
    "m": datetime.timedelta(minutes=1),
    "h": datetime.timedelta(hours=1),
    "d": datetime.timedelta(days=1),
    "w": datetime.timedelta(weeks=1),
}

RECURRENCE_LABELS = {
    "daily": "daily",
    "hourly": "hourly",
    "weekly": "weekly",
    "biweekly": "every 2 weeks",
    "weekdays": "weekdays (Mon-Fri)",
    "weekends": "weekends (Sat-Sun)",
    "monthly": "monthly",
    "yearly": "yearly",
}

RECURRENCE_PRESETS = ("daily", "hourly", "weekly", "biweekly", "weekdays", "weekends", "monthly", "yearly")

_DURATION_WORDS = {"w": "week", "d": "day", "h": "hour", "m": "minute"}

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

_DURATION_WHOLE_RE = re.compile(r"^\s*\d+\s*[mhdw](?:\s*[,+]?\s*\d+\s*[mhdw])*\s*$")
_DURATION_RE = re.compile(r"(\d+)\s*([mhdw])")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_RELATIVE_RE = re.compile(r"^(today|tonight|tomorrow)(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_WEEKDAY_RE = re.compile(r"^(next\s+)?([a-z]+)(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_DMY_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$")

_PARSE_HINT = "Try `2h`, `tomorrow 16:00`, `friday 18:30`, or a full date like `2026-09-20 12:00`."


def _hhmm(match, hg, mg, sg):
    if match.group(hg) is None:
        return None
    hour = int(match.group(hg))
    minute = int(match.group(mg))
    second = int(match.group(sg) or 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError("Invalid time. Use the 24-hour clock, e.g. `18:30`.")
    return hour, minute, second


def _duration_delta(dur):
    delta = datetime.timedelta(0)
    for amount, unit in _DURATION_RE.findall(dur):
        delta += int(amount) * DURATION_UNITS[unit]
    return delta


def parse_recurrence(text):
    if not text:
        return None
    lowered = " ".join(text.strip().lower().split())
    if lowered in RECURRENCE_PRESETS:
        return lowered
    dur = re.sub(r"^every(?:\s+|:)?", "", lowered).strip()
    if _DURATION_WHOLE_RE.match(dur):
        if _duration_delta(dur) <= datetime.timedelta(0):
            raise ValueError("The repeat interval must be positive, e.g. `every 2h`.")
        return f"every:{dur}"
    raise ValueError(
        "Recurrence must be one of `daily`, `hourly`, `weekly`, `biweekly`, `weekdays`, `weekends`, `monthly`, `yearly`, or a repeat like `every 2h`, `every 1h30m`, `every 3d`."
    )


def _describe_duration(dur):
    parts = []
    for amount, unit in _DURATION_RE.findall(dur):
        n = int(amount)
        name = _DURATION_WORDS[unit]
        parts.append(f"{n} {name}{'s' if n != 1 else ''}")
    return " ".join(parts)


def recurrence_label(recurring):
    if not recurring:
        return ""
    if recurring in RECURRENCE_LABELS:
        return RECURRENCE_LABELS[recurring]
    if recurring.startswith("every:"):
        return "every " + _describe_duration(recurring[len("every:"):])
    return recurring


async def _recurring_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    choices = [
        app_commands.Choice(name="Daily", value="daily"),
        app_commands.Choice(name="Hourly", value="hourly"),
        app_commands.Choice(name="Weekly", value="weekly"),
        app_commands.Choice(name="Biweekly (every 2 weeks)", value="biweekly"),
        app_commands.Choice(name="Weekdays (Mon-Fri)", value="weekdays"),
        app_commands.Choice(name="Weekends (Sat-Sun)", value="weekends"),
        app_commands.Choice(name="Monthly", value="monthly"),
        app_commands.Choice(name="Yearly", value="yearly"),
        app_commands.Choice(name="Every 2 hours", value="every 2h"),
        app_commands.Choice(name="Every 1h 30m", value="every 1h30m"),
        app_commands.Choice(name="Every 3 days", value="every 3d"),
    ]
    query = current.strip().lower()
    if not query:
        return choices
    return [c for c in choices if c.value.lower().startswith(query) or query in c.value.lower()]


def _at_clock(base, clock):
    if clock is None:
        return None
    hour, minute, second = clock
    return base.replace(hour=hour, minute=minute, second=second, microsecond=0)


def parse_reminder_time(text, tz_name):
    tz = ZoneInfo(tz_name)
    now = qotd_now(tz_name)
    lowered = " ".join(text.strip().lower().split())
    if not lowered:
        raise ValueError(f"You didn't give me a time. {_PARSE_HINT}")

    if _DURATION_WHOLE_RE.match(lowered):
        return now + _duration_delta(lowered)

    m = _RELATIVE_RE.match(lowered)
    if m:
        base = now + datetime.timedelta(days=1) if m.group(1) == "tomorrow" else now
        target = _at_clock(base, _hhmm(m, 2, 3, 4) or (9, 0, 0))
        if target <= now:
            raise ValueError(f"`{text}` has already passed today. Try `tomorrow 16:00` or give a date.")
        return target

    m = _TIME_RE.match(lowered)
    if m:
        target = _at_clock(now, _hhmm(m, 1, 2, 3))
        if target <= now:
            target += datetime.timedelta(days=1)
        return target

    m = _ISO_RE.match(lowered)
    if m:
        target = datetime.datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            *(_hhmm(m, 4, 5, 6) or (9, 0, 0)), tzinfo=tz,
        )
        if target <= now:
            raise ValueError(f"`{text}` is in the past.")
        return target

    m = _DMY_RE.match(lowered)
    if m:
        target = datetime.datetime(
            int(m.group(3)), int(m.group(2)), int(m.group(1)),
            *(_hhmm(m, 4, 5, 6) or (9, 0, 0)), tzinfo=tz,
        )
        if target <= now:
            raise ValueError(f"`{text}` is in the past.")
        return target

    m = _WEEKDAY_RE.match(lowered)
    if m and m.group(2) in WEEKDAYS:
        days = (WEEKDAYS[m.group(2)] - now.weekday()) % 7
        clock = _hhmm(m, 3, 4, 5) or (9, 0, 0)
        target = _at_clock(now + datetime.timedelta(days=days), clock)
        if target <= now or (days == 0 and m.group(1)):
            target += datetime.timedelta(days=7)
        return target

    raise ValueError(f"Couldn't understand `{text}`. {_PARSE_HINT}")


def next_occurrence(trigger_ts, tz_name, recurring):
    tz = ZoneInfo(tz_name)
    current = datetime.datetime.fromtimestamp(trigger_ts, tz=tz)
    if recurring == "hourly":
        return current + datetime.timedelta(hours=1)
    if recurring == "daily":
        return current + datetime.timedelta(days=1)
    if recurring == "weekly":
        return current + datetime.timedelta(days=7)
    if recurring == "biweekly":
        return current + datetime.timedelta(days=14)
    if recurring == "weekdays":
        nxt = current + datetime.timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += datetime.timedelta(days=1)
        return nxt
    if recurring == "weekends":
        nxt = current + datetime.timedelta(days=1)
        while nxt.weekday() < 5:
            nxt += datetime.timedelta(days=1)
        return nxt
    if recurring == "monthly":
        year, month = current.year, current.month + 1
        if month > 12:
            year, month = year + 1, 1
        day = min(current.day, calendar.monthrange(year, month)[1])
        return current.replace(year=year, month=month, day=day)
    if recurring == "yearly":
        year, month = current.year + 1, current.month
        day = min(current.day, calendar.monthrange(year, month)[1])
        return current.replace(year=year, month=month, day=day)
    if recurring.startswith("every:"):
        return current + _duration_delta(recurring[len("every:"):])
    raise ValueError(f"Unknown recurrence: {recurring}")


def get_saved_timezone(user_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT remind_tz FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
        return row["remind_tz"] if row and row["remind_tz"] else None
    finally:
        conn.close()


def get_saved_recurring(user_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT remind_recurring FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
        return row["remind_recurring"] if row and row["remind_recurring"] else None
    finally:
        conn.close()


def _validate_timezone(tz_name):
    try:
        ZoneInfo(tz_name)
        return True
    except Exception:
        return False


async def _reminder_id_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id FROM reminders WHERE user_id = ? AND CAST(id AS TEXT) LIKE ? ORDER BY trigger_at LIMIT 25",
            (interaction.user.id, f"%{current}%"),
        ).fetchall()
    finally:
        conn.close()
    return [app_commands.Choice(name=f"#{row['id']}", value=row["id"]) for row in rows]


class _ConfirmClearView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id

    def _guard(self, interaction):
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Yes, delete all", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
            return
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM reminders WHERE user_id = ?", (interaction.user.id,))
            deleted = cur.rowcount
            conn.commit()
        except Exception as e:
            logger.error("Failed to clear reminders for %s: %s", interaction.user.id, e)
            await interaction.response.send_message("Failed to clear your reminders. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()
        for item in self.children:
            item.disabled = True
        embed = discord.Embed(description=f"Deleted your **{deleted}** reminder{'s' if deleted != 1 else ''}.", color=discord.Color(0x7128fc))
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()
        logger.info("%s cleared %s reminder(s)", interaction.user, deleted)

    @discord.ui.button(label="Keep them", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        embed = discord.Embed(description="Nothing was deleted.", color=discord.Color(0x7128fc))
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


class ReminderCog(commands.Cog):
    remind = discord.app_commands.Group(
        name="remind",
        description="Set reminders (DM or channel)",
        allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=True),
        allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True),
    )

    def __init__(self, bot):
        self.bot = bot

    async def _can_post_to(self, channel, user):
        guild = channel.guild
        if guild is None:
            return f"I can't look up <#{channel.id}> to check permissions there."
        member = guild.get_member(user.id)
        if member is None:
            try:
                member = await guild.fetch_member(user.id)
            except discord.NotFound:
                member = None
        if member is None:
            return f"Channel reminders need you to be a member of **{guild.name}**, and I can't find you there. Leave `channel:` empty to use your DMs instead."
        missing = [n.replace("_", " ") for n in ("view_channel", "send_messages") if not getattr(channel.permissions_for(member), n)]
        if missing:
            return f"You can't post to <#{channel.id}> yourself (missing **{', '.join(missing)}**). Pick a channel you can use or leave `channel:` empty for DMs."
        bot_member = guild.get_member(self.bot.user.id)
        if bot_member is None:
            try:
                bot_member = await guild.fetch_member(self.bot.user.id)
            except discord.NotFound:
                bot_member = None
        if bot_member is None:
            return f"I can't resolve my roles in that server, so I can't verify I can post to <#{channel.id}>."
        missing = [n.replace("_", " ") for n in ("view_channel", "send_messages") if not getattr(channel.permissions_for(bot_member), n)]
        if missing:
            return f"I can't deliver to <#{channel.id}>: I'm missing **{', '.join(missing)}** there. Pick another channel or leave `channel:` empty to use DMs."
        return None

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @remind.command(name="create", description="Create a reminder that gets sent to your DMs")
    @app_commands.describe(
        message="What to remind you about",
        time="When to remind you, e.g. 10m, 2h, tomorrow 16:00, friday 18:30 (omit to use your saved default time)",
        recurring="Repeat: daily, weekly, weekdays, monthly, or every 2h / every 3d (optional)",
        timezone="Override your saved timezone for this reminder (optional)",
        channel="Deliver in a server channel instead of your DMs (optional)",
    )
    @app_commands.autocomplete(recurring=_recurring_autocomplete, timezone=_timezone_autocomplete)
    async def create_reminder(self, interaction: discord.Interaction, message: str, time: str = None, recurring: str = None, timezone: str = None, channel: discord.TextChannel = None):
        message = message.strip()
        if not message:
            await interaction.response.send_message("Give me something to remind you about.", ephemeral=True)
            return

        if not time or not time.strip():
            saved_time = get_user_pref(interaction.user.id, "remind_time")
            if not saved_time:
                await interaction.response.send_message(
                    "You didn't give a time. Save a default one with `/remind defaults time:09:30` so you can skip the `time:` option, or pass one here.",
                    ephemeral=True,
                )
                return
            time = saved_time

        if channel is None:
            saved_channel_id = get_user_pref(interaction.user.id, "remind_channel")
            if saved_channel_id:
                saved_channel = self.bot.get_channel(saved_channel_id)
                if saved_channel is None:
                    try:
                        saved_channel = await self.bot.fetch_channel(saved_channel_id)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        saved_channel = None
                if saved_channel is not None:
                    reason = await self._can_post_to(saved_channel, interaction.user)
                    if reason is None:
                        channel = saved_channel
                    else:
                        log_admin_event("user_pref_drop", f"remind_channel {saved_channel_id} no longer usable: {reason}", guild_id=interaction.guild_id, user_id=interaction.user.id)

        tz_name = None
        if timezone:
            if not _validate_timezone(timezone):
                await interaction.response.send_message(f"Unknown timezone `{timezone}`. Type part of a nearby city and pick from the suggestions, e.g. `Europe/Amsterdam`.", ephemeral=True)
                return
            tz_name = timezone
        else:
            tz_name = get_saved_timezone(interaction.user.id) or DEFAULT_TIMEZONE

        try:
            target = parse_reminder_time(time, tz_name)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        if recurring is None:
            recurring = get_saved_recurring(interaction.user.id)

        try:
            recurring = parse_recurrence(recurring)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        if channel is not None:
            reason = await self._can_post_to(channel, interaction.user)
            if reason:
                await interaction.response.send_message(reason, ephemeral=True)
                return

        if recurring == "weekdays" and target.weekday() >= 5:
            target = _at_clock(
                target + datetime.timedelta(days=7 - target.weekday()),
                (target.hour, target.minute, target.second),
            )
        elif recurring == "weekends" and target.weekday() < 5:
            target = _at_clock(
                target + datetime.timedelta(days=5 - target.weekday()),
                (target.hour, target.minute, target.second),
            )

        trigger_ts = int(target.timestamp())
        created_at = int(time_module.time())
        channel_id = channel.id if channel else None

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO reminders (user_id, message, trigger_at, recurring, tz, created_at, channel_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (interaction.user.id, message, trigger_ts, recurring, tz_name, created_at, channel_id),
            )
            conn.commit()
            reminder_id = cur.lastrowid
        except Exception as e:
            logger.error("Failed to create reminder for %s: %s", interaction.user.id, e)
            await interaction.response.send_message("Failed to create the reminder. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        dest = f"<#{channel.id}>" if channel else "your DMs"
        msg = (
            f"⏰ Reminder `#{reminder_id}` set!\n"
            f"> {message}\n\n"
            f"Fires <t:{trigger_ts}:R> (<t:{trigger_ts}:f>) in `{tz_name}` ({qotd_tz_label(tz_name)})\n"
            f"Delivers to {dest}."
        )
        if recurring:
            msg += f"\nRepeats **{recurrence_label(recurring)}**."

        if not timezone:
            msg += "\n> 💡 *Tip: save your default timezone with `/remind timezone` so future reminders use it automatically.*"
        if not recurring and not get_saved_recurring(interaction.user.id):
            msg += "\n> 💡 *Tip: repeat automatically with `recurring:` (e.g. `daily`) or set a default with `/remind defaults`.*"

        msg += "\n\nManage reminders with `/remind list`."
        await interaction.response.send_message(msg, ephemeral=True)
        logger.info("%s created reminder #%s in %s for %s: %s", interaction.user, reminder_id, qotd_tz_label(tz_name), trigger_ts, message[:80])

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @remind.command(name="list", description="List your active reminders")
    async def list_reminders(self, interaction: discord.Interaction):
        conn = get_db()
        try:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT id, message, trigger_at, recurring, tz, channel_id FROM reminders WHERE user_id = ? ORDER BY trigger_at",
                (interaction.user.id,),
            ).fetchall()
        except Exception as e:
            logger.error("Failed to load reminders for %s: %s", interaction.user.id, e)
            await interaction.response.send_message("Failed to load your reminders. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        if not rows:
            await interaction.response.send_message(
                "You have no reminders. Create one with `/remind create`!\n"
                "> 💡 *Tip: set your default timezone (`/remind timezone`) and repeat (`/remind defaults`) once, then only pass what changes.*",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"⏰ Your reminders ({len(rows)})",
            color=discord.Color(0x7128fc),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        for r in rows[:25]:
            preview = r["message"] if len(r["message"]) <= 120 else r["message"][:117] + "..."
            dest = f"<#{r['channel_id']}>" if r["channel_id"] else "DM"
            line = f"> {preview}\nFires <t:{r['trigger_at']}:f> • 📨 {dest}"
            if r["recurring"]:
                line += f"\nRepeats **{recurrence_label(r['recurring'])}**"
            embed.add_field(
                name=f"`#{r['id']}` · <t:{r['trigger_at']}:R>",
                value=line,
                inline=False,
            )
        if len(rows) > 25:
            embed.add_field(name=f"\u2026 and {len(rows) - 25} more", value="Delete old ones with `/remind delete` to keep the list tidy.", inline=False)
        embed.set_footer(text="Delete one with /remind delete")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @remind.command(name="delete", description="Delete a reminder by its ID")
    @app_commands.describe(id="The reminder ID (shown when you create or list reminders)")
    @app_commands.autocomplete(id=_reminder_id_autocomplete)
    async def delete_reminder(self, interaction: discord.Interaction, id: int):
        conn = get_db()
        try:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT id, recurring FROM reminders WHERE id = ? AND user_id = ?",
                (id, interaction.user.id),
            ).fetchone()
            if not row:
                await interaction.response.send_message(f"No reminder `#{id}` found. Check `/remind list` for your active reminders.", ephemeral=True)
                return
            cur.execute("DELETE FROM reminders WHERE id = ? AND user_id = ?", (id, interaction.user.id))
            conn.commit()
        except Exception as e:
            logger.error("Failed to delete reminder #%s for %s: %s", id, interaction.user.id, e)
            await interaction.response.send_message("Failed to delete the reminder. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        msg = f"Reminder `#{id}` deleted."
        if row["recurring"]:
            msg += " It won't repeat anymore."
        await interaction.response.send_message(msg, ephemeral=True)
        logger.info("%s deleted reminder #%s", interaction.user, id)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @remind.command(name="edit", description="Change a reminder's message, time, or timezone")
    @app_commands.describe(
        id="The reminder ID (shown when you create or list reminders)",
        message="New reminder text (optional)",
        time="New trigger time, e.g. 10m or tomorrow 16:00 (optional)",
        timezone="New timezone for this reminder (optional)",
    )
    @app_commands.autocomplete(id=_reminder_id_autocomplete, timezone=_timezone_autocomplete)
    async def edit_reminder(self, interaction: discord.Interaction, id: int, message: str = None, time: str = None, timezone: str = None):
        if message is not None:
            message = message.strip()
        if not message and time is None and timezone is None:
            await interaction.response.send_message("Give me something to change: a new `message`, `time`, or `timezone`.", ephemeral=True)
            return

        conn = get_db()
        try:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT id, message, trigger_at, recurring, tz, channel_id FROM reminders WHERE id = ? AND user_id = ?",
                (id, interaction.user.id),
            ).fetchone()
            if not row:
                await interaction.response.send_message(f"No reminder `#{id}` found. Check `/remind list` for your active reminders.", ephemeral=True)
                return

            tz_name = row["tz"]
            if timezone:
                if not _validate_timezone(timezone):
                    await interaction.response.send_message(f"Unknown timezone `{timezone}`. Type part of a nearby city and pick from the suggestions, e.g. `Europe/Amsterdam`.", ephemeral=True)
                    return
                tz_name = timezone

            trigger_ts = row["trigger_at"]
            if time:
                try:
                    target = parse_reminder_time(time, tz_name)
                except ValueError as e:
                    await interaction.response.send_message(str(e), ephemeral=True)
                    return
                if row["recurring"] == "weekdays" and target.weekday() >= 5:
                    target = _at_clock(
                        target + datetime.timedelta(days=7 - target.weekday()),
                        (target.hour, target.minute, target.second),
                    )
                elif row["recurring"] == "weekends" and target.weekday() < 5:
                    target = _at_clock(
                        target + datetime.timedelta(days=5 - target.weekday()),
                        (target.hour, target.minute, target.second),
                    )
                trigger_ts = int(target.timestamp())

            new_message = message if message is not None else row["message"]
            cur.execute(
                "UPDATE reminders SET message = ?, trigger_at = ?, tz = ? WHERE id = ? AND user_id = ?",
                (new_message, trigger_ts, tz_name, id, interaction.user.id),
            )
            conn.commit()
        except Exception as e:
            logger.error("Failed to edit reminder #%s for %s: %s", id, interaction.user.id, e)
            await interaction.response.send_message("Failed to edit the reminder. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        msg = (
            f"Reminder `#{id}` updated:\n> {new_message}\n"
            f"Fires <t:{trigger_ts}:R> (<t:{trigger_ts}:f>) in `{tz_name}` ({qotd_tz_label(tz_name)})"
        )
        if row["recurring"]:
            msg += f"\nRepeats **{recurrence_label(row['recurring'])}**."
        await interaction.response.send_message(msg, ephemeral=True)
        logger.info("%s edited reminder #%s", interaction.user, id)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @remind.command(name="clear", description="Delete all your reminders (asks for confirmation)")
    async def clear_reminders(self, interaction: discord.Interaction):
        conn = get_db()
        try:
            count = conn.execute("SELECT COUNT(*) AS n FROM reminders WHERE user_id = ?", (interaction.user.id,)).fetchone()["n"]
        except Exception as e:
            logger.error("Failed to count reminders for %s: %s", interaction.user.id, e)
            await interaction.response.send_message("Failed to load your reminders. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        if not count:
            await interaction.response.send_message("You have no reminders to clear. Create one with `/remind create`!", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Clear all {count} reminder{'s' if count != 1 else ''}?",
            description="This permanently deletes every reminder you've created, including recurring ones. There's no undo.",
            color=discord.Color(0x7128fc),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True, view=_ConfirmClearView(interaction.user.id))
        logger.info("%s opened clear-reminders confirmation (%s reminders)", interaction.user, count)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @remind.command(name="timezone", description="Set the default timezone for your reminders")
    @app_commands.describe(timezone="IANA timezone, e.g. Europe/Amsterdam (leave empty to view your current one)")
    @app_commands.autocomplete(timezone=_timezone_autocomplete)
    async def reminder_timezone(self, interaction: discord.Interaction, timezone: str = None):
        if timezone is None:
            saved = get_saved_timezone(interaction.user.id) or DEFAULT_TIMEZONE
            await interaction.response.send_message(f"Your reminder timezone is `{saved}` ({qotd_tz_label(saved)}). Set it with `/remind timezone <zone>`.", ephemeral=True)
            return

        if not _validate_timezone(timezone):
            await interaction.response.send_message(f"Unknown timezone `{timezone}`. Type part of a nearby city and pick from the suggestions, e.g. `Europe/Amsterdam`.", ephemeral=True)
            return

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO user_prefs (user_id, remind_tz) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET remind_tz = excluded.remind_tz",
                (interaction.user.id, timezone),
            )
            conn.commit()
        except Exception as e:
            logger.error("Failed to save reminder timezone for %s: %s", interaction.user.id, e)
            await interaction.response.send_message("Failed to save your timezone. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        await interaction.response.send_message(f"Your reminder timezone is now `{timezone}` ({qotd_tz_label(timezone)}). Future reminders use it unless you pass a `timezone:` override.", ephemeral=True)
        logger.info("%s set reminder timezone to %s", interaction.user, timezone)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @remind.command(name="defaults", description="View or set your default reminder settings (timezone, repeat, time, channel)")
    @app_commands.describe(
        timezone="New default timezone, e.g. Europe/Amsterdam (optional)",
        recurring="New default repeat, e.g. daily, weekly, every 2h, or `none` to clear (optional)",
        time="New default time of day, e.g. 09:30, used when you skip the time in a reminder (optional)",
        channel="Default delivery channel instead of your DMs (optional)",
        clear="Clear the saved channel and/or time, e.g. after leaving a server (optional)",
    )
    @app_commands.autocomplete(timezone=_timezone_autocomplete, recurring=_recurring_autocomplete)
    @app_commands.choices(clear=[
        app_commands.Choice(name="Nothing", value="none"),
        app_commands.Choice(name="Default channel", value="channel"),
        app_commands.Choice(name="Default time", value="time"),
        app_commands.Choice(name="Both", value="all"),
    ])
    async def reminder_defaults(self, interaction: discord.Interaction, timezone: str = None, recurring: str = None, time: str = None, channel: discord.TextChannel = None, clear: str = "none"):
        if timezone is not None and not _validate_timezone(timezone):
            await interaction.response.send_message(f"Unknown timezone `{timezone}`. Type part of a nearby city and pick from the suggestions, e.g. `Europe/Amsterdam`.", ephemeral=True)
            return

        new_recurring = None
        recurring_cleared = False
        if recurring is not None:
            if recurring.strip().lower() in ("none", "off", "no"):
                recurring_cleared = True
            else:
                try:
                    new_recurring = parse_recurrence(recurring)
                except ValueError as e:
                    await interaction.response.send_message(str(e), ephemeral=True)
                    return

        normalized_time = None
        time_invalid = False
        if time is not None and time.strip():
            m = _DEFAULT_TIME_RE.match(time.strip())
            if m:
                normalized_time = f"{int(m.group(1))}:{m.group(2)}"
            else:
                time_invalid = True
        if time_invalid:
            await interaction.response.send_message("The default time must be a clock time like `09:30` or `17:00`.", ephemeral=True)
            return

        clear_channel = clear in ("channel", "all")
        clear_time = clear in ("time", "all")

        if channel is not None and not clear_channel:
            reason = await self._can_post_to(channel, interaction.user)
            if reason:
                await interaction.response.send_message(reason, ephemeral=True)
                return

        if timezone is None and recurring is None and time is None and channel is None and not clear_channel and not clear_time:
            tz = get_saved_timezone(interaction.user.id) or DEFAULT_TIMEZONE
            rec = get_saved_recurring(interaction.user.id)
            rec_label = recurrence_label(rec) if rec else "no repeat"
            chan = get_user_pref(interaction.user.id, "remind_channel")
            saved_time = get_user_pref(interaction.user.id, "remind_time")
            await interaction.response.send_message(
                "Your reminder defaults:\n"
                f"**Timezone:** `{tz}` ({qotd_tz_label(tz)})\n"
                f"**Repeat:** `{rec_label}`\n"
                f"**Deliver to:** `{f'<#{chan}>' if chan else 'your DMs'}`\n"
                f"**Default time:** `{saved_time or 'none'}`\n\n"
                "Set them with `/remind defaults`, e.g. `timezone:Europe/Amsterdam recurring:daily time:09:30 channel:#reminders`, and clear with `clear:`.",
                ephemeral=True,
            )
            return

        conn = get_db()
        try:
            cur = conn.cursor()
            if timezone is not None:
                cur.execute(
                    "INSERT INTO user_prefs (user_id, remind_tz) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET remind_tz = excluded.remind_tz",
                    (interaction.user.id, timezone),
                )
            if recurring is not None:
                cur.execute(
                    "INSERT INTO user_prefs (user_id, remind_recurring) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET remind_recurring = excluded.remind_recurring",
                    (interaction.user.id, new_recurring),
                )
            if time is not None:
                set_user_pref(interaction.user.id, remind_time=normalized_time)
            if channel is not None and not clear_channel:
                set_user_pref(interaction.user.id, remind_channel=channel.id)
            if clear_time:
                set_user_pref(interaction.user.id, remind_time=None)
            if clear_channel:
                set_user_pref(interaction.user.id, remind_channel=None)
            conn.commit()
        except Exception as e:
            logger.error("Failed to save reminder defaults for %s: %s", interaction.user.id, e)
            await interaction.response.send_message("Failed to save your defaults. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        parts = []
        if timezone is not None:
            parts.append(f"**Timezone:** `{timezone}` ({qotd_tz_label(timezone)})")
        if recurring_cleared:
            parts.append("**Repeat:** cleared (`daily`, `weekly`, etc. will ask each time)")
        elif new_recurring is not None:
            parts.append(f"**Repeat:** default `{recurrence_label(new_recurring)}`")
        if time is not None and normalized_time:
            parts.append(f"**Default time:** `{normalized_time}`")
        if clear_time:
            parts.append("**Default time:** cleared")
        if channel is not None and not clear_channel:
            parts.append(f"**Deliver to:** <#{channel.id}>")
        if clear_channel:
            parts.append("**Default channel:** cleared (deliver to your DMs)")
        msg = "Default reminder settings updated:\n" + "\n".join(parts)
        msg += "\n\nFuture `/remind create` calls use these unless you set `time:`, `timezone:`, `recurring:` or `channel:` directly."
        await interaction.response.send_message(msg, ephemeral=True)
        logger.info("%s updated reminder defaults (tz=%s, recurring=%s, time=%s, channel=%s)", interaction.user, timezone, new_recurring, normalized_time, channel.id if channel else None)

    @tasks.loop(seconds=5)
    async def reminder_loop(self):
        conn = get_db()
        try:
            cur = conn.cursor()
            try:
                due = cur.execute(
                    "SELECT id, user_id, message, trigger_at, recurring, tz, channel_id FROM reminders WHERE trigger_at <= ? ORDER BY trigger_at",
                    (int(time_module.time()),),
                ).fetchall()
            except Exception as e:
                logger.error("Failed to fetch due reminders: %s", e)
                return

            for row in due:
                result = await self._deliver(row)
                if result == "retry":
                    logger.info("Couldn't DM reminder #%s to %s yet, will retry", row["id"], row["user_id"])
                    continue
                if row["recurring"]:
                    try:
                        nxt = next_occurrence(row["trigger_at"], row["tz"], row["recurring"])
                        cur.execute("UPDATE reminders SET trigger_at = ? WHERE id = ?", (int(nxt.timestamp()), row["id"]))
                    except Exception as e:
                        logger.error("Failed to reschedule recurring reminder #%s: %s", row["id"], e)
                        cur.execute("DELETE FROM reminders WHERE id = ?", (row["id"],))
                else:
                    cur.execute("DELETE FROM reminders WHERE id = ?", (row["id"],))
                conn.commit()
        finally:
            conn.close()

    async def _deliver(self, row):
        user = None
        try:
            user = self.bot.get_user(row["user_id"]) or await self.bot.fetch_user(row["user_id"])
        except discord.NotFound:
            logger.warning("Reminder #%s for unknown user %s", row["id"], row["user_id"])

        embed = discord.Embed(
            title="Reminder",
            description=row["message"],
            color=discord.Color(0x7128fc),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        if row["recurring"]:
            embed.set_footer(text=f"VoidWave • Reminder #{row['id']} • Repeats {recurrence_label(row['recurring'])}")
        else:
            embed.set_footer(text=f"VoidWave • Reminder #{row['id']}")

        if row["channel_id"]:
            channel = self.bot.get_channel(row["channel_id"])
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(row["channel_id"])
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    channel = None
            if channel is not None:
                if user is not None:
                    reason = await self._can_post_to(channel, user)
                    if reason is not None:
                        logger.info(
                            "Reminder #%s owner no longer allowed in <#%s>, falling back to DM: %s",
                            row["id"], row["channel_id"], reason,
                        )
                        channel = None
                if channel is not None:
                    try:
                        content = user.mention if user else None
                        await channel.send(content=content, embed=embed)
                        logger.info("Sent reminder #%s to %s in <#%s>", row["id"], row["user_id"], row["channel_id"])
                        return "delivered"
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as e:
                        logger.warning("Couldn't post reminder #%s to <#%s>, falling back to DM: %s", row["id"], row["channel_id"], e)

        if user is None:
            logger.warning("Reminder #%s dropped: no DM target and channel <#%s> unreachable", row["id"], row["channel_id"])
            return "dropped"

        try:
            await user.send(embed=embed)
            logger.info("Sent reminder #%s to %s", row["id"], row["user_id"])
            return "delivered"
        except discord.Forbidden:
            logger.warning("Couldn't DM reminder #%s to %s (DMs closed)", row["id"], row["user_id"])
            return "retry"
        except (discord.NotFound, discord.HTTPException) as e:
            logger.error("Failed to DM reminder #%s to %s: %s", row["id"], row["user_id"], e)
            return "dropped"


async def setup(bot):
    await bot.add_cog(ReminderCog(bot))
