from discord import app_commands
from discord.ext import commands
import discord
import random
import html as html_module
import asyncio
import utils


VOIDWAVE_COLOR = 0x7128fc

_trivia_token = None

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
    "As I see it, yes.",
    "Ask again later.",
    "Better not tell you now.",
    "Cannot predict now.",
    "Concentrate and ask again.",
    "Don't count on it.",
    "It is certain.",
    "It is decidedly so.",
    "Most likely.",
    "My reply is no.",
    "My sources say no.",
    "Outlook good.",
    "Outlook not so good.",
    "Reply hazy, try again.",
    "Signs point to yes.",
    "Very doubtful.",
    "Without a doubt.",
    "Yes.",
    "Yes, definitely.",
    "You may rely on it.",
]

TICTACTOE_EMPTY = "\u200b"


class RPSView(discord.ui.View):
    def __init__(self, player: discord.User):
        super().__init__(timeout=120)
        self.player = player
        self.bot_choice = random.choice(list(RPS_WINS.keys()))

    async def _finish(self, interaction: discord.Interaction, player_choice: str):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True

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
        await interaction.response.edit_message(embed=embed, view=self)

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

        win = find_move("⭕", "❌")
        if win is not None:
            return win
        block = find_move("❌", "⭕")
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
        self.winner = "player" if self._check_winner() else None

        found_winner = self.winner is not None

        if not found_winner and self.move_count < 9:
            bot_index = self._bot_move()
            self.board[bot_index] = "⭕"
            self.move_count += 1
            self.winner = "bot" if self._check_winner() else None
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
        self._loading = False

        for label in options:
            self.add_item(_TriviaButton(label, self))

    @staticmethod
    async def _ensure_token():
        global _trivia_token
        if _trivia_token:
            return
        try:
            async with utils.http_session.get("https://opentdb.com/api_token.php?command=request") as r:
                data = await r.json()
            if (data or {}).get("response_code") == 0:
                _trivia_token = data.get("token")
        except Exception:
            pass

    @staticmethod
    async def fetch_question():
        global _trivia_token
        await TriviaView._ensure_token()

        for attempt in range(6):
            url = "https://opentdb.com/api.php?amount=1&type=multiple"
            if _trivia_token:
                url += f"&token={_trivia_token}"
            try:
                async with utils.http_session.get(url) as r:
                    data = await r.json()
            except Exception:
                return None

            code = (data or {}).get("response_code")
            if code == 0:
                result = (data.get("results") or [None])[0]
                if not result:
                    return None

                def clean(text):
                    return html_module.unescape(str(text))

                question = clean(result["question"])
                correct = clean(result["correct_answer"])
                incorrect = [clean(a) for a in result["incorrect_answers"]]

                options = [correct] + incorrect
                random.shuffle(options)

                return question, options, correct
            elif code == 1:
                _trivia_token = None
                return None
            elif code == 5:
                await asyncio.sleep(min(5, 2 ** attempt))
                continue
            else:
                return None

        return None

    def _build_embed(self):
        embed = discord.Embed(
            title="❓ Trivia",
            description=f"**{self.question}**\n\nSelect an answer below!",
            color=discord.Color(VOIDWAVE_COLOR),
        )
        embed.set_footer(text="Vote for 2x XP! /vote")
        return embed

    async def start_again(self, interaction: discord.Interaction):
        if self._loading:
            try:
                await interaction.response.send_message("Loading a new question...", ephemeral=True)
            except discord.HTTPException:
                pass
            return
        self._loading = True
        await interaction.response.defer()
        fetched = await self.fetch_question()
        if not fetched:
            self._loading = False
            try:
                await interaction.edit_original_response(
                    content="> Could not fetch a trivia question. Please try again later.",
                    embed=None,
                    view=None,
                )
            except discord.HTTPException:
                pass
            return
        self.question, self.options, self.answer = fetched
        self.answered = False
        self._loading = False
        self.clear_items()
        for label in self.options:
            self.add_item(_TriviaButton(label, self))
        await interaction.edit_original_response(embed=self._build_embed(), view=self)

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

        self.add_item(_TriviaAgainButton(self))

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
        super().__init__(label=label, style=discord.ButtonStyle.primary, row=1)
        self.host_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.host_view.interaction.user.id:
            await interaction.response.send_message("This isn't your trivia game!", ephemeral=True)
            return
        if self.host_view.answered:
            return
        await self.host_view.reveal(interaction, self.label)


class _TriviaAgainButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="🔁 Another", style=discord.ButtonStyle.secondary, row=1)
        self.host_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.host_view.interaction.user.id:
            await interaction.response.send_message("This isn't your trivia game!", ephemeral=True)
            return
        await self.host_view.start_again(interaction)


CONNECT_FOUR_ROWS = 6
CONNECT_FOUR_COLS = 7
CONNECT_FOUR_EMPTY = "⚪"
CONNECT_FOUR_PLAYER = "🔴"
CONNECT_FOUR_BOT = "🟣"


