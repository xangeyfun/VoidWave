from discord import app_commands
from discord.ext import commands
import discord
import time
from utils import get_llm_response, last_llm, llm_queue_size, ai_processing, LLM_COOLDOWN, is_blocked


class AICog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="ai", description="Chat with the bot's AI (powered by Llama 3.2)")
    @app_commands.describe(message="The message to send to the AI", stats="Show additional information about the AI response", hidden="Hide the command from others")
    async def ai(self, interaction: discord.Interaction, message: str, stats: bool = False, hidden: bool = False):
        global ai_processing

        if is_blocked(interaction.user.id, "ai"):
            await interaction.response.send_message("You are blocked from using VoidWave AI features.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=hidden)

        if interaction.user.id in last_llm and time.time() - last_llm[interaction.user.id] < LLM_COOLDOWN and interaction.user.id != 996771607630585856:
            await interaction.followup.send(f"Slow down! VoidWave needs a breather. Try again in `{LLM_COOLDOWN - (time.time() - last_llm[interaction.user.id]):.1f} seconds.`", ephemeral=True)
            return

        if len(llm_queue_size) > 0 or ai_processing:
            await interaction.followup.send(f"VoidWave is busy right now. Try again in a bit! (Queue: `{len(llm_queue_size) + (1 if ai_processing else 0)}`)", ephemeral=True)
            return

        ai_processing = True
        try:
            reply, info = await get_llm_response(message, interaction.user.name, interaction.user.id)

            if stats:
                reply += f"\n> {info}"

            await interaction.followup.send(reply, ephemeral=hidden, allowed_mentions=discord.AllowedMentions.none())
        finally:
            ai_processing = False


async def setup(bot):
    await bot.add_cog(AICog(bot))
