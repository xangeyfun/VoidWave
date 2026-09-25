import asyncio
import io
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
    resolve_hidden,
)

KIRKIFY_QUEUE_MAX = 5
KIRKIFY_WAIT_TIMEOUT = 14 * 60
KIRKIFY_ESTIMATE_FALLBACK = 30.0
VOIDWAVE_COLOR = 0x7128fc
logger = logging.getLogger("cogs.ai")


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    if m == 0:
        return f"about {s}s"
    if s == 0:
        return f"about {m}m"
    return f"about {m}m {s}s"


class AICog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.kirkify_queue = asyncio.Queue(maxsize=KIRKIFY_QUEUE_MAX)
        self._kirkify_worker_task = None
        self._kirkify_seq = 0
        self._kirkify_done = 0
        self._kirkify_times = []

    async def cog_load(self):
        self._kirkify_worker_task = asyncio.create_task(self._kirkify_worker())

    async def cog_unload(self):
        if self._kirkify_worker_task:
            self._kirkify_worker_task.cancel()

    async def _kirkify_worker(self):
        while True:
            entry = await self.kirkify_queue.get()
            try:
                fut, interaction, image, hidden = entry
                if fut.done():
                    continue
                try:
                    started = time.monotonic()
                    output_data = await self._run_kirkify(interaction, image, hidden)
                    self._kirkify_times.append(time.monotonic() - started)
                    self._kirkify_times = self._kirkify_times[-8:]
                    if not fut.done():
                        fut.set_result(output_data)
                except Exception as e:
                    logger.error("Kirkify failed for user %s: %s", interaction.user.id, e)
                    if not fut.done():
                        fut.set_exception(e)
            finally:
                self._kirkify_done += 1
                self.kirkify_queue.task_done()

    async def _run_kirkify(self, interaction, image, hidden):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            input_path = tmp / "input.png"
            output_path = tmp / "output.png"
            await image.save(input_path)

            try:
                import cv2
            except ImportError:
                cv2 = None

            if cv2 is not None:
                img = cv2.imread(str(input_path))
                if img is None:
                    raise ValueError(
                        "That file isn't a readable image. Try a PNG, JPG, GIF, or WebP instead."
                    )
                cv2.imwrite(str(input_path), img)

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
                raise TimeoutError("kirkify timed out")

            if process.returncode != 0:
                err = stderr.decode(errors="replace").strip()
                detail = " | ".join(err.splitlines()[-6:]) if err else f"exit code {process.returncode}"
                raise RuntimeError(f"kirkify subprocess failed: {detail}")

            data = output_path.read_bytes()
            logger.info("Kirkified %s request from %s", image.id, interaction.user.id)
            return data

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="ai", description="Chat with the bot's self hosted AI")
    @app_commands.describe(message="The message to send to the AI", stats="Show additional information about the AI response", hidden="Hide the command from others")
    async def ai(self, interaction: discord.Interaction, message: str, stats: bool = False, hidden: bool | None = None):
        hidden = resolve_hidden(interaction.user.id, hidden)
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
    async def kirkify(self, interaction: discord.Interaction, image: discord.Attachment, hidden: bool | None = None):
        hidden = resolve_hidden(interaction.user.id, hidden)
        if image.size > 10 * 1024 * 1024:  # 10 MB limit
            await interaction.response.send_message("The image is too large. Please upload an image smaller than 10 MB.", ephemeral=True)
            return

        if self.kirkify_queue.full():
            await interaction.response.send_message(
                "Kirkify's queue is full right now. Please try again in a bit.", ephemeral=True
            )
            return

        if not self._kirkify_worker_task or self._kirkify_worker_task.done():
            self._kirkify_worker_task = asyncio.create_task(self._kirkify_worker())

        fut = asyncio.get_running_loop().create_future()
        seq = self._kirkify_seq
        self._kirkify_seq += 1
        await self.kirkify_queue.put((fut, interaction, image, hidden))

        await interaction.response.defer(ephemeral=hidden)

        ahead = max(0, seq - self._kirkify_done)
        if ahead == 0:
            status = "Processing your image now; give it a few seconds."
        else:
            if self._kirkify_times:
                estimate = (sum(self._kirkify_times) / len(self._kirkify_times)) * ahead
            else:
                estimate = KIRKIFY_ESTIMATE_FALLBACK * ahead
            status = (
                f"Queued! There {'is' if ahead == 1 else 'are'} **{ahead}** "
                f"{('request' if ahead == 1 else 'requests')} ahead of you "
                f"(est. wait {_fmt_duration(estimate)}). I'll post the result here when it's done."
            )
        thinking = await interaction.followup.send(status, wait=True)

        try:
            output_data = await asyncio.wait_for(fut, timeout=KIRKIFY_WAIT_TIMEOUT)
        except asyncio.TimeoutError:
            await thinking.edit(content="Kirkify is taking longer than expected. Please try again later.")
            return
        except Exception:
            await thinking.edit(
                content=(
                    "Failed to kirkify that image. Make sure it's a PNG, JPG, GIF, or WebP and faces are visible. "
                "Please try again later."
                )
            )
            return

        embed = discord.Embed(title="Kirkified!", color=VOIDWAVE_COLOR)
        embed.set_image(url="attachment://output.png")
        await thinking.edit(
            content=None,
            embed=embed,
            attachments=[discord.File(io.BytesIO(output_data), filename="output.png")],
        )


async def setup(bot):
    await bot.add_cog(AICog(bot))