class ConnectFourView(discord.ui.View):
    def __init__(self, player: discord.User):
        super().__init__(timeout=120)
        self.player = player
        self.board = [[CONNECT_FOUR_EMPTY] * CONNECT_FOUR_COLS for _ in range(CONNECT_FOUR_ROWS)]
        self.winner = None
        self.move_count = 0

    def _board_embed(self, over=False):
        if self.winner == "player":
            title = "🔴 You win! 🎉"
            color = discord.Color(0x2ecc71)
        elif self.winner == "bot":
            title = "🟣 VoidWave wins! 😅"
            color = discord.Color(0xe74c3c)
        elif over:
            title = "🤝 It's a draw!"
            color = discord.Color(0xf1c40f)
        else:
            title = "Connect Four"
            color = discord.Color(VOIDWAVE_COLOR)

        grid = "\n".join(" ".join(row) for row in self.board)
        column_numbers = " ".join(f"{c + 1:>2}" for c in range(CONNECT_FOUR_COLS))
        description = (
            f"> {self.player.mention} is **{CONNECT_FOUR_PLAYER}** and VoidWave is **{CONNECT_FOUR_BOT}**.\n"
            f"> Press a column button below to drop your piece!\n\n"
            f"```\n{grid}\n{column_numbers}\n```"
        )
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text="Vote for 2x XP! /vote")
        return embed

    def _drop(self, col, piece):
        for row in range(CONNECT_FOUR_ROWS - 1, -1, -1):
            if self.board[row][col] == CONNECT_FOUR_EMPTY:
                self.board[row][col] = piece
                return row
        return None

    def _check_winner_at(self, row, col):
        piece = self.board[row][col]
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            count = 1
            for step in (1, -1):
                r, c = row + dr * step, col + dc * step
                while 0 <= r < CONNECT_FOUR_ROWS and 0 <= c < CONNECT_FOUR_COLS and self.board[r][c] == piece:
                    count += 1
                    r += dr * step
                    c += dc * step
            if count >= 4:
                return True
        return False

    def _find_winning_col(self, me):
        for col in range(CONNECT_FOUR_COLS):
            if self.board[0][col] != CONNECT_FOUR_EMPTY:
                continue
            row = self._drop(col, me)
            won = self._check_winner_at(row, col)
            self.board[row][col] = CONNECT_FOUR_EMPTY
            if won:
                return col
        return None

    def _bot_move(self):
        win = self._find_winning_col(CONNECT_FOUR_BOT)
        if win is not None:
            return win
        block = self._find_winning_col(CONNECT_FOUR_PLAYER)
        if block is not None:
            return block
        preferred = [3, 2, 4, 1, 5, 0, 6]
        for col in preferred:
            if self.board[0][col] == CONNECT_FOUR_EMPTY:
                return col
        return None

    async def _player_turn(self, interaction: discord.Interaction, col: int):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        if self.winner is not None:
            return
        if self.board[0][col] != CONNECT_FOUR_EMPTY:
            await interaction.response.send_message("That column is full!", ephemeral=True)
            return

        row = self._drop(col, CONNECT_FOUR_PLAYER)
        self.move_count += 1
        if self._check_winner_at(row, col):
            self.winner = "player"

        if self.winner is None and self.move_count < CONNECT_FOUR_ROWS * CONNECT_FOUR_COLS:
            bot_col = self._bot_move()
            bot_row = self._drop(bot_col, CONNECT_FOUR_BOT)
            self.move_count += 1
            if self._check_winner_at(bot_row, bot_col):
                self.winner = "bot"

        game_over = self.winner is not None or self.move_count >= CONNECT_FOUR_ROWS * CONNECT_FOUR_COLS
        embed = self._board_embed(over=game_over)

        if game_over:
            for child in self.children:
                child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class ConnectFourButton(discord.ui.Button):
    def __init__(self, col, view, row):
        super().__init__(label=f"{col + 1}", style=discord.ButtonStyle.secondary, row=row)
        self.col = col
        self.game_view = view

    async def callback(self, interaction: discord.Interaction):
        await self.game_view._player_turn(interaction, self.col)


