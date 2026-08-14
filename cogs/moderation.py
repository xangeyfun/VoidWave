from discord import app_commands
from discord.ext import commands
import discord


class ModerationCog(commands.Cog):
    moderation = discord.app_commands.Group(
        name="moderation",
        description="Moderation commands",
        allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=False),
        allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False),
        default_permissions=discord.Permissions(manage_messages=True),
    )

    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        if isinstance(error, discord.app_commands.MissingPermissions):
            msg = "> You need **Manage Messages** permission to use this command."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

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


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
