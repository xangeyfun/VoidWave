from discord import app_commands
from discord.ext import commands
import discord
import random
import html as html_module
import utils


VOIDWAVE_COLOR = 0x7128fc

TEAM_EMOJI = {
    "rock": "🪨",
    "paper": "📄",
    "scissors": "✂️",
}

RPS_WINS = {
    "rock": "scissors",
    "paper": "rock",
    "scissors": "paper",
}

EIGHT_BALL_RESPONSES = [
    "🎱 As I see it, yes.",
    "🎱 Ask again later.",
    "🎱 Better not tell you now.",
    "🎱 Cannot predict now.",
    "🎱 Concentrate and ask again.",
    "🎱 Don't count on it.",
    "🎱 It is certain.",
    "🎱 It is decidedly so.",
    "🎱 Most likely.",
    "🎱 My reply is no.",
    "🎱 My sources say no.",
    "🎱 Outlook good.",
    "🎱 Outlook not so good.",
    "🎱 Reply hazy, try again.",
    "🎱 Signs point to yes.",
    "🎱 Very doubtful.",
    "🎱 Without a doubt.",
    "🎱 Yes.",
    "🎱 Yes - definitely.",
    "🎱 You may rely on it.",
]

TICTACTOE_EMPTY = "\u200b"


class RPSView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.bot_choice = random.choice(list(RPS_WINS.keys()))

    async def _finish(self, interaction: discord.Interaction, player_choice: str):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        player_emoji = TEAM_EMOJI[player_choice]
        bot_emoji = TEAM_EMOJI[self.bot_choice]

        if player_choice == self.bot_choice:
            result = "It's a tie! 🤝"
            color = discord.Color(0xf1c40f)
        elif RPS_WINS[player_choice] == self.bot_choice:
            result = "You win! 🎉"
            color = discord.Color(0x2ecc71)
        else:
            result = "You lose! 😅"
            color = discord.Color(0xe74c3c)

        embed = discord.Embed(
            title="🪨📄✂️ Rock Paper Scissors",
            description=(
                f"> {player_emoji} **You** - **{player_choice.title()}**\n"
                f"> {bot_emoji} **VoidWave** - **{self.bot_choice.title()}**\n\n"
                f"**{result}**"
            ),
            color=color,
        )
        embed.set_footer(text="Vote for 2x XP! /vote")
        await interaction.followup.send(embed=embed)

    @discord.ui.button(emoji="🪨", style=discord.ButtonStyle.secondary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, "rock")

    @discord.ui.button(emoji="📄", style=discord.ButtonStyle.secondary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, "paper")

    @discord.ui.button(emoji="✂️", style=discord.ButtonStyle.secondary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, "scissors")

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


TICTACTOE_WIN_LINES = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