HANGMAN_WORDS = (
    "python", "javascript", "server", "discord", "level", "starlight",
    "android", "keyboard", "monitor", "galaxy", "crystal", "thunder",
    "mountain", "ocean", "garden", "library", "captain", "pixel",
    "rocket", "comet", "nebula", "shadow", "firefly", "guitar",
    "breeze", "canyon", "sunrise", "horizon", "island", "kingdom",
    "lantern", "mystic", "nomad", "orbit", "phoenix", "quantum",
    "raptor", "sapphire", "tournament", "umbrella", "voyage", "walrus",
    "zeppelin", "adventure", "biscuit", "cascade", "dragonfly", "emerald",
    "astronaut", "blacksmith", "cathedral", "dolphin", "eclipse", "forest",
    "glacier", "harbor", "icicle", "journey", "kangaroo", "lagoon",
    "mammoth", "nightingale", "octopus", "paradise", "quicksilver", "rainbow",
    "savanna", "tornado", "unicorn", "volcano", "waterfall", "yacht",
    "zephyr", "blueprint", "chandelier", "diamonds", "elephant", "fireworks",
    "glowworm", "harmony", "igloo", "jasmine", "kilometer", "language",
    "mirage", "northstar", "octagon", "planetarium", "quasar", "staircase",
    "telescope", "universe", "vortex", "whisper", "xylophone", "yellowstone",
    "zealous", "algorithm", "bandwidth", "chipmunk", "dashboard", "elevator",
    "forecast", "greenhouse", "hierarchy", "instrument", "javascript", "keyboard",
    "latitude", "magnet", "nutmeg", "ostrich", "pillowcase", "quartz",
    "radiator", "satellite", "tangerine", "underwater", "vacation", "watermelon",
    "yogurt", "zebra", "abacus", "banjo", "cactus", "dandelion",
    "eucalyptus", "fireplace", "gazebo", "honeycomb", "ivory", "jungle",
    "kindergarten", "lemonade", "moonshine", "nightshade", "obsidian", "pineapple",
    "quest", "reindeer", "sunflower", "twilight", "umbrella", "vineyard",
    "whirlwind", "xenon", "yo-yo", "zeppelin",
)

