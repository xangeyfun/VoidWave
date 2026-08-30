from discord import app_commands
from discord.ext import commands
import discord
import asyncio

from akinator import AsyncAkinator


VOIDWAVE_COLOR = 0x7128fc

THEME_MAP = {
    "characters": "c",
    "objects": "o",
    "animals": "a",
}

ANSWER_LABELS = {
    "yes": "Yes",
    "no": "No",
    "idk": "Don't know",
    "probably": "Probably",
    "probably_not": "Probably not",
}

ANSWER_VALUES = {
    "yes": "yes",
    "no": "no",
    "idk": "idk",
    "probably": "probably",
    "probably_not": "probably not",
}

ANSWER_EMOJIS = {
    "yes": "✅",
    "no": "❌",
    "idk": "❓",
    "probably": "🤔",
    "probably_not": "🙄",
}

# Strictly only one active game per user to avoid sessions leaking.
_ACTIVE_GAMES: dict[int, "AkinatorView"] = {}


def _theme_display(theme_key: str) -> str:
    return {"c": "Characters", "o": "Objects", "a": "Animals"}[theme_key]


async def _create_game(theme_key: str, attempts: int = 4, delay: float = 1.5):
    last_error = None
    for i in range(attempts):
        try:
            aki = AsyncAkinator()
            await aki.start_game(language="en", child_mode=True, theme=theme_key)
            return aki, None
        except Exception as e:
            last_error = e
            if i < attempts - 1:
                await asyncio.sleep(delay)
    return None, last_error