class TicTacToeView(discord.ui.View):
    def __init__(self, player: discord.User):
        super().__init__(timeout=120)
        self.player = player
        self.board = [TICTACTOE_EMPTY] * 9
        self.winner = None
        self.move_count = 0

    def _state_embed(self, over=False):
        if self.winner == "player":
            title = "❌ You win! 🎉"
            color = discord.Color(0x2ecc71)
        elif self.winner == "bot":
            title = "✅ VoidWave wins! 😅"
            color = discord.Color(0xe74c3c)
        elif over:
            title = "🤝 It's a draw!"
            color = discord.Color(0xf1c40f)
        else:
            title = "Tic-Tac-Toe"
            color = discord.Color(VOIDWAVE_COLOR)
        description = (
            f"> {self.player.mention} is **❌ (X)** and VoidWave is **⭕ (O)**.\n"
            f"> Click a square to place your mark!"
        )
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text="Vote for 2x XP! /vote")
        return embed

    def _check_winner(self):
        for a, b, c in TICTACTOE_WIN_LINES:
            if self.board[a] != TICTACTOE_EMPTY and self.board[a] == self.board[b] == self.board[c]:
                return self.board[a]
        return None

    def _bot_move(self):
        empty = [i for i, m in enumerate(self.board) if m == TICTACTOE_EMPTY]

        def find_move(me, other):
            for i in empty:
                self.board[i] = me
                if self._check_winner() == me:
                    self.board[i] = TICTACTOE_EMPTY
                    return i
                self.board[i] = TICTACTOE_EMPTY
            return None

        win = find_move("O", "X")
        if win is not None:
            return win
        block = find_move("X", "O")
        if block is not None:
            return block
        if 4 in empty:
            return 4
        return random.choice(empty)

    @discord.ui.button(label=TICTACTOE_EMPTY, style=discord.ButtonStyle.secondary, row=0)
    async def cell0(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._player_move(interaction, 0)

    @discord.ui.button(label=TICTACTOE_EMPTY, style=discord.ButtonStyle.secondary, row=0)
    async def cell1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._player_move(interaction, 1)

    @discord.ui.button(label=TICTACTOE_EMPTY, style=discord.ButtonStyle.secondary, row=0)
    async def cell2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._player_move(interaction, 2)

    @discord.ui.button(label=TICTACTOE_EMPTY, style=discord.ButtonStyle.secondary, row=1)
    async def cell3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._player_move(interaction, 3)

    @discord.ui.button(label=TICTACTOE_EMPTY, style=discord.ButtonStyle.secondary, row=1)
    async def cell4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._player_move(interaction, 4)

    @discord.ui.button(label=TICTACTOE_EMPTY, style=discord.ButtonStyle.secondary, row=1)
    async def cell5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._player_move(interaction, 5)

    @discord.ui.button(label=TICTACTOE_EMPTY, style=discord.ButtonStyle.secondary, row=2)
    async def cell6(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._player_move(interaction, 6)

    @discord.ui.button(label=TICTACTOE_EMPTY, style=discord.ButtonStyle.secondary, row=2)
    async def cell7(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._player_move(interaction, 7)

    @discord.ui.button(label=TICTACTOE_EMPTY, style=discord.ButtonStyle.secondary, row=2)
    async def cell8(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._player_move(interaction, 8)

    async def _player_move(self, interaction: discord.Interaction, index: int):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return

        if self.board[index] != TICTACTOE_EMPTY or self.winner is not None:
            return

        self.board[index] = "❌"
        self.move_count += 1
        self.winner = self._check_winner()

        found_winner = self.winner is not None

        if not found_winner and self.move_count < 9:
            bot_index = self._bot_move()
            self.board[bot_index] = "⭕"
            self.move_count += 1
            self.winner = self._check_winner()
            found_winner = self.winner is not None

        game_over = found_winner or self.move_count == 9
        embed = self._state_embed(over=game_over)

        for i, child in enumerate(self.children):
            child.label = self.board[i]
            child.disabled = self.board[i] != TICTACTOE_EMPTY or game_over

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class TriviaView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, question, options, answer):
        super().__init__(timeout=60)
        self.interaction = interaction
        self.question = question
        self.options = options
        self.answer = answer
        self.answered = False

        for label in options:
            self.add_item(_TriviaButton(label, self))

    async def reveal(self, interaction: discord.Interaction, chosen: str):
        self.answered = True
        correct = self.answer == chosen
        embed = discord.Embed(
            title="❓ Trivia",
            description=f"**{self.question}**",
            color=discord.Color(0x2ecc71 if correct else 0xe74c3c),
        )
        embed.add_field(
            name="Your answer",
            value=f"{'✅' if correct else '❌'} **{chosen}**",
            inline=False,
        )
        if not correct:
            embed.add_field(name="Correct answer", value=f"✅ **{self.answer}**", inline=False)
        embed.set_footer(text="Vote for 2x XP! /vote")

        for child in self.children:
            child.disabled = True
            if child.label == self.answer:
                child.style = discord.ButtonStyle.success
            else:
                child.style = discord.ButtonStyle.danger

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        embed = discord.Embed(
            title="❓ Trivia",
            description=f"**{self.question}**\n\n⏰ Time's up! The correct answer was **{self.answer}**.",
            color=discord.Color(0x95a5a6),
        )
        embed.set_footer(text="Vote for 2x XP! /vote")
        for child in self.children:
            child.disabled = True
        try:
            await self.interaction.edit_original_response(embed=embed, view=self)
        except discord.HTTPException:
            pass
        except discord.NotFound:
            pass


class _TriviaButton(discord.ui.Button):
    def __init__(self, label, view):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.host_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.host_view.interaction.user.id:
            await interaction.response.send_message("This isn't your trivia game!", ephemeral=True)
            return
        if self.host_view.answered:
            return
        await self.host_view.reveal(interaction, self.label)


class GamesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="8ball", description="Ask the magic 8-ball a question.")
    @app_commands.describe(question="The question you want answered", hidden="Hide the command from others")
    async def eight_ball(self, interaction: discord.Interaction, question: str, hidden: bool = False):
        embed = discord.Embed(
            title="🎱 Magic 8-Ball",
            description=(
                f"> **Q:** {question}\n"
                f"> **A:** {random.choice(EIGHT_BALL_RESPONSES)}"
            ),
            color=discord.Color(VOIDWAVE_COLOR),
        )
        embed.set_footer(text="Vote for 2x XP! /vote")
        await interaction.response.send_message(embed=embed, ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="rps", description="Play rock, paper, scissors against VoidWave.")
    @app_commands.describe(hidden="Hide the command from others")
    async def rps(self, interaction: discord.Interaction, hidden: bool = False):
        embed = discord.Embed(
            title="🪨📄✂️ Rock Paper Scissors",
            description="Pick your move below!",
            color=discord.Color(VOIDWAVE_COLOR),
        )
        embed.set_footer(text="Vote for 2x XP! /vote")
        await interaction.response.send_message(embed=embed, ephemeral=hidden, view=RPSView())

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="tictactoe", description="Play tic-tac-toe against VoidWave.")
    @app_commands.describe(hidden="Hide the command from others")
    async def tictactoe(self, interaction: discord.Interaction, hidden: bool = False):
        view = TicTacToeView(interaction.user)
        await interaction.response.send_message(embed=view._state_embed(), ephemeral=hidden, view=view)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="trivia", description="Test your knowledge with a random trivia question.")
    @app_commands.describe(hidden="Hide the command from others")
    async def trivia(self, interaction: discord.Interaction, hidden: bool = False):
        await interaction.response.defer(ephemeral=hidden)

        try:
            async with utils.http_session.get("https://opentdb.com/api.php?amount=1&type=multiple") as r:
                data = await r.json()
        except Exception as e:
            await interaction.followup.send(f"> Could not fetch a trivia question. Please try again later.\n> {e}")
            return

        results = (data or {}).get("results")
        if not results:
            await interaction.followup.send("> Could not fetch a trivia question. Please try again later.")
            return

        result = results[0]

        def clean(text):
            return html_module.unescape(str(text))

        question = clean(result["question"])
        correct = clean(result["correct_answer"])
        incorrect = [clean(a) for a in result["incorrect_answers"]]

        options = [correct] + incorrect
        random.shuffle(options)

        embed = discord.Embed(
            title="❓ Trivia",
            description=f"**{question}**\n\nSelect an answer below!",
            color=discord.Color(VOIDWAVE_COLOR),
        )
        embed.set_footer(text="Vote for 2x XP! /vote")

        view = TriviaView(interaction, question, options, correct)
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(GamesCog(bot))