WORDLE_WORDS = (
    "apple", "about", "above", "abuse", "actor", "acute", "admit", "adobe",
    "adopt", "adult", "after", "again", "agent", "agree", "ahead", "alarm",
    "album", "alert", "alien", "align", "alive", "allow", "alone", "along",
    "alter", "amaze", "ample", "angle", "angry", "apart", "apple", "apply",
    "arena", "argue", "arise", "armed", "array", "aside", "asset", "audio",
    "audit", "avoid", "award", "aware", "awful", "basic", "beach", "beard",
    "beast", "begin", "being", "belly", "below", "bench", "birth", "black",
    "blade", "blame", "blank", "blast", "blaze", "bleak", "blend", "blind",
    "block", "blood", "bloom", "blown", "board", "boast", "boost", "brain",
    "brand", "brave", "bread", "break", "breed", "brick", "brief", "bring",
    "broad", "brood", "brown", "brush", "build", "bunch", "burst", "cabin",
    "cable", "candy", "canoe", "carry", "catch", "cause", "cease", "chain",
    "chair", "chaos", "charm", "chase", "cheap", "cheek", "cheer", "chess",
    "chest", "chief", "child", "chill", "choir", "chose", "chunk", "civic",
    "civil", "claim", "clash", "class", "clean", "clear", "click", "cliff",
    "climb", "clock", "close", "cloud", "coach", "coast", "coral", "couch",
    "cough", "could", "count", "court", "cover", "crack", "craft", "crane",
    "crash", "crazy", "cream", "crime", "crisp", "cross", "crowd", "crown",
    "crude", "cruel", "crush", "curve", "cycle", "daily", "dance", "death",
    "debut", "decor", "delay", "delta", "dense", "depth", "devil", "diary",
    "dirty", "ditch", "dizzy", "dough", "dozen", "drama", "drift", "drink",
    "drive", "drone", "drove", "dying", "eager", "eagle", "early", "earth",
    "eight", "elbow", "elder", "elect", "elite", "empty", "enemy", "enjoy",
    "enter", "entry", "equal", "error", "essay", "event", "every", "exact",
    "exile", "exist", "extra", "fable", "facet", "faint", "fairy", "faith",
    "false", "fancy", "fault", "favor", "feast", "fence", "ferry", "fever",
    "fiber", "field", "fifth", "fifty", "fight", "final", "first", "flame",
    "flask", "fleet", "flesh", "float", "flock", "flood", "floor", "flour",
    "fluid", "flush", "focal", "focus", "force", "forge", "forth", "forty",
    "forum", "found", "frame", "fresh", "front", "frost", "fruit", "fully",
    "funny", "gauge", "gears", "ghost", "giant", "given", "glass", "globe",
    "gloom", "glory", "glove", "glued", "going", "grace", "grade", "grain",
    "grand", "grant", "grape", "graph", "grasp", "grass", "grave", "great",
    "green", "grief", "grill", "grind", "gross", "group", "grove", "grown",
    "guard", "guess", "guest", "guide", "guilt", "habit", "happy", "harsh",
    "haste", "hatch", "haunt", "haven", "hazel", "heart", "heavy", "hedge",
    "hello", "hence", "herbs", "hinge", "honey", "honor", "horse", "hotel",
    "house", "human", "humor", "hurry", "ideal", "image", "imply", "index",
    "inner", "input", "irony", "issue", "ivory", "jazzy", "jeans", "jelly",
    "jewel", "joint", "judge", "juice", "kayak", "kebab", "kneel", "knife",
    "knock", "known", "label", "labor", "large", "laser", "later", "laugh",
    "layer", "learn", "lease", "least", "leave", "legal", "lemon", "level",
    "light", "limit", "liver", "lobby", "local", "lodge", "logic", "loose",
    "lover", "lower", "lucky", "lunar", "lunch", "lying", "magic", "major",
    "maker", "manor", "maple", "march", "marsh", "mason", "match", "maybe",
    "mayor", "meant", "media", "medal", "melon", "mercy", "merit", "metal",
    "meter", "might", "minor", "minus", "mixed", "model", "money", "month",
    "moral", "motor", "mount", "mouse", "mouth", "movie", "music", "nerve",
    "never", "newly", "night", "noble", "noise", "north", "noted", "novel",
    "nurse", "oasis", "occur", "ocean", "offer", "often", "olive", "onion",
    "onset", "opera", "orbit", "order", "organ", "other", "ought", "ounce",
    "outer", "owner", "paint", "panel", "panic", "paper", "party", "pasta",
    "patch", "peace", "peach", "pearl", "piano", "piece", "pilot", "pinch",
    "pitch", "pizza", "place", "plain", "plane", "plant", "plate", "plead",
    "pluck", "point", "polar", "porch", "posed", "pound", "power", "press",
    "price", "pride", "prime", "print", "prior", "prize", "proof", "proud",
    "prove", "pulse", "punch", "pupil", "purse", "quest", "queue", "quick",
    "quiet", "quite", "quote", "radio", "raise", "rally", "ranch", "range",
    "rapid", "ratio", "reach", "react", "ready", "refer", "relax", "reply",
    "rider", "rifle", "right", "rigid", "ripen", "risky", "rival", "river",
    "robot", "rocky", "roman", "rough", "round", "route", "royal", "rugby",
    "ruler", "rural", "sadly", "saint", "sauce", "scale", "scare", "scene",
    "scent", "scope", "score", "scout", "screw", "seize", "sense", "serve",
    "seven", "shade", "shake", "shall", "shame", "shape", "share", "shark",
    "sharp", "sheep", "sheet", "shelf", "shell", "shift", "shine", "shirt",
    "shock", "shoot", "shore", "short", "shout", "showy", "since", "siren",
    "sixth", "sixty", "skill", "skirt", "slate", "sleep", "slice", "slide",
    "slope", "small", "smart", "smell", "smile", "smoke", "snack", "snake",
    "solar", "solid", "solve", "sorry", "sound", "south", "space", "spare",
    "spark", "speak", "speed", "spell", "spend", "spent", "spice", "spike",
    "spine", "spite", "split", "spoke", "sport", "spray", "squad", "stack",
    "staff", "stage", "stain", "stake", "stale", "stand", "stare", "start",
    "state", "stave", "stead", "steam", "steel", "steep", "steer", "stunt",
    "stern", "stick", "stiff", "still", "sting", "stock", "stole", "stone",
    "stood", "stool", "store", "storm", "story", "stove", "strap", "straw",
    "stray", "strip", "stuck", "study", "stuff", "style", "sugar", "suite",
    "sunny", "super", "surge", "sweet", "swift", "swing", "sword", "table",
    "taken", "taste", "teach", "teeth", "tempo", "tenth", "theme", "there",
    "these", "thick", "thing", "think", "third", "those", "three", "threw",
    "throw", "thumb", "tiger", "tight", "timer", "tired", "title", "toast",
    "today", "token", "tonic", "tooth", "topic", "total", "touch", "tough",
    "towel", "tower", "toxic", "trace", "track", "trade", "trail", "train",
    "trait", "treat", "trend", "trial", "tribe", "trick", "tried", "troop",
    "truck", "truly", "trunk", "trust", "truth", "twice", "twist", "uncle",
    "under", "union", "unite", "unity", "until", "upper", "upset", "urban",
    "usage", "usual", "utter", "vague", "valid", "value", "valve", "vapor",
    "vault", "venue", "verse", "video", "vigor", "viral", "virus", "visit",
    "vital", "vivid", "vocal", "voice", "voter", "wagon", "waste", "watch",
    "water", "weary", "weave", "wedge", "weigh", "whale", "wheat", "wheel",
    "where", "which", "while", "white", "whole", "whose", "widow", "width",
    "witch", "woman", "world", "worry", "worse", "worst", "worth", "would",
    "wound", "wreck", "write", "wrong", "wrote", "yacht", "yield", "young",
    "youth", "zebra", "zesty", "zones",
)

HANGMAN_MAX_WRONG = 6


