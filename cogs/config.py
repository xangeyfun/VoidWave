import datetime

from discord import app_commands
from discord.ext import commands
import discord
from utils import get_db, date, level_autocomplete


def _next_qotd_timestamp() -> str:
    now = datetime.datetime.now()
    target = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now >= target:
        target += datetime.timedelta(days=1)
    return f"<t:{int(target.timestamp())}:R>"


class ConfigCog(commands.Cog):
    config = discord.app_commands.Group(name="config", description="Admin commands for configuring the bot", allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=False), allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False))
    level = discord.app_commands.Group(name="level", description="Configure level system settings", parent=config)
    qotd = discord.app_commands.Group(name="qotd", description="Configure QOTD settings", parent=config)

    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        if isinstance(error, discord.app_commands.MissingPermissions):
            msg = "> You need **Administrator** permissions to use this command."
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
            qotd_status = f"{channel_name} ({'Enabled' if qotd_channel[1] else 'Disabled'})"
            if qotd_channel[1]:
                qotd_status += f"\nNext QOTD: {_next_qotd_timestamp()}"
            embed.add_field(name="QOTD Channel", value=qotd_status, inline=False)
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
    @config.command(name="help", description="Get help with configuration commands")
    @app_commands.describe(topic="Get help for a specific feature")
    @app_commands.choices(topic=[
        app_commands.Choice(name="Leveling", value="leveling"),
        app_commands.Choice(name="Question of the Day", value="qotd"),
    ])
    async def config_help(self, interaction: discord.Interaction, topic: str = None):
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
                msg += f"\n\nNext QOTD: {_next_qotd_timestamp()}"
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
            print(f"{date()} ERROR  Failed to set level channel: {e}")
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
            print(f"{date()} ERROR  Failed to toggle level channel: {e}")
            await interaction.response.send_message(f"Failed to update level up message setting. Please try again later.\n> {e}", ephemeral=True)
            return
        finally:
            conn.close()

        await interaction.response.send_message(f"Level up messages have been **{'enabled' if enabled else 'disabled'}**", ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.checks.has_permissions(administrator=True)
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
            print(f"{date()} ERROR  Failed to add level role: {e}")
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
            print(f"{date()} ERROR  Failed to remove level role: {e}")
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
            print(f"{date()} ERROR  Failed to set QOTD enabled: {e}")
            await interaction.response.send_message(f"Failed to update QOTD setting. Please try again later.\n> {e}", ephemeral=True)
            return
        finally:
            conn.close()

        msg = f"QOTD has been {'enabled' if enabled else 'disabled'}"
        if enabled:
            msg += f"\n\nNext QOTD: {_next_qotd_timestamp()}"
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
            print(f"{date()} ERROR  Failed to set QOTD role: {e}")
            await interaction.response.send_message(f"Failed to set QOTD role. Please try again later.\n> {e}", ephemeral=True)
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
            print(f"{date()} ERROR  Failed to set delete old QOTD: {e}")
            await interaction.response.send_message(f"Failed to update delete old QOTD setting. Please try again later.\n> {e}", ephemeral=True)
            return
        finally:
            conn.close()

        await interaction.response.send_message(f"Delete old QOTD messages has been {'enabled' if enabled else 'disabled'}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
