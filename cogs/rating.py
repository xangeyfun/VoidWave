import discord
import datetime
import time
import logging

from utils import get_db

logger = logging.getLogger("cogs.rating")

RATING_CHANNEL_ID = 1540471117557403648


async def send_rating_prompt(bot, user_id, guild_name):
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
    except discord.NotFound:
        return

    embed = discord.Embed(
        title="⭐ How's your VoidWave experience?",
        description=(
            f"Hey {user.mention}! Thanks for using VoidWave, we're glad to have you. 🚀\n\n"
            "Could you rate your experience so far? It only takes a second and helps us improve. 💜"
        ),
        color=0x7128fc,
    )
    embed.set_footer(text="VoidWave • Thanks for the feedback!")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

    view = RatingView(bot, user_id, guild_name)
    try:
        await user.send(embed=embed, view=view)
        logger.info("Sent rating prompt to %s (%s)", user, user_id)
    except discord.Forbidden:
        logger.warning("Could not send rating prompt to %s (DMs closed)", user_id)
    except (discord.NotFound, discord.HTTPException) as e:
        logger.error("Failed to send rating prompt to %s: %s", user_id, e)


class RatingView(discord.ui.View):
    def __init__(self, bot, user_id, guild_name):
        super().__init__(timeout=600)
        self.bot = bot
        self.user_id = user_id
        self.guild_name = guild_name

    async def _rate(self, interaction: discord.Interaction, rating: int):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This rating prompt isn't for you.", ephemeral=True)
            return
        stars = "⭐" * rating
        embed = discord.Embed(
            description=f"Thanks! You rated VoidWave {stars}\n\nWould you like to tell us why?",
            color=0x7128fc,
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=embed,
            view=FeedbackView(self.bot, self.user_id, self.guild_name, rating),
        )
        save_rating(self.user_id, rating, "", self.guild_name)
        await forward_rating_to_channel(self.bot, interaction.user, rating, "", self.guild_name)

    @discord.ui.button(label="⭐", style=discord.ButtonStyle.secondary)
    async def one(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._rate(interaction, 1)

    @discord.ui.button(label="⭐", style=discord.ButtonStyle.secondary)
    async def two(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._rate(interaction, 2)

    @discord.ui.button(label="⭐", style=discord.ButtonStyle.secondary)
    async def three(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._rate(interaction, 3)

    @discord.ui.button(label="⭐", style=discord.ButtonStyle.secondary)
    async def four(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._rate(interaction, 4)

    @discord.ui.button(label="⭐", style=discord.ButtonStyle.secondary)
    async def five(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._rate(interaction, 5)


class FeedbackView(discord.ui.View):
    def __init__(self, bot, user_id, guild_name, rating):
        super().__init__(timeout=600)
        self.bot = bot
        self.user_id = user_id
        self.guild_name = guild_name
        self.rating = rating

    async def _finish(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This rating prompt isn't for you.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        embed = discord.Embed(description="Thanks for the feedback! 💜", color=0x7128fc)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Looks good", style=discord.ButtonStyle.primary)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction)

    @discord.ui.button(label="Add optional feedback", style=discord.ButtonStyle.secondary)
    async def add_feedback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This rating prompt isn't for you.", ephemeral=True)
            return
        await interaction.response.send_modal(FeedbackModal(self.bot, self.user_id, self.guild_name, self.rating, self))


class FeedbackModal(discord.ui.Modal, title="VoidWave Rating"):
    def __init__(self, bot, user_id, guild_name, rating, view):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.guild_name = guild_name
        self.rating = rating
        self.view_ref = view
        self.feedback_input = discord.ui.TextInput(
            label="Any additional feedback? (optional)",
            max_length=1000,
            style=discord.TextStyle.paragraph,
            required=False,
        )
        self.add_item(self.feedback_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This rating prompt isn't for you.", ephemeral=True)
            return
        feedback = (self.feedback_input.value or "").strip()
        update_feedback(self.user_id, feedback)
        for item in self.view_ref.children:
            item.disabled = True
        embed = discord.Embed(description="Thanks for the feedback! 💜", color=0x7128fc)
        await interaction.response.edit_message(embed=embed, view=self.view_ref)


def save_rating(user_id, rating, feedback, guild_name):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_ratings (user_id, rating, feedback, guild_name, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, rating, feedback, guild_name, int(time.time())),
        )
        cur.execute("UPDATE users SET rated = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error("Failed to save rating from %s: %s", user_id, e)
        return False
    finally:
        conn.close()


def update_feedback(user_id, feedback):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE user_ratings SET feedback=? WHERE id=(SELECT MAX(id) FROM user_ratings WHERE user_id=?)",
            (feedback, user_id),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to update feedback from %s: %s", user_id, e)
    finally:
        conn.close()


async def forward_rating_to_channel(bot, user, rating, feedback, guild_name):
    channel = bot.get_channel(RATING_CHANNEL_ID)
    if not channel:
        logger.error("Rating channel not found, dropped rating from %s (%s)", user, user.id)
        return

    stars = "⭐" * rating + "☆" * (5 - rating)
    embed = discord.Embed(
        title="⭐ New Rating",
        description=f"{stars} **{rating}/5**",
        color=0x7128fc,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=False)
    embed.add_field(name="Guild", value=guild_name or "DMs", inline=False)
    embed.add_field(name="Feedback", value=feedback or "No written feedback", inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="VoidWave • Auto-rating")

    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        logger.error("Failed to forward rating to rating channel: %s", e)


async def setup(bot):
    pass