class AkinatorView(discord.ui.View):
    def __init__(self, user: discord.User, aki: AsyncAkinator, theme_key: str):
        super().__init__(timeout=180)
        self.user = user
        self.aki = aki
        self.theme_key = theme_key
        self.message = None
        self.busy = False

    def _question_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🧠 Akinator · {_theme_display(self.theme_key)}",
            description=f"**{self.aki.question}**",
            color=discord.Color(VOIDWAVE_COLOR),
        )
        embed.set_footer(text=f"Step {self.aki.step} • Vote for 2x XP! /vote")
        return embed

    def _guess_embed(self) -> discord.Embed:
        description = f"**{self.aki.name_proposition}**"
        desc = (self.aki.description_proposition or "").strip()
        if desc and desc != "-":
            description += f"\n> {desc}"
        embed = discord.Embed(
            title="🎉 I think I got it!",
            description=description,
            color=discord.Color(VOIDWAVE_COLOR),
        )
        if getattr(self.aki, "photo", None):
            embed.set_thumbnail(url=self.aki.photo)
        embed.set_footer(text=f"{self.aki.progression:.0f}% sure • Vote for 2x XP! /vote")
        return embed

    async def _guess(self, interaction: discord.Interaction):
        self.clear_items()
        self.add_item(_AkinatorGuessButton(self, guess=True))
        self.add_item(_AkinatorGuessButton(self, guess=False))
        self.add_item(_AkinatorEndButton(self))
        await interaction.edit_original_response(embed=self._guess_embed(), view=self)

    async def _answer(self, interaction: discord.Interaction, answer_key: str):
        if self.busy:
            await interaction.response.defer()
            return
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This isn't your game! Start your own game with **`/akinator`**", ephemeral=True)
            return

        self.busy = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        try:
            await self.aki.answer(ANSWER_VALUES[answer_key])
        except Exception as e:
            await self._disable_all(interaction)
            embed = discord.Embed(
                title="⚠️ Akinator error",
                description=f"Something went wrong talking to Akinator.\n> {e}",
                color=discord.Color.dark_red(),
            )
            await interaction.edit_original_response(embed=embed, view=None)
            _ACTIVE_GAMES.pop(self.user.id, None)
            return

        self.busy = False

        if self.aki.win:
            await self._guess(interaction)
        else:
            for child in self.children:
                child.disabled = False
            await interaction.edit_original_response(embed=self._question_embed(), view=self)

    async def _back(self, interaction: discord.Interaction):
        if self.busy:
            await interaction.response.defer()
            return
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This isn't your game! Start your own game with **`/akinator`**", ephemeral=True)
            return
        if self.aki.step == 0:
            await interaction.response.send_message("You can't go back any further!", ephemeral=True)
            return

        self.busy = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        try:
            await self.aki.back()
        except Exception as e:
            self.busy = False
            for child in self.children:
                child.disabled = False
            embed = discord.Embed(
                title="⚠️ Akinator error",
                description=f"Couldn't go back.\n> {e}",
                color=discord.Color.dark_red(),
            )
            embed.set_footer(text="Vote for 2x XP! /vote")
            await interaction.edit_original_response(embed=embed, view=self)
            return

        self.busy = False
        for child in self.children:
            child.disabled = False
        await interaction.edit_original_response(embed=self._question_embed(), view=self)

    async def _on_guess(self, interaction: discord.Interaction, correct: bool):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This isn't your game! Start your own game with **`/akinator`**", ephemeral=True)
            return

        self.busy = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        try:
            await (self.aki.choose() if correct else self.aki.exclude())
        except Exception as e:
            embed = discord.Embed(
                title="⚠️ Akinator error",
                description=f"Something went wrong recording your answer.\n> {e}",
                color=discord.Color.dark_red(),
            )
            await interaction.edit_original_response(embed=embed, view=None)
            _ACTIVE_GAMES.pop(self.user.id, None)
            return

        self.busy = False

        if correct or (not correct and self.aki.finished):
            embed = discord.Embed(
                title="⭐ Akinator",
                description=f"**{self.aki.question}**",
                color=discord.Color(VOIDWAVE_COLOR),
            )
            if not correct:
                embed.description = f"You defeated me!\n\n**{self.aki.question}**"
            embed.set_footer(text="Vote for 2x XP! /vote")
            await interaction.edit_original_response(embed=embed, view=None)
            _ACTIVE_GAMES.pop(self.user.id, None)
        else:
            self.clear_items()
            self._build_answer_row()
            self._build_back_row()
            await interaction.edit_original_response(embed=self._question_embed(), view=self)

    async def _disable_all(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass

    def _build_answer_row(self):
        for key in ("yes", "no", "idk", "probably", "probably_not"):
            self.add_item(_AkinatorAnswerButton(self, key))

    def _build_back_row(self):
        self.add_item(_AkinatorBackButton(self))
        self.add_item(_AkinatorEndButton(self))

    async def _end(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This isn't your game! Start your own game with **`/akinator`**", ephemeral=True)
            return

        _ACTIVE_GAMES.pop(self.user.id, None)
        embed = discord.Embed(
            title="🛑 Game ended",
            description="Your Akinator game has been ended. Run `/akinator` to start a new one!",
            color=discord.Color(VOIDWAVE_COLOR),
        )
        embed.set_footer(text="Vote for 2x XP! /vote")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        _ACTIVE_GAMES.pop(self.user.id, None)
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class _AkinatorAnswerButton(discord.ui.Button):
    def __init__(self, view: AkinatorView, key: str):
        super().__init__(label=ANSWER_LABELS[key], emoji=ANSWER_EMOJIS[key], style=discord.ButtonStyle.secondary, row=0)
        self._key = key
        self._game = view

    async def callback(self, interaction: discord.Interaction):
        await self._game._answer(interaction, self._key)


class _AkinatorBackButton(discord.ui.Button):
    def __init__(self, view: AkinatorView):
        super().__init__(label="↩️ Back", style=discord.ButtonStyle.secondary, row=2)
        self._game = view

    async def callback(self, interaction: discord.Interaction):
        await self._game._back(interaction)


class _AkinatorEndButton(discord.ui.Button):
    def __init__(self, view: AkinatorView, row: int = 2):
        super().__init__(label="🛑 End game", style=discord.ButtonStyle.danger, row=row)
        self._game = view

    async def callback(self, interaction: discord.Interaction):
        await self._game._end(interaction)


class _AkinatorGuessButton(discord.ui.Button):
    def __init__(self, view: AkinatorView, guess: bool):
        super().__init__(
            label="✅ Yes, that's right!" if guess else "❌ No, keep going",
            style=discord.ButtonStyle.success if guess else discord.ButtonStyle.danger,
            row=0,
        )
        self._guess = guess
        self._game = view

    async def callback(self, interaction: discord.Interaction):
        await self._game._on_guess(interaction, self._guess)


class _RestartConfirmView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, theme_key: str):
        super().__init__(timeout=60)
        self._interaction = interaction
        self._theme_key = theme_key

    @discord.ui.button(label="🛑 End old game & start new", style=discord.ButtonStyle.danger)
    async def restart(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self._interaction.user.id:
            await interaction.response.send_message("You can't do that here!", ephemeral=True)
            return

        _ACTIVE_GAMES.pop(interaction.user.id, None)
        embed = discord.Embed(
            title="🛑 Old game ended",
            description="Starting a new game…",
            color=discord.Color(VOIDWAVE_COLOR),
        )
        await interaction.response.edit_message(embed=embed, view=None)

        await self._start_new()

    async def _start_new(self):
        interaction = self._interaction

        aki, error = await _create_game(self._theme_key)
        if aki is None:
            await interaction.followup.send(f"> Could not start an Akinator game after several tries. Please try again later.\n> `{error}`")
            self.stop()
            return

        view = AkinatorView(interaction.user, aki, self._theme_key)
        view._build_answer_row()
        view._build_back_row()

        message = await interaction.followup.send(embed=view._question_embed(), view=view)
        view.message = message
        _ACTIVE_GAMES[interaction.user.id] = view
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self._interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass


class AkinatorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _start_new(self, interaction: discord.Interaction, theme_key: str, hidden: bool):
        aki, error = await _create_game(theme_key)
        if aki is None:
            await interaction.followup.send(f"> Could not start an Akinator game after several tries. Please try again later.\n> `{error}`")
            return

        view = AkinatorView(interaction.user, aki, theme_key)
        view._build_answer_row()
        view._build_back_row()

        message = await interaction.followup.send(embed=view._question_embed(), view=view)
        view.message = message
        _ACTIVE_GAMES[interaction.user.id] = view

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="akinator", description="Play a game of Akinator and let VoidWave guess what you're thinking of.")
    @app_commands.describe(theme="What theme to guess from", hidden="Hide the command from others")
    @app_commands.choices(theme=[
        app_commands.Choice(name="Characters", value="characters"),
        app_commands.Choice(name="Objects", value="objects"),
        app_commands.Choice(name="Animals", value="animals"),
    ])
    async def akinator(self, interaction: discord.Interaction, theme: str = "characters", hidden: bool = False):
        theme_key = THEME_MAP[theme]

        if interaction.user.id in _ACTIVE_GAMES:
            embed = discord.Embed(
                title="⚠️ You already have a game running!",
                description="You can't start a new Akinator game until you finish or end your current one.",
                color=discord.Color(VOIDWAVE_COLOR),
            )
            view = _RestartConfirmView(interaction, theme_key)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=hidden)
        await self._start_new(interaction, theme_key, hidden)


async def setup(bot):
    await bot.add_cog(AkinatorCog(bot))
