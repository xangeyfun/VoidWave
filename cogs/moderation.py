from discord import app_commands
from discord.ext import commands
import discord
import datetime


class ModerationCog(commands.Cog):
    moderation = discord.app_commands.Group(
        name="moderation",
        description="Moderation commands",
        allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=False),
        allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False),
        default_permissions=discord.Permissions(manage_messages=True),
    )

    role = discord.app_commands.Group(name="role", description="Manage a member's roles", parent=moderation)

    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        if isinstance(error, discord.app_commands.MissingPermissions):
            perms = ", ".join(f"**{p.replace('_', ' ').title()}**" for p in error.missing_permissions)
            msg = f"> You need {perms} permission to use this command."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

    def _hierarchy_error(self, interaction: discord.Interaction, member: discord.Member, action: str) -> str | None:
        if member == interaction.guild.owner:
            return f"I can't {action} the server owner."
        if member == interaction.guild.me:
            return f"I can't {action} myself."
        if member.top_role >= interaction.guild.me.top_role:
            return f"I can't {action} {member.mention} because their highest role is equal to or above mine."
        if member.top_role >= interaction.user.top_role and member != interaction.user:
            return f"You can't {action} {member.mention} because their highest role is equal to or above yours."
        return None

    def _role_error(self, interaction: discord.Interaction, role: discord.Role, action: str) -> str | None:
        if role.is_default():
            return "I can't manage the @everyone role."
        if role >= interaction.guild.me.top_role:
            return f"I can't {action} {role.mention} because it's equal to or above my highest role."
        if role >= interaction.user.top_role:
            return f"You can't {action} {role.mention} because it's equal to or above your highest role."
        return None

    @discord.app_commands.checks.has_permissions(manage_messages=True)
    @moderation.command(name="purge", description="Bulk delete messages")
    @app_commands.describe(amount="Number of messages to delete (1-100)", user="Only delete this user's messages", hidden="Hide the command from others")
    async def purge(self, interaction: discord.Interaction, amount: int, user: discord.Member | None = None, hidden: bool = False):
        await interaction.response.defer(ephemeral=hidden)

        amount = max(1, min(amount, 100))

        def check(msg):
            if user is not None:
                return msg.author.id == user.id
            return True

        try:
            deleted = await interaction.channel.purge(limit=amount, check=check)  # type: ignore
            await interaction.followup.send(f"Deleted **{len(deleted)}** message{'s' if len(deleted) != 1 else ''}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to delete messages here.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Something went wrong...\n> {e}", ephemeral=True)

    @discord.app_commands.checks.has_permissions(kick_members=True)
    @moderation.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(member="The member to kick", reason="Reason for the kick", hidden="Hide the command from others")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str | None = None, hidden: bool = False):
        err = self._hierarchy_error(interaction, member, "kick")
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=hidden)
        await member.kick(reason=reason)
        await interaction.followup.send(f"Kicked **{member}**.{f' Reason: {reason}' if reason else ''}", ephemeral=True)

    @discord.app_commands.checks.has_permissions(ban_members=True)
    @moderation.command(name="ban", description="Ban a member from the server")
    @app_commands.describe(member="The member to ban", delete_days="Delete recent messages (0-7)", reason="Reason for the ban", hidden="Hide the command from others")
    async def ban(self, interaction: discord.Interaction, member: discord.Member, delete_days: int = 0, reason: str | None = None, hidden: bool = False):
        err = self._hierarchy_error(interaction, member, "ban")
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        delete_days = max(0, min(delete_days, 7))
        await interaction.response.defer(ephemeral=hidden)
        await member.ban(reason=reason, delete_message_seconds=delete_days * 86400)
        await interaction.followup.send(f"Banned **{member}**.{f' Reason: {reason}' if reason else ''}", ephemeral=True)

    @discord.app_commands.checks.has_permissions(ban_members=True)
    @moderation.command(name="unban", description="Unban a user by ID")
    @app_commands.describe(user="The user to unban", reason="Reason for the unban", hidden="Hide the command from others")
    async def unban(self, interaction: discord.Interaction, user: discord.User, reason: str | None = None, hidden: bool = False):
        await interaction.response.defer(ephemeral=hidden)
        try:
            await interaction.guild.unban(user, reason=reason)  # type: ignore
            await interaction.followup.send(f"Unbanned **{user}**.{f' Reason: {reason}' if reason else ''}", ephemeral=True)
        except discord.NotFound:
            await interaction.followup.send(f"**{user}** is not banned.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to unban members.", ephemeral=True)

    @discord.app_commands.checks.has_permissions(moderate_members=True)
    @moderation.command(name="timeout", description="Timeout a member for a set duration")
    @app_commands.describe(member="The member to timeout", amount="How long the timeout lasts", unit="Unit for the timeout duration", reason="Reason for the timeout", hidden="Hide the command from others")
    @app_commands.choices(unit=[
        app_commands.Choice(name="minutes", value="minutes"),
        app_commands.Choice(name="hours", value="hours"),
        app_commands.Choice(name="days", value="days"),
    ])
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, amount: int, unit: str = "minutes", reason: str | None = None, hidden: bool = False):
        err = self._hierarchy_error(interaction, member, "timeout")
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        factors = {"minutes": 1, "hours": 60, "days": 1440}
        minutes = max(1, min(amount * factors[unit], 40320))
        await interaction.response.defer(ephemeral=hidden)
        await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
        await interaction.followup.send(f"Timed out **{member}** for **{amount} {unit}**.{f' Reason: {reason}' if reason else ''}", ephemeral=True)

    @discord.app_commands.checks.has_permissions(manage_channels=True)
    @moderation.command(name="slowmode", description="Set or clear slowmode on a channel")
    @app_commands.describe(seconds="Slowmode in seconds (0 to clear, max 21600)", channel="The channel to change (defaults to this one)", hidden="Hide the command from others")
    async def slowmode(self, interaction: discord.Interaction, seconds: int, channel: discord.TextChannel | None = None, hidden: bool = False):
        channel = channel or interaction.channel  # type: ignore
        seconds = max(0, min(seconds, 21600))
        await interaction.response.defer(ephemeral=hidden)
        await channel.edit(slowmode_delay=seconds)
        if seconds:
            await interaction.followup.send(f"Set slowmode to **{seconds} seconds** in {channel.mention}.", ephemeral=True)
        else:
            await interaction.followup.send(f"Cleared slowmode in {channel.mention}.", ephemeral=True)

    @discord.app_commands.checks.has_permissions(manage_channels=True)
    @moderation.command(name="lock", description="Lock a channel so members can't send messages")
    @app_commands.describe(channel="The channel to lock (defaults to this one)", reason="Reason for locking", hidden="Hide the command from others")
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None, reason: str | None = None, hidden: bool = False):
        channel = channel or interaction.channel  # type: ignore
        await interaction.response.defer(ephemeral=hidden)
        await channel.set_permissions(interaction.guild.default_role, send_messages=False)  # type: ignore
        await interaction.followup.send(f"Locked {channel.mention}.{f' Reason: {reason}' if reason else ''}", ephemeral=True)

    @discord.app_commands.checks.has_permissions(manage_channels=True)
    @moderation.command(name="unlock", description="Unlock a previously locked channel")
    @app_commands.describe(channel="The channel to unlock (defaults to this one)", hidden="Hide the command from others")
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None, hidden: bool = False):
        channel = channel or interaction.channel  # type: ignore
        await interaction.response.defer(ephemeral=hidden)
        await channel.set_permissions(interaction.guild.default_role, send_messages=None)  # type: ignore
        await interaction.followup.send(f"Unlocked {channel.mention}.", ephemeral=True)

    @discord.app_commands.checks.has_permissions(manage_roles=True)
    @role.command(name="add", description="Add a role to a member")
    @app_commands.describe(member="The member to give the role to", role="The role to add", hidden="Hide the command from others")
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role, hidden: bool = False):
        err = self._role_error(interaction, role, "give")
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=hidden)
        if role in member.roles:
            await interaction.followup.send(f"{member.mention} already has {role.mention}.", ephemeral=True)
            return
        await member.add_roles(role, reason=f"Added by {interaction.user}")
        await interaction.followup.send(f"Gave {role.mention} to **{member}**.", ephemeral=True)

    @discord.app_commands.checks.has_permissions(manage_roles=True)
    @role.command(name="remove", description="Remove a role from a member")
    @app_commands.describe(member="The member to remove the role from", role="The role to remove", hidden="Hide the command from others")
    async def role_remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role, hidden: bool = False):
        err = self._role_error(interaction, role, "remove")
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=hidden)
        if role not in member.roles:
            await interaction.followup.send(f"{member.mention} doesn't have {role.mention}.", ephemeral=True)
            return
        await member.remove_roles(role, reason=f"Removed by {interaction.user}")
        await interaction.followup.send(f"Removed {role.mention} from **{member}**.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