class HangmanView(discord.ui.View):
    def __init__(self, player: discord.User):
        super().__init__(timeout=120)
        self.player = player
        self.word = random.choice(HANGMAN_WORDS).upper()
        self.guessed = set()
        self.wrong = 0
        self.done = False
        self.add_item(_HangmanSelect("A-M", "ABCDEFGHIJKLM", self))
        self.add_item(_HangmanSelect("N-Z", "NOPQRSTUVWXYZ", self))

    def _state_embed(self):
        masked = " ".join((ch if ch in self.guessed else "▬") for ch in self.word)
        if self.wrong >= HANGMAN_MAX_WRONG:
            title = "💀 You lost!"
            color = discord.Color(0xe74c3c)
            description = f"> The word was **{self.word}**."
        elif all(ch in self.guessed for ch in self.word):
            title = "🎉 You won!"
            color = discord.Color(0x2ecc71)
            description = f"> Word guessed: **{self.word}**"
        else:
            title = "✏️ Hangman"
            color = discord.Color(VOIDWAVE_COLOR)
            description = f"> Guess the word! Select a letter below."

        wrong_letters = " ".join(sorted(l for l in self.guessed if l not in self.word))
        embed = discord.Embed(
            title=title,
            description=(
                f"{description}\n\n"
                f"**{masked}**\n"
                f"**Wrong:** {wrong_letters or 'none'}\n"
                f"**Lives:** {'❤️' * (HANGMAN_MAX_WRONG - self.wrong)}{'🖤' * self.wrong}"
            ),
            color=color,
        )
        embed.set_footer(text="Vote for 2x XP! /vote")
        return embed

    def _refresh_options(self):
        for child in self.children:
            if isinstance(child, _HangmanSelect):
                child.rebuild(self.guessed)

    def _refresh_embed_and_view(self):
        embed = self._state_embed()
        for child in self.children:
            if isinstance(child, _HangmanSelect):
                child.disabled = self.done or not child.remaining()
        self._refresh_options()
        return embed

    async def _guess(self, interaction: discord.Interaction, letter: str):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        if self.done or letter in self.guessed:
            return

        self.guessed.add(letter)
        if letter not in self.word:
            self.wrong += 1

        if self.wrong >= HANGMAN_MAX_WRONG or all(ch in self.guessed for ch in self.word):
            self.done = True

        embed = self._refresh_embed_and_view()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            if isinstance(child, _HangmanSelect):
                child.disabled = True


class _HangmanSelect(discord.ui.Select):
    def __init__(self, placeholder, letters, view, row=0):
        self.letters = list(letters)
        self.game_view = view
        options = [discord.SelectOption(label=l, value=l) for l in self.letters]
        super().__init__(
            placeholder=placeholder,
            options=options,
            min_values=1,
            max_values=1,
            disabled=False,
        )
        self._reset()

    def remaining(self):
        return [l for l in self.letters if l not in self.game_view.guessed]

    def rebuild(self, guessed):
        remaining = [l for l in self.letters if l not in guessed]
        if not remaining:
            self.placeholder = "Done"
        else:
            self.placeholder = remaining[0] + "-" + remaining[-1]
        self.options = [discord.SelectOption(label=l, value=l) for l in remaining]
        if self.values:
            self._reset()

    def _reset(self):
        self._values = []

    async def callback(self, interaction: discord.Interaction):
        if not self.values:
            return
        await self.game_view._guess(interaction, self.values[0])


CARD_SUITS = ("♠", "♥", "♦", "♣")
CARD_RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")


def _build_deck():
    return [f"{rank}{suit}" for suit in CARD_SUITS for rank in CARD_RANKS]


def _card_value(card):
    rank = card[:-1]
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)


def _hand_value(hand):
    total = sum(_card_value(c) for c in hand)
    aces = sum(1 for c in hand if c[:-1] == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


class BlackjackView(discord.ui.View):
    def __init__(self, player: discord.User):
        super().__init__(timeout=120)
        self.player = player
        self.deck = _build_deck()
        random.shuffle(self.deck)
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.bot_hand = [self.deck.pop(), self.deck.pop()]
        self.over = False

    def _state_embed(self):
        player_value = _hand_value(self.player_hand)

        description = (
            f"> **Your hand:** {' '.join(self.player_hand)}\n"
            f"> **Your total:** {player_value}\n"
        )

        if self.over:
            bot_value = _hand_value(self.bot_hand)
            description += f"> **VoidWave's hand:** {' '.join(self.bot_hand)} ({bot_value})"

            if player_value > 21:
                embed = discord.Embed(title="💥 You busted! VoidWave wins. 😅", description=description, color=discord.Color(0xe74c3c))
            elif bot_value > 21:
                embed = discord.Embed(title="🎉 VoidWave busted, you win!", description=description, color=discord.Color(0x2ecc71))
            elif player_value > bot_value:
                embed = discord.Embed(title="🎉 You win!", description=description, color=discord.Color(0x2ecc71))
            elif player_value < bot_value:
                embed = discord.Embed(title="😅 VoidWave wins!", description=description, color=discord.Color(0xe74c3c))
            else:
                embed = discord.Embed(title="🤝 It's a push!", description=description, color=discord.Color(0xf1c40f))
        else:
            description += f"> **VoidWave's hand:** {self.bot_hand[0]} 🂠 (?)"
            title_color = discord.Color(VOIDWAVE_COLOR)
            embed = discord.Embed(title="🃏 Blackjack", description=description, color=title_color)

        embed.set_footer(text="Vote for 2x XP! /vote")
        return embed

    async def _hit(self, interaction: discord.Interaction):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        if self.over:
            return
        self.player_hand.append(self.deck.pop())
        if _hand_value(self.player_hand) > 21:
            self.over = True
            for child in self.children:
                child.disabled = True
        await interaction.response.edit_message(embed=self._state_embed(), view=self)

    async def _stand(self, interaction: discord.Interaction):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        if self.over:
            return
        self.over = True
        while _hand_value(self.bot_hand) < 17:
            self.bot_hand.append(self.deck.pop())
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=self._state_embed(), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.success)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._hit(interaction)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.danger)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._stand(interaction)


