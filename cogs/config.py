import datetime
from zoneinfo import ZoneInfo, available_timezones
import logging

from discord import app_commands
from discord.ext import commands
import discord
from utils import get_db, level_autocomplete, qotd_minutes, qotd_now, qotd_tz_label

logger = logging.getLogger("cogs.config")


COMMON_TIMEZONES = [
    "UTC",
    "Europe/London",
    "Europe/Amsterdam",
    "Europe/Berlin",
    "Europe/Paris",
    "Europe/Madrid",
    "Europe/Warsaw",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
    "Asia/Tokyo",
    "Asia/Kolkata",
    "Australia/Sydney",
]


CONFIG_LABELS = {
    "overview": "Overview",
    "leveling": "Leveling",
    "qotd": "Question of the Day",
}
CONFIG_EMOJIS = {
    "overview": "🏠",
    "leveling": "📊",
    "qotd": "❓",
}


class ConfigHelpSelect(discord.ui.Select):
    def __init__(self, placeholder, disabled_category, categories):
        self.disabled_category = disabled_category
        options = [
            discord.SelectOption(
                label=CONFIG_LABELS[cat],
                value=cat,
                emoji=CONFIG_EMOJIS[cat],
                default=(cat == disabled_category),
            )
            for cat in categories
        ]
        super().__init__(
            placeholder=f"{CONFIG_EMOJIS[disabled_category]} {CONFIG_LABELS[disabled_category]}",
            options=options,
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.author_id:
            await interaction.response.send_message("This help menu isn't for you.", ephemeral=True)
            return
        category = self.values[0]
        embed = self.view.cog._config_help_embed(category)
        for opt in self.options:
            opt.default = (opt.value == category)
        self.placeholder = f"{CONFIG_EMOJIS[category]} {CONFIG_LABELS[category]}"
        await interaction.response.edit_message(embed=embed, view=self.view)


class ConfigHelpView(discord.ui.View):
    def __init__(self, cog, select):
        super().__init__(timeout=120)
        self.cog = cog
        self.author_id = None
        self.add_item(select)
        close = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary, row=1)
        close.callback = self._close
        self.add_item(close)

    async def _close(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This help menu isn't for you.", ephemeral=True)
            return
        await interaction.response.edit_message(view=None)
        self.stop()


def _next_qotd_timestamp(guild_id=None) -> str:
    qotd_time = "16:00"
    tz_name = None
    if guild_id is not None:
        conn = get_db()
        try:
            cur = conn.cursor()
            row = cur.execute("SELECT qotd_time, qotd_tz FROM guild_settings WHERE guild_id = ?", (guild_id,)).fetchone()
            if row:
                if row["qotd_time"]:
                    qotd_time = row["qotd_time"]
                tz_name = row["qotd_tz"]
        except Exception as e:
            logger.error("Failed to fetch QOTD time for next-run preview: %s", e)
        finally:
            conn.close()

    minutes = qotd_minutes(qotd_time)
    if minutes is None:
        minutes = qotd_minutes("16:00")

    now = qotd_now(tz_name)
    target = now.replace(hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0)
    if now >= target:
        target += datetime.timedelta(days=1)
    return f"<t:{int(target.timestamp())}:R>"


async def _timezone_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    query = current.strip().lower()
    if not query:
        zones = COMMON_TIMEZONES
    else:
        all_zones = sorted(available_timezones())
        starts = [z for z in all_zones if z.lower().startswith(query)]
        contains = [z for z in all_zones if query in z.lower() and z not in starts]
        zones = (starts + contains)[:25]
    return [app_commands.Choice(name=z, value=z) for z in zones[:25]]


def _channel_issue(channel):
    """Return an error string when a stored channel is unusable, else None."""
    if channel is None:
        return "the channel was deleted, set it again"
    if not isinstance(channel, discord.TextChannel):
        return f"the stored id points at <#{channel.id}> which is not a text channel"
    return None


def _missing_perms(channel, member, names):
    perms = channel.permissions_for(member)
    return [n.replace("_", " ") for n in names if not getattr(perms, n)]


def _role_issue(role, top_role):
    """Return an error string when a stored role can't be assigned, else None."""
    if role is None:
        return "the role was deleted, set it again"
    if role >= top_role:
        return f"<@&{role.id}> sits above my highest role so it can never be assigned"
    return None


def _role_pingable(role, member):
    if role.is_default() or role.mentionable:
        return True
    return member.guild_permissions.mention_everyone


class ConfigCog(commands.Cog):
    config = discord.app_commands.Group(name="config", description="Admin commands for configuring the bot", default_permissions=discord.Permissions(administrator=True), allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=False), allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False))
    level = discord.app_commands.Group(name="level", description="Configure level system settings", parent=config)
    qotd = discord.app_commands.Group(name="qotd", description="Configure QOTD settings", parent=config)

    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        if isinstance(error, discord.app_commands.BotMissingPermissions):
            perms = ", ".join(f"**{p.replace('_', ' ').title()}**" for p in error.missing_permissions)
            msg = f"> I need {perms} permission to do that. Ask a server admin to grant it to me."
        elif isinstance(error, discord.app_commands.MissingPermissions):
            msg = "> You need **Administrator** permissions to use this command."
        else:
            return

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @config.command(name="view", description="View current configuration")
    async def view_config(self, interaction: discord.Interaction):
        try:
            conn = get_db()
            cur = conn.cursor()
            level_channel = cur.execute("SELECT level_channel_id, level_channel_enabled, vote_announce_enabled FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
            level_roles = cur.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ?", (interaction.guild.id,)).fetchall() # type: ignore
            qotd_channel = cur.execute("SELECT qotd_channel, qotd_enabled, delete_old_qotd, qotd_time, qotd_tz FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
        except Exception as e:
            logger.error("Failed to fetch config: %s", e)
            await interaction.response.send_message(f"Failed to fetch config. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        embed = discord.Embed(title="⚙️ Current Configuration", color=discord.Color(0x7128fc), timestamp=datetime.datetime.now(datetime.timezone.utc))

        if level_channel:
            channel = interaction.guild.get_channel(level_channel[0])
            channel_name = channel.mention if channel else "`No Channel Set`"
            embed.add_field(name="Level Up Channel", value=f"{channel_name} ({'Enabled' if level_channel[1] else 'Disabled'})", inline=False)
            if level_channel[2] is not None:
                embed.add_field(name="Vote Announcements", value=f"{'Enabled' if level_channel[2] else 'Disabled'}", inline=False)
        else:
            embed.add_field(name="Level Up Channel", value="Not set", inline=False)

        if qotd_channel:
            channel = interaction.guild.get_channel(qotd_channel[0])
            channel_name = channel.mention if channel else "`No Channel Set`"
            qotd_status = f"{channel_name} ({'Enabled' if qotd_channel[1] else 'Disabled'})"
            if qotd_channel[1]:
                time_display = f"{qotd_channel[3] or '16:00'} ({qotd_tz_label(qotd_channel[4])})"
                qotd_status += f"\nPosts daily at: `{time_display}`"
                qotd_status += f"\nNext QOTD: {_next_qotd_timestamp(interaction.guild.id)}"
            embed.add_field(name="QOTD Channel", value=qotd_status, inline=False)
            embed.add_field(name="Delete Old QOTD", value=f"{'Enabled' if qotd_channel[2] else 'Disabled'}", inline=False)
        else:
            embed.add_field(name="QOTD Channel", value="Not set", inline=False)

        if level_roles:
            roles_str = "\n".join([f"Level {row[0]}: <@&{row[1]}>" for row in level_roles])
            embed.add_field(name="Level Roles", value=roles_str, inline=False)
        else:
            embed.add_field(name="Level Roles", value="No level roles set", inline=False)

        embed.set_footer(text="Vote for 2x XP! /vote")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @config.command(name="test", description="Check that your configuration actually works")
    @app_commands.describe(send_test="Also send a test message into your configured channels")
    async def test_config(self, interaction: discord.Interaction, send_test: bool = False):
        await interaction.response.defer(ephemeral=True)

        conn = get_db()
        try:
            cur = conn.cursor()
            settings = cur.execute("SELECT level_channel_id, level_channel_enabled, vote_announce_enabled, qotd_enabled, qotd_channel, qotd_role_id, delete_old_qotd, qotd_time, qotd_tz FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
            level_roles = cur.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ?", (interaction.guild.id,)).fetchall() # type: ignore
        except Exception as e:
            logger.error("Failed to fetch config for test: %s", e)
            await interaction.followup.send("Failed to run the config test. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        me = interaction.guild.me
        icons = {"ok": "✅", "warn": "⚠️", "fail": "❌"}

        def line(status, text):
            return f"{icons[status]} {text}"

        level_results = []
        qotd_results = []

        # Leveling checks
        if not settings or not settings["level_channel_id"]:
            level_results.append(("warn", "No level up channel set. Fix with `/config level set_channel`"))
        elif not settings["level_channel_enabled"]:
            level_results.append(("warn", "Level announcements are turned off. Enable with `/config level toggle_channel true`"))
        else:
            channel = interaction.guild.get_channel(settings["level_channel_id"])
            issue = _channel_issue(channel)
            if issue:
                level_results.append(("fail", issue))
            else:
                missing = _missing_perms(channel, me, ["view_channel", "send_messages", "embed_links"])
                if missing:
                    level_results.append(("fail", f"I am missing {', '.join(missing)} in {channel.mention}"))
                else:
                    level_results.append(("ok", f"Level up channel {channel.mention} works"))

        if settings and settings["vote_announce_enabled"] is not None:
            if settings["vote_announce_enabled"] and settings["level_channel_enabled"]:
                level_results.append(("ok", "Vote announcements will post in the level up channel"))
            elif settings["vote_announce_enabled"] and not settings["level_channel_enabled"]:
                level_results.append(("warn", "Vote announcements are on but level up messages are off, so they won't post. Enable with `/config level toggle_channel true` or disable vote announcements with `/config level toggle_vote_announce false`"))
            else:
                level_results.append(("ok", "Vote announcements are disabled"))

        if level_roles:
            bad = 0
            for row in level_roles:
                role = interaction.guild.get_role(row["role_id"])
                issue = _role_issue(role, me.top_role)
                if issue:
                    bad += 1
                    level_results.append(("fail", f"Level {row['level']} reward: {issue}"))
            good = len(level_roles) - bad
            if good:
                level_results.append(("ok", f"{good} of {len(level_roles)} level roles assignable"))
        elif settings and settings["level_channel_enabled"]:
            level_results.append(("warn", "No level roles configured. Optional: `/config level add_role`"))

        # QOTD checks
        if not settings or not settings["qotd_enabled"]:
            qotd_results.append(("warn", "QOTD is disabled. Set it up with `/config qotd set_channel`, a role with `/config qotd set_role`, then enable with `/config qotd enable true`"))
        else:
            if not settings["qotd_channel"]:
                qotd_results.append(("fail", "QOTD enabled but no channel set. Fix with `/config qotd set_channel`"))
            else:
                channel = interaction.guild.get_channel(settings["qotd_channel"])
                issue = _channel_issue(channel)
                if issue:
                    qotd_results.append(("fail", issue))
                else:
                    needed = ["view_channel", "send_messages", "embed_links", "create_public_threads", "send_messages_in_threads"]
                    if settings["delete_old_qotd"]:
                        needed.append("manage_threads")
                    missing = _missing_perms(channel, me, needed)
                    if missing:
                        note = " (also needed to delete old posts)" if "manage threads" in missing and settings["delete_old_qotd"] else ""
                        qotd_results.append(("fail", f"I am missing {', '.join(missing)} in {channel.mention}{note}"))
                    else:
                        qotd_results.append(("ok", f"QOTD channel {channel.mention} works"))

            role = interaction.guild.get_role(settings["qotd_role_id"]) if settings["qotd_role_id"] else None
            if role is None:
                qotd_results.append(("warn", "No ping role set. Optional: `/config qotd set_role`"))
            elif not _role_pingable(role, me):
                qotd_results.append(("fail", f"<@&{role.id}> can't be pinged by me. Make it mentionable or grant me the Mention Everyone permission"))
            elif role.is_default():
                qotd_results.append(("ok", "@everyone will be pinged with each question"))
            else:
                qotd_results.append(("ok", f"Ping role {role.mention} is pingeable"))

            minutes = qotd_minutes(settings["qotd_time"])
            tz_issue = None
            if settings["qotd_tz"]:
                try:
                    ZoneInfo(settings["qotd_tz"])
                except Exception:
                    tz_issue = f"timezone `{settings['qotd_tz']}` is not valid. Run `/config qotd set_time` again and pick from the suggestions"
            if minutes is None:
                qotd_results.append(("fail", f"Stored time `{settings['qotd_time']}` is invalid. Run `/config qotd set_time` again"))
            elif tz_issue:
                qotd_results.append(("fail", tz_issue))
            else:
                qotd_results.append(("ok", f"Scheduled daily at `{settings['qotd_time'] or '16:00'}` ({qotd_tz_label(settings['qotd_tz'])})"))
                qotd_results.append(("ok", f"Next QOTD: {_next_qotd_timestamp(interaction.guild.id)}"))

        # Optional live sends
        if send_test and settings:
            level_channel = interaction.guild.get_channel(settings["level_channel_id"]) if settings["level_channel_id"] else None
            if isinstance(level_channel, discord.TextChannel) and settings["level_channel_enabled"]:
                try:
                    await level_channel.send(embed=discord.Embed(
                        title="🧪 Configuration test",
                        description="If you can read this, level up announcements will post here correctly.",
                        color=0x7128fc,
                    ))
                    level_results.append(("ok", f"Test message delivered to {level_channel.mention}"))
                except Exception as e:
                    level_results.append(("fail", f"Test message to {level_channel.mention} failed: {e}"))

            qotd_channel = interaction.guild.get_channel(settings["qotd_channel"]) if settings["qotd_channel"] else None
            if isinstance(qotd_channel, discord.TextChannel):
                try:
                    await qotd_channel.send(embed=discord.Embed(
                        title="🧪 Configuration test",
                        description="If you can read this, the daily question will post here correctly.",
                        color=0x7128fc,
                    ))
                    qotd_results.append(("ok", f"Test message delivered to {qotd_channel.mention}"))
                except Exception as e:
                    qotd_results.append(("fail", f"Test message to {qotd_channel.mention} failed: {e}"))

        all_results = level_results + qotd_results
        fails = sum(1 for s, _ in all_results if s == "fail")

        embed = discord.Embed(title="🧪 Config Test", color=discord.Color.red() if fails else 0x7128fc)
        embed.add_field(name="Leveling", value="\n".join(line(s, t) for s, t in level_results) or "Nothing configured yet", inline=False)
        embed.add_field(name="Question of the Day", value="\n".join(line(s, t) for s, t in qotd_results) or "Nothing configured yet", inline=False)
        embed.set_footer(text=f"{fails} problem(s) found. Fix them with the commands above." if fails else "Everything looks good!")
        await interaction.followup.send(embed=embed, ephemeral=True)

    def _config_help_embed(self, category):
        embeds = {
            "leveling": discord.Embed(
                title="📊 Leveling Configuration",
                description="Set up level-up announcements and auto-roles for your server.",
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Quick Setup",
                value="`/config auto level:true` - Create channel and enable announcements instantly",
                inline=False,
            ).add_field(
                name="Level Up Channel",
                value=(
                    "`/config level set_channel [channel]` - Set the level up message channel\n"
                    "`/config level toggle_channel [enabled]` - Enable or disable level up messages\n"
                    "`/config level toggle_vote_announce [enabled]` - Vote announcements in the level up channel"
                ),
                inline=False,
            ).add_field(
                name="Level Roles",
                value=(
                    "`/config level add_role [level] [role]` - Give a role on level up\n"
                    "`/config level remove_role [level]` - Remove a level role"
                ),
                inline=False,
            ),
            "qotd": discord.Embed(
                title="❓ QOTD Configuration",
                description="Set up a daily question with auto-threads and role pings.",
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Quick Setup",
                value="`/config auto qotd:true` - Create channel, role, and enable QOTD instantly",
                inline=False,
            ).add_field(
                name="QOTD Settings",
                value=(
                    "`/config qotd set_channel [channel]` - Set the QOTD channel\n"
                    "`/config qotd set_role [role]` - Role to ping with the QOTD\n"
                    "`/config qotd set_time [time] [timezone]` - When the QOTD posts (e.g. 18:30 Europe/Amsterdam)\n"
                    "`/config qotd enable [enabled]` - Enable or disable QOTD messages\n"
                    "`/config qotd delete_old [enabled]` - Delete old QOTD messages"
                ),
                inline=False,
            ),
            "overview": discord.Embed(
                title="⚙️ Configuration Help",
                description=(
                    "Select a feature below, or run `/config help topic:<feature>` to jump straight to it.\n"
                    "Full setup docs: <https://voidwave.xangey.dev/setup>"
                ),
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Quick Setup",
                value=(
                    "`/config auto [level] [qotd]` - Create channels, roles, and enable features\n"
                    "Example: `/config auto level:true qotd:true`"
                ),
                inline=False,
            ).add_field(
                name="General",
                value=(
                    "`/config view` - View current configuration\n"
                    "`/config test` - Health-check your settings\n"
                    "`/config help topic:Leveling` - Leveling commands\n"
                    "`/config help topic:Question of the Day` - QOTD commands"
                ),
                inline=False,
            ),
        }
        embed = embeds[category]
        embed.set_footer(text="Vote for 2x XP! /vote")
        return embed

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @config.command(name="help", description="Get help with configuration commands")
    @app_commands.describe(topic="Get help for a specific feature")
    @app_commands.choices(topic=[
        app_commands.Choice(name="Leveling", value="leveling"),
        app_commands.Choice(name="Question of the Day", value="qotd"),
    ])
    async def config_help(self, interaction: discord.Interaction, topic: str = None):
        category = topic or "overview"
        embed = self._config_help_embed(category)
        if topic is None:
            select = ConfigHelpSelect(
                placeholder=category,
                disabled_category=category,
                categories=["overview", "leveling", "qotd"],
            )
            view = ConfigHelpView(self, select)
            view.author_id = interaction.user.id
        else:
            view = None
        await interaction.response.send_message(embed=embed, ephemeral=True, view=view)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @config.command(name="auto", description="Automatically set up features for your server")
    @app_commands.describe(level="Set up leveling channel and enable announcements", qotd="Set up QOTD channel, role, and enable QOTD")
    async def auto_config(self, interaction: discord.Interaction, level: bool = True, qotd: bool = True):
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
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            "INSERT INTO guild_settings (guild_id, level_channel_id, level_channel_enabled) VALUES (?, ?, 1) ON CONFLICT(guild_id) DO UPDATE SET level_channel_id = excluded.level_channel_id, level_channel_enabled = 1",
                            (guild_obj.id, level_channel.id)
                        )
                        conn.commit()
                    finally:
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
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            "INSERT INTO guild_settings (guild_id, qotd_channel, qotd_role_id, qotd_enabled) VALUES (?, ?, ?, 1) ON CONFLICT(guild_id) DO UPDATE SET qotd_channel = excluded.qotd_channel, qotd_role_id = excluded.qotd_role_id, qotd_enabled = 1",
                            (guild_obj.id, qotd_channel.id, qotd_role.id)
                        )
                        conn.commit()
                    finally:
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
            msg = f"### All set up!\n**Created:**\n{items_text}\n\nBoth features are now enabled. Customize further with `/config help`."
            if qotd:
                msg += f"\n\nNext QOTD: {_next_qotd_timestamp(interaction.guild.id)}"
            await interaction.followup.send(msg, ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @level.command(name="set_channel", description="Set the channel for level up messages")
    @app_commands.describe(channel="The channel to send level up messages in")
    async def set_level_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        permissions = channel.permissions_for(interaction.guild.me)
        if not permissions.send_messages or not permissions.view_channel:
            await interaction.response.send_message(f"I don't have permission to send messages in {channel.mention}. Please update my permissions for that channel.", ephemeral=True)
            return

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO guild_settings (guild_id, level_channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET level_channel_id = excluded.level_channel_id", (interaction.guild.id, channel.id)) # type: ignore
            conn.commit()
        except Exception as e:
            logger.error("Failed to set level channel: %s", e)
        finally:
            conn.close()

        await interaction.response.send_message(f"Level up channel set to {channel.mention}\n\n**Don't forget:** Enable level-up messages with `/config level toggle_channel` to start announcing them!", ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @level.command(name="toggle_channel", description="Enable or disable level up messages")
    @app_commands.describe(enabled="Whether to enable level up messages")
    async def toggle_level_channel(self, interaction: discord.Interaction, enabled: bool):
        conn = get_db()
        try:
            cur = conn.cursor()
            channel = cur.execute("SELECT level_channel_id FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
            channel = self.bot.get_channel(channel[0]) if channel and channel[0] else None
            if not channel:
                await interaction.response.send_message("Please set a level up channel first using `/config level set_channel`", ephemeral=True)
                return

            cur.execute("INSERT INTO guild_settings (guild_id, level_channel_enabled) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET level_channel_enabled = excluded.level_channel_enabled", (interaction.guild.id, int(enabled))) # type: ignore
            conn.commit()

        except Exception as e:
            logger.error("Failed to toggle level channel: %s", e)
            await interaction.response.send_message(f"Failed to update level up message setting. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        await interaction.response.send_message(f"Level up messages have been **{'enabled' if enabled else 'disabled'}**", ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @level.command(name="toggle_vote_announce", description="Enable or disable vote announcements in the level up channel")
    @app_commands.describe(enabled="Whether to announce votes in the level up channel")
    async def toggle_vote_announce(self, interaction: discord.Interaction, enabled: bool):
        conn = get_db()
        try:
            cur = conn.cursor()
            row = cur.execute("SELECT level_channel_id, level_channel_enabled FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
            channel_id = row["level_channel_id"] if row else None
            if not channel_id:
                await interaction.response.send_message("Set a level up channel first using `/config level set_channel`, then enable messages with `/config level toggle_channel`. Vote announcements post there.", ephemeral=True)
                return

            cur.execute("INSERT INTO guild_settings (guild_id, vote_announce_enabled) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET vote_announce_enabled = excluded.vote_announce_enabled", (interaction.guild.id, int(enabled))) # type: ignore
            conn.commit()
        except Exception as e:
            logger.error("Failed to toggle vote announcements: %s", e)
            await interaction.response.send_message("Failed to update vote announcement setting. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        await interaction.response.send_message(f"Vote announcements have been **{'enabled' if enabled else 'disabled'}**" + ("" if enabled else " in your level up channel."), ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @discord.app_commands.checks.bot_has_permissions(manage_roles=True)
    @level.command(name="add_role", description="Add a role to be given on level up")
    @app_commands.describe(level="The level to give the role at", role="The role to give")
    async def add_level_role(self, interaction: discord.Interaction, level: int, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(f"I can't assign {role.mention} because it's higher than or equal to my highest role. Please move my role above it in the server settings.", ephemeral=True)
            return

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("INSERT OR REPLACE INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)", (interaction.guild.id, level, role.id)) # type: ignore
            conn.commit()
        except Exception as e:
            logger.error("Failed to add level role: %s", e)
        finally:
            conn.close()

        role_text = role.name if role.is_default() else role.mention
        await interaction.response.send_message(f"Role {role_text} will now be given at level {level}", ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @level.command(name="remove_role", description="Remove a level role")
    @app_commands.describe(level="The level of the role to remove")
    @app_commands.autocomplete(level=level_autocomplete)
    async def remove_level_role(self, interaction: discord.Interaction, level: int):
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (interaction.guild.id, level)) # type: ignore
            conn.commit()
        except Exception as e:
            logger.error("Failed to remove level role: %s", e)
        finally:
            conn.close()

        await interaction.response.send_message(f"Level role for level {level} has been removed", ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @qotd.command(name="set_channel", description="Set the channel for QOTD")
    @app_commands.describe(channel="The channel to send the QOTD in")
    async def set_qotd_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        permissions = channel.permissions_for(interaction.guild.me)
        if not permissions.send_messages or not permissions.view_channel:
            await interaction.response.send_message(f"I don't have permission to send messages in {channel.mention}. Please update my permissions for that channel.", ephemeral=True)
            return

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO guild_settings (guild_id, qotd_channel) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET qotd_channel = excluded.qotd_channel", (interaction.guild.id, channel.id)) # type: ignore
            conn.commit()

            role_row = cur.execute("SELECT qotd_role_id FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone()
            has_role = role_row and role_row[0]

        except Exception as e:
            logger.error("Failed to set QOTD channel: %s", e)
            await interaction.response.send_message(f"Failed to set QOTD channel. Please try again later.", ephemeral=True)
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
    @qotd.command(name="set_time", description="Set the time of day the QOTD is posted")
    @app_commands.describe(time="Time of day in 24-hour HH:MM format", timezone="Timezone for the time, e.g. Europe/Amsterdam (defaults to server time)")
    @app_commands.autocomplete(timezone=_timezone_autocomplete)
    async def set_qotd_time(self, interaction: discord.Interaction, time: str, timezone: str = None):
        minutes = qotd_minutes(time)
        if minutes is None:
            await interaction.response.send_message("Invalid time. Use 24-hour HH:MM format, e.g. `18:30`.", ephemeral=True)
            return

        tz_name = None
        if timezone:
            try:
                ZoneInfo(timezone)
                tz_name = timezone
            except Exception:
                await interaction.response.send_message(f"Unknown timezone `{timezone}`. Type part of a nearby city and pick from the suggestions, e.g. `Europe/Amsterdam`.", ephemeral=True)
                return

        qotd_time = f"{minutes // 60:02d}:{minutes % 60:02d}"

        conn = get_db()
        try:
            cur = conn.cursor()
            existing = cur.execute("SELECT qotd_time, qotd_tz FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
            changed = not existing or existing["qotd_time"] != qotd_time or existing["qotd_tz"] != tz_name
            if changed:
                cur.execute("INSERT INTO guild_settings (guild_id, qotd_time, qotd_tz, last_qotd_date) VALUES (?, ?, ?, NULL) ON CONFLICT(guild_id) DO UPDATE SET qotd_time = excluded.qotd_time, qotd_tz = excluded.qotd_tz, last_qotd_date = NULL", (interaction.guild.id, qotd_time, tz_name))
            else:
                cur.execute("INSERT INTO guild_settings (guild_id, qotd_time, qotd_tz) VALUES (?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET qotd_time = excluded.qotd_time, qotd_tz = excluded.qotd_tz", (interaction.guild.id, qotd_time, tz_name)) # type: ignore
            conn.commit()
        except Exception as e:
            logger.error("Failed to set QOTD time: %s", e)
            await interaction.response.send_message(f"Failed to set QOTD time. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        msg = f"QOTD will be posted daily at `{qotd_time}` ({qotd_tz_label(tz_name)})"
        if changed and existing is not None:
            msg += "\n\nThe schedule changed, so the next QOTD posts at this new time even if one already went out today."
        msg += f"\n\nNext QOTD: {_next_qotd_timestamp(interaction.guild.id)}"
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @qotd.command(name="enable", description="Enable or disable the QOTD")
    @app_commands.describe(enabled="Whether to enable the QOTD")
    async def enable_qotd(self, interaction: discord.Interaction, enabled: bool):
        conn = get_db()
        try:
            cur = conn.cursor()
            channel = cur.execute("SELECT qotd_channel FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
            channel = self.bot.get_channel(channel[0]) if channel and channel[0] else None
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
            logger.error("Failed to set QOTD enabled: %s", e)
            await interaction.response.send_message(f"Failed to update QOTD setting. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        msg = f"QOTD has been {'enabled' if enabled else 'disabled'}"
        if enabled:
            msg += f"\n\nNext QOTD: {_next_qotd_timestamp(interaction.guild.id)}"
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
    @qotd.command(name="set_role", description="Set a role to be pinged with the QOTD")
    @app_commands.describe(role="The role to ping with the QOTD")
    async def set_qotd_role(self, interaction: discord.Interaction, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(f"I can't use {role.mention} because it's higher than or equal to my highest role. Please move my role above it in the server settings.", ephemeral=True)
            return

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO guild_settings (guild_id, qotd_role_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET qotd_role_id = excluded.qotd_role_id", (interaction.guild.id, role.id)) # type: ignore
            conn.commit()

        except Exception as e:
            logger.error("Failed to set QOTD role: %s", e)
            await interaction.response.send_message(f"Failed to set QOTD role. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        role_text = role.name if role.is_default() else role.mention
        msg = f"QOTD role set to {role_text}"
        channel_row = None
        conn2 = get_db()
        try:
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
    @qotd.command(name="delete_old", description="Enable or disable deletion of old QOTD messages")
    @app_commands.describe(enabled="Whether to delete old QOTD messages")
    async def delete_old_qotd(self, interaction: discord.Interaction, enabled: bool):
        conn = get_db()
        try:
            cur = conn.cursor()
            channel = cur.execute("SELECT qotd_channel FROM guild_settings WHERE guild_id = ?", (interaction.guild.id,)).fetchone() # type: ignore
            channel = self.bot.get_channel(channel[0]) if channel and channel[0] else None
            if not channel:
                await interaction.response.send_message("Please set a QOTD channel first using `/config qotd set_channel`", ephemeral=True)
                return

            cur.execute("INSERT INTO guild_settings (guild_id, delete_old_qotd) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET delete_old_qotd = excluded.delete_old_qotd", (interaction.guild.id, int(enabled))) # type: ignore
            conn.commit()

        except Exception as e:
            logger.error("Failed to set delete old QOTD: %s", e)
            await interaction.response.send_message(f"Failed to update delete old QOTD setting. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        await interaction.response.send_message(f"Delete old QOTD messages has been {'enabled' if enabled else 'disabled'}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
