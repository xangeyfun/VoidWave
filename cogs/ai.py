import asyncio
import logging
import sys
import tempfile
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils import (
    LLM_COOLDOWN,
    ai_processing,
    block_reply,
    get_db,
    get_llm_response,
    is_blocked,
    last_llm,
    llm_queue_size,
)

kirkify_lock = asyncio.Lock()
VOIDWAVE_COLOR = 0x7128fc
logger = logging.getLogger("cogs.ai")


class AICog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="ai", description="Chat with the bot's self hosted AI")
    @app_commands.describe(message="The message to send to the AI", stats="Show additional information about the AI response", hidden="Hide the command from others")
    async def ai(self, interaction: discord.Interaction, message: str, stats: bool = False, hidden: bool = False):
        global ai_processing

        if is_blocked(interaction.user.id, "ai"):
            await interaction.response.send_message(block_reply(interaction.user.id, "ai", "using VoidWave AI features"), ephemeral=True)
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

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="aitoggle", description="Turn AI replies on or off for yourself.")
    @app_commands.describe(enabled="Whether AI replies should be on (leave out to toggle)")
    async def aitoggle(self, interaction: discord.Interaction, enabled: bool = None):
        conn = get_db()
        try:
            cur = conn.cursor()
            row = cur.execute("SELECT ai_enabled FROM user_prefs WHERE user_id = ?", (interaction.user.id,)).fetchone()
            current = row[0] if row and row[0] is not None else 1
            new_value = enabled if enabled is not None else not current
            cur.execute(
                "INSERT INTO user_prefs (user_id, ai_enabled) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET ai_enabled = excluded.ai_enabled",
                (interaction.user.id, int(new_value)),
            )
            conn.commit()
        except Exception as e:
            logger.error("Failed to update AI preference for %s: %s", interaction.user.id, e)
            await interaction.response.send_message("Failed to update your AI preference. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        if new_value:
            await interaction.response.send_message(
                "AI replies are now **on** for you. Mention the bot or reply to it and VoidWave will respond. 💜",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "AI replies are now **off** for you. VoidWave will no longer send AI responses to your messages. "
                "Run `/aitoggle` anytime to turn them back on.",
                ephemeral=True,
            )

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="kirkify", description="Kirkify someone using AI.")
    @discord.app_commands.describe(image="The image to kirkify", hidden="Hide the command from others")
    async def kirkify(self, interaction: discord.Interaction, image: discord.Attachment, hidden: bool = False):
        if kirkify_lock.locked():
            await interaction.response.send_message("Kirkify is currently busy. Please try again later.", ephemeral=True)
            return

        if image.size > 10 * 1024 * 1024:  # 10 MB limit
            await interaction.response.send_message("The image is too large. Please upload an image smaller than 10 MB.", ephemeral=True)
            return

        async with kirkify_lock:
            await interaction.response.defer(ephemeral=hidden)

            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)

                input_path = tmp / "input.png"
                output_path = tmp / "output.png"

                await image.save(input_path)

                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "kirkify.py",
                    str(input_path),
                    str(output_path),
                    "--fast",
                    cwd=Path("third_party/kirkify.py"),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    logger.error("Kirkify timed out for user %s", interaction.user.id)
                    await interaction.followup.send("Kirkify took too long to process. Please try again later.", ephemeral=hidden)
                    return

                if process.returncode != 0:
                    logger.error("Kirkify failed: %s", stderr.decode())
                    await interaction.followup.send("Failed to kirkify the image. Please try again later.", ephemeral=hidden)
                    return

                embed = discord.Embed(title="Kirkified!", color=VOIDWAVE_COLOR)
                embed.set_image(url="attachment://output.png")

                await interaction.followup.send(embed=embed, file=discord.File(output_path, filename="output.png"), ephemeral=hidden)


async def setup(bot):
    await bot.add_cog(AICog(bot))