WORDLE_MAX_GUESSES = 6

WORDLE_COLOR = {
    2: "🟩",
    1: "🟨",
    0: "⬛",
}


def _wordle_hint(guess, word):
    hint = [0] * len(word)
    used = [False] * len(word)

    for i, ch in enumerate(guess):
        if ch == word[i]:
            hint[i] = 2
            used[i] = True

    for i, ch in enumerate(guess):
        if hint[i] == 2:
            continue
        for j in range(len(word)):
            if word[j] == ch and not used[j] and hint[j] != 2:
                hint[i] = 1
                used[j] = True
                break

    return hint


class _WordleGuessModal(discord.ui.Modal, title="Wordle Guess"):
    def __init__(self, view):
        super().__init__()
        self.host_view = view
        self.word_input = discord.ui.TextInput(
            label="5-letter word",
            placeholder="Enter your guess (e.g. CRANE)",
            min_length=5,
            max_length=5,
            style=discord.TextStyle.short,
            required=True,
        )
        self.add_item(self.word_input)

    async def on_submit(self, interaction: discord.Interaction):
        guess = self.word_input.value.strip().upper()
        if not guess.isalpha() or len(guess) != 5:
            await interaction.response.send_message("Please enter a valid 5-letter word.", ephemeral=True)
            return
        await self.host_view._submit_guess(interaction, guess)


class WordleView(discord.ui.View):
    def __init__(self, player: discord.User):
        super().__init__(timeout=300)
        self.player = player
        self.word = random.choice(WORDLE_WORDS).upper()
        self.guesses = []
        self.done = False
        self.message = None
        self.add_item(_WordleGuessButton(self))
        self.add_item(_WordleRevealButton(self))

    def _format_row(self, guess):
        hint = _wordle_hint(guess, self.word)
        letters = "  ".join(guess)
        tiles = " ".join(WORDLE_COLOR[h] for h in hint)
        return f"> `{letters}`\n> {tiles}"

    def _state_embed(self):
        lines = [self._format_row(g) for g in self.guesses]

        if self.done:
            if self.guesses and self.guesses[-1] == self.word:
                title = "🎉 You got it!"
                color = discord.Color(0x2ecc71)
                description = f"> The word was **{self.word}**.\n\n" + "\n\n".join(lines)
            else:
                title = "😞 Out of guesses!"
                color = discord.Color(0xe74c3c)
                description = f"> The word was **{self.word}**.\n\n" + "\n\n".join(lines)
        else:
            title = "🟩🟨⬛ Wordle"
            color = discord.Color(VOIDWAVE_COLOR)
            description = (
                "> Guess the 5-letter word in 6 tries.\n"
                "> 🟩 correct spot, 🟨 wrong spot, ⬛ not in the word.\n\n"
                + "\n\n".join(lines)
            )

        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text=f"Guess {len(self.guesses)}/{WORDLE_MAX_GUESSES} • Vote for 2x XP! /vote")
        return embed

    async def _submit_guess(self, interaction: discord.Interaction, guess: str):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        if self.done or len(self.guesses) >= WORDLE_MAX_GUESSES:
            await interaction.response.send_message("This game is already over.", ephemeral=True)
            return

        await interaction.response.defer()
        self.guesses.append(guess)
        if guess == self.word or len(self.guesses) >= WORDLE_MAX_GUESSES:
            self.done = True
            for child in self.children:
                child.disabled = True

        embed = self._state_embed()
        await self._edit(embed)

    async def _reveal(self, interaction: discord.Interaction):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        if self.done:
            return
        await interaction.response.defer()
        self.done = True
        for child in self.children:
            child.disabled = True
        await self._edit(self._state_embed())

    async def _edit(self, embed):
        try:
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass
        except discord.NotFound:
            pass

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class _WordleGuessButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="✏️ Guess", style=discord.ButtonStyle.success)
        self.host_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.host_view.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        if self.host_view.done:
            return
        await interaction.response.send_modal(_WordleGuessModal(self.host_view))


class _WordleRevealButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="💡 Reveal", style=discord.ButtonStyle.secondary)
        self.host_view = view

    async def callback(self, interaction: discord.Interaction):
        await self.host_view._reveal(interaction)


MS_COLS = 5
MS_ROWS = 4
MS_MINES = 5
MS_CELLS = 20

MS_NUM_EMOJI = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
}


def _ms_neighbors(idx):
    row, col = divmod(idx, MS_COLS)
    out = []
    for r in range(max(0, row - 1), min(MS_ROWS, row + 2)):
        for c in range(max(0, col - 1), min(MS_COLS, col + 2)):
            if (r, c) != (row, col):
                out.append(r * MS_COLS + c)
    return out


class MinesweeperView(discord.ui.View):
    def __init__(self, player: discord.User, mine_count: int = MS_MINES):
        super().__init__(timeout=300)
        self.player = player
        self.mine_count = mine_count
        self.mines = set()
        self.revealed = set()
        self.flags = set()
        self.over = False
        self.won = False
        self.flag_mode = False
        self.started = False
        self._build_board()
        self._build_controls()

    def _build_board(self):
        for idx in range(MS_CELLS):
            self.add_item(MinesweeperButton(idx, self, idx // MS_COLS))

    def _build_controls(self):
        flag = _MinesweeperFlagButton(self)
        flag.row = MS_ROWS
        self.add_item(flag)
        new_game = _MinesweeperNewGameButton(self)
        new_game.row = MS_ROWS
        self.add_item(new_game)

    def _place_mines(self, safe_idx):
        pool = [i for i in range(MS_CELLS) if i != safe_idx]
        zone = {safe_idx} | set(_ms_neighbors(safe_idx))
        zone_pool = [i for i in pool if i not in zone]
        if len(zone_pool) >= self.mine_count:
            pool = zone_pool
        self.mines = set(random.sample(pool, self.mine_count))

    def _adjacent_mines(self, idx):
        return sum(1 for n in _ms_neighbors(idx) if n in self.mines)

    def _reveal(self, idx):
        if self.over or self.won:
            return
        if idx in self.flags:
            return
        if not self.started:
            self._place_mines(idx)
            self.started = True
        if idx in self.mines:
            self.over = True
            return
        if idx in self.revealed:
            return
        count = self._adjacent_mines(idx)
        self.revealed.add(idx)
        if count == 0:
            for n in _ms_neighbors(idx):
                if n not in self.revealed and n not in self.flags and n not in self.mines:
                    self._reveal(n)

    def _check_win(self):
        safe = MS_CELLS - self.mine_count
        if len(self.revealed) == safe:
            self.won = True

    def _state_embed(self):
        if self.over:
            title = "💥 You hit a mine!"
            color = discord.Color(0xe74c3c)
        elif self.won:
            title = "🎉 You cleared the field!"
            color = discord.Color(0x2ecc71)
        else:
            title = "💣 Minesweeper"
            color = discord.Color(VOIDWAVE_COLOR)

        flag_state = "On 🚩" if self.flag_mode else "Off"
        description = (
            f"> Reveal every safe cell without hitting a mine.\n"
            f"> **Mines:** {self.mine_count} **| Flags:** {len(self.flags)}/{self.mine_count} **| Flag mode:** {flag_state}"
        )
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text="Vote for 2x XP! /vote")
        return embed

    def _render(self):
        over = self.over or self.won
        for child in self.children:
            if isinstance(child, MinesweeperButton):
                child.disabled = over
                idx = child.idx
                if self.over:
                    if idx in self.mines:
                        child.label = "💣"
                        child.style = discord.ButtonStyle.danger
                    else:
                        count = self._adjacent_mines(idx)
                        child.label = MS_NUM_EMOJI.get(count) or "⬜"
                        if idx in self.revealed:
                            child.style = discord.ButtonStyle.success if count == 0 else discord.ButtonStyle.primary
                        else:
                            child.style = discord.ButtonStyle.secondary
                elif idx in self.flags and idx not in self.revealed:
                    child.label = "🚩"
                    child.style = discord.ButtonStyle.secondary
                elif idx in self.revealed:
                    count = self._adjacent_mines(idx)
                    child.label = MS_NUM_EMOJI.get(count) or "⬜"
                    child.style = discord.ButtonStyle.success if count == 0 else discord.ButtonStyle.primary
                else:
                    child.label = "⬜"
                    child.style = discord.ButtonStyle.secondary
            elif isinstance(child, _MinesweeperFlagButton):
                child.disabled = over
                child.label = "🚩 Flag: On" if self.flag_mode else "🚩 Flag: Off"
                child.style = discord.ButtonStyle.success if self.flag_mode else discord.ButtonStyle.secondary

    async def _handle_cell(self, interaction: discord.Interaction, idx: int):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        if self.over or self.won:
            return
        if self.flag_mode:
            if idx in self.revealed:
                await interaction.response.send_message("That cell is already revealed.", ephemeral=True)
                return
            if idx in self.flags:
                self.flags.discard(idx)
                await self._update(interaction)
                return
            if len(self.flags) < self.mine_count:
                self.flags.add(idx)
                await self._update(interaction)
                return
            await interaction.response.send_message("You've placed all your flags.", ephemeral=True)
            return
        self._reveal(idx)
        self._check_win()
        await self._update(interaction)

    async def _toggle_flag_mode(self, interaction: discord.Interaction):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        if self.over or self.won:
            return
        self.flag_mode = not self.flag_mode
        await self._update(interaction)

    async def _new_game(self, interaction: discord.Interaction):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        self.mines = set()
        self.revealed = set()
        self.flags = set()
        self.over = False
        self.won = False
        self.started = False
        await self._update(interaction)

    async def _update(self, interaction: discord.Interaction):
        self._render()
        await interaction.response.edit_message(embed=self._state_embed(), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class MinesweeperButton(discord.ui.Button):
    def __init__(self, idx, view, row):
        super().__init__(label="⬜", style=discord.ButtonStyle.secondary, row=row)
        self.idx = idx
        self.host_view = view

    async def callback(self, interaction: discord.Interaction):
        await self.host_view._handle_cell(interaction, self.idx)


class _MinesweeperFlagButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="🚩 Flag: Off", style=discord.ButtonStyle.secondary)
        self.host_view = view

    async def callback(self, interaction: discord.Interaction):
        await self.host_view._toggle_flag_mode(interaction)


class _MinesweeperNewGameButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="🔄 New Game", style=discord.ButtonStyle.secondary)
        self.host_view = view

    async def callback(self, interaction: discord.Interaction):
        await self.host_view._new_game(interaction)


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
                f"> **🎱:** {random.choice(EIGHT_BALL_RESPONSES)}"
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
        await interaction.response.send_message(embed=embed, ephemeral=hidden, view=RPSView(interaction.user))

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

        fetched = await TriviaView.fetch_question()
        if not fetched:
            await interaction.followup.send("> Could not fetch a trivia question. Please try again later.")
            return

        question, options, correct = fetched

        embed = discord.Embed(
            title="❓ Trivia",
            description=f"**{question}**\n\nSelect an answer below!",
            color=discord.Color(VOIDWAVE_COLOR),
        )
        embed.set_footer(text="Vote for 2x XP! /vote")

        view = TriviaView(interaction, question, options, correct)
        await interaction.followup.send(embed=embed, view=view)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="connectfour", description="Play connect four against VoidWave.")
    @app_commands.describe(hidden="Hide the command from others")
    async def connectfour(self, interaction: discord.Interaction, hidden: bool = False):
        view = ConnectFourView(interaction.user)
        for col in range(CONNECT_FOUR_COLS):
            row = 0 if col < 4 else 1
            view.add_item(ConnectFourButton(col, view, row))
        await interaction.response.send_message(embed=view._board_embed(), ephemeral=hidden, view=view)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="hangman", description="Play hangman against VoidWave.")
    @app_commands.describe(hidden="Hide the command from others")
    async def hangman(self, interaction: discord.Interaction, hidden: bool = False):
        view = HangmanView(interaction.user)
        await interaction.response.send_message(embed=view._state_embed(), ephemeral=hidden, view=view)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="blackjack", description="Play blackjack against VoidWave.")
    @app_commands.describe(hidden="Hide the command from others")
    async def blackjack(self, interaction: discord.Interaction, hidden: bool = False):
        view = BlackjackView(interaction.user)
        await interaction.response.send_message(embed=view._state_embed(), ephemeral=hidden, view=view)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="wordle", description="Play a game of wordle against VoidWave.")
    @app_commands.describe(hidden="Hide the command from others")
    async def wordle(self, interaction: discord.Interaction, hidden: bool = False):
        await interaction.response.defer(ephemeral=hidden)
        view = WordleView(interaction.user)
        view.message = await interaction.followup.send(embed=view._state_embed(), view=view)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="minesweeper", description="Play a game of minesweeper against VoidWave.")
    @app_commands.describe(mines="Mine density as a percentage (default 25)", hidden="Hide the command from others")
    async def minesweeper(self, interaction: discord.Interaction, mines: int = None, hidden: bool = False):
        total = MS_CELLS
        if mines is None:
            mine_count = MS_MINES
        else:
            mine_count = round(total * mines / 100) if 0 < mines <= 100 else MS_MINES
            mine_count = min(max(mine_count, 1), total - 1)
        view = MinesweeperView(interaction.user, mine_count)
        await interaction.response.send_message(embed=view._state_embed(), ephemeral=hidden, view=view)


async def setup(bot):
    await bot.add_cog(GamesCog(bot))
