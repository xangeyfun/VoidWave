from discord import app_commands
from discord.ext import commands
import discord
import random
import time

from . import games as gm


VOIDWAVE_COLOR = gm.VOIDWAVE_COLOR
CHALLENGE_TIME = 60
TURN_TIME = 60


def _default_footer(embed):
    embed.set_footer(text="Vote for 2x XP! /vote")
    return embed


# ---------------------------------------------------------------------------
# Generic 2-player challenge flow
# ---------------------------------------------------------------------------
class ChallengeView(discord.ui.View):
    """Posts a challenge embed; on accept swaps it for the real game.

    ``build_game(challenger, challengee)`` must return ``(embed, view)``.
    """

    command_name = None
    game_name = ""

    def __init__(self, challenger, challengee, build_game):
        super().__init__(timeout=CHALLENGE_TIME)
        self.challenger = challenger
        self.challengee = challengee
        self.build_game = build_game
        self.message = None

    def _embed(self):
        embed = discord.Embed(
            title=f"{self.game_name} Challenge",
            description=(
                f"{self.challenger.mention} challenges {self.challengee.mention} "
                f"to {self.game_name}!\n\n"
                f"Accept to play, or the challenge expires <t:{int(time.time()) + CHALLENGE_TIME}:R>."
            ),
            color=VOIDWAVE_COLOR,
        )
        return _default_footer(embed)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, row=0)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.challengee.id:
            await interaction.response.send_message("Only the challenged player can accept!", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        embed, view = self.build_game(self.challenger, self.challengee)
        view.message = self.message
        self.stop()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, row=0)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        self.stop()
        embed = discord.Embed(
            title=f"{self.game_name} Challenge",
            description=f"{self.challengee.mention} declined the game. Maybe next time!",
            color=discord.Color(0x95a5a6),
        )
        _default_footer(embed)
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title=f"{self.game_name} Challenge",
            description=f"{self.challengee.mention} did not respond in time. The challenge expired.",
            color=discord.Color(0x95a5a6),
        )
        _default_footer(embed)
        try:
            await self.message.edit(embed=embed, view=None)
        except discord.HTTPException:
            pass


# ---------------------------------------------------------------------------
# Tic-Tac-Toe 1v1
# ---------------------------------------------------------------------------
EMPTY = gm.TICTACTOE_EMPTY
WIN_LINES = gm.TICTACTOE_WIN_LINES
MARKS = ["❌", "⭕"]


class TicTacToeVersusView(discord.ui.View):
    command_name = "/tictactoe"

    def __init__(self, p1, p2):
        super().__init__(timeout=TURN_TIME)
        self.players = [p1, p2]
        self.current = 0
        self.board = [EMPTY] * 9
        self.winner = None
        self.move_count = 0
        self.message = None
        for i in range(9):
            row = i // 3
            self.add_item(_TTTButton(i, self, row))

    def _embed(self, status=None):
        if self.winner == 0:
            title = "Tic-Tac-Toe"
            color = VOIDWAVE_COLOR
        elif self.winner == 1:
            title = f"{self.players[0].display_name} wins!"
            color = discord.Color(0x2ecc71)
        elif self.winner == 2:
            title = f"{self.players[1].display_name} wins!"
            color = discord.Color(0x2ecc71)
        else:
            title = "Tic-Tac-Toe"
            color = discord.Color(0xf1c40f)

        desc = (
            f"{self.players[0].mention} is **{MARKS[0]}** and {self.players[1].mention} is **{MARKS[1]}**.\n"
        )
        if status:
            desc += status + "\n"
        if self.winner is None:
            desc += f"It is **{self.players[self.current].mention}**'s turn (click a square)."
        embed = discord.Embed(title=title, description=desc, color=color)
        return _default_footer(embed)

    def _check_winner(self):
        for a, b, c in WIN_LINES:
            if self.board[a] != EMPTY and self.board[a] == self.board[b] == self.board[c]:
                return self.board[a]
        return None

    async def _move(self, interaction, index):
        if self.winner is not None:
            return
        if interaction.user.id != self.players[self.current].id:
            await interaction.response.send_message("It is not your turn yet!", ephemeral=True)
            return
        if self.board[index] != EMPTY:
            return

        self.board[index] = MARKS[self.current]
        self.move_count += 1
        result = self._check_winner()
        if result is not None:
            self.winner = self.current + 1
        elif self.move_count == 9:
            self.winner = 0  # draw
        else:
            self.current = 1 - self.current

        over = self.winner is not None
        for i, child in enumerate(self.children):
            child.label = self.board[i]
            child.disabled = self.board[i] != EMPTY or over
        if self.winner == 0 and self.move_count == 9:
            status = "It's a draw!"
        elif self.winner is not None:
            status = f"{self.players[self.winner - 1].mention} got three in a row!"
        else:
            status = None
        await interaction.response.edit_message(embed=self._embed(status), view=self)
        if over:
            self.stop()

    async def on_timeout(self):
        if self.winner is not None:
            return
        self.winner = (1 - self.current) + 1
        status = f"{self.players[self.current].mention} ran out of time. {self.players[1 - self.current].mention} wins!"
        for child in self.children:
            child.disabled = True
        await self._render_after_result(status)

    async def _render_after_result(self, status):
        if self.winner == 1:
            title = f"{self.players[0].display_name} wins!"
        elif self.winner == 2:
            title = f"{self.players[1].display_name} wins!"
        else:
            title = "Tic-Tac-Toe"
        embed = discord.Embed(
            title=title,
            description=status or "Game over.",
            color=discord.Color(0x2ecc71 if self.winner in (1, 2) else 0xf1c40f),
        )
        _default_footer(embed)
        try:
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass


class _TTTButton(discord.ui.Button):
    def __init__(self, index, view, row):
        super().__init__(label=EMPTY, style=discord.ButtonStyle.secondary, row=row)
        self.index = index
        self.host_view = view

    async def callback(self, interaction):
        await self.host_view._move(interaction, self.index)


def _ttt_build(challenger, challengee):
    view = TicTacToeVersusView(challenger, challengee)
    return view._embed(), view


# ---------------------------------------------------------------------------
# Connect Four 1v1
# ---------------------------------------------------------------------------
CF_ROWS = gm.CONNECT_FOUR_ROWS
CF_COLS = gm.CONNECT_FOUR_COLS
CF_EMPTY = gm.CONNECT_FOUR_EMPTY
CF_PIECES = [gm.CONNECT_FOUR_PLAYER, gm.CONNECT_FOUR_BOT]


class ConnectFourVersusView(discord.ui.View):
    command_name = "/connectfour"

    def __init__(self, p1, p2):
        super().__init__(timeout=TURN_TIME)
        self.players = [p1, p2]
        self.current = 0
        self.board = [[CF_EMPTY] * CF_COLS for _ in range(CF_ROWS)]
        self.winner = None
        self.move_count = 0
        self.message = None
        for col in range(CF_COLS):
            row = 0 if col < 4 else 1
            self.add_item(_CFButton(col, self, row))

    def _embed(self, status=None):
        if self.winner in (1, 2):
            title = f"{self.players[self.winner - 1].display_name} wins!"
            color = discord.Color(0x2ecc71)
        elif self.winner == 0:
            title = "Connect Four"
            color = discord.Color(0xf1c40f)
        else:
            title = "Connect Four"
            color = VOIDWAVE_COLOR

        grid = "\n".join(" ".join(row) for row in self.board)
        column_numbers = " ".join(f"{c + 1:>2}" for c in range(CF_COLS))
        desc = (
            f"{self.players[0].mention} is **{CF_PIECES[0]}** and {self.players[1].mention} is **{CF_PIECES[1]}**.\n"
        )
        if status:
            desc += status + "\n"
        if self.winner is None:
            desc += f"It is **{self.players[self.current].mention}**'s turn.\n\n"
        else:
            desc += "\n"
        desc += f"```\n{grid}\n{column_numbers}\n```"
        return _default_footer(discord.Embed(title=title, description=desc, color=color))

    def _drop(self, col, piece):
        for row in range(CF_ROWS - 1, -1, -1):
            if self.board[row][col] == CF_EMPTY:
                self.board[row][col] = piece
                return row
        return None

    def _check_winner_at(self, row, col):
        piece = self.board[row][col]
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            count = 1
            for step in (1, -1):
                r, c = row + dr * step, col + dc * step
                while 0 <= r < CF_ROWS and 0 <= c < CF_COLS and self.board[r][c] == piece:
                    count += 1
                    r += dr * step
                    c += dc * step
            if count >= 4:
                return True
        return False

    async def _move(self, interaction, col):
        if self.winner is not None:
            return
        if interaction.user.id != self.players[self.current].id:
            await interaction.response.send_message("It is not your turn yet!", ephemeral=True)
            return
        if self.board[0][col] != CF_EMPTY:
            await interaction.response.send_message("That column is full!", ephemeral=True)
            return

        row = self._drop(col, CF_PIECES[self.current])
        self.move_count += 1
        if self._check_winner_at(row, col):
            self.winner = self.current + 1
        elif self.move_count == CF_ROWS * CF_COLS:
            self.winner = 0  # draw
        else:
            self.current = 1 - self.current

        over = self.winner is not None
        for i, child in enumerate(self.children):
            if self.board[0][i] != CF_EMPTY or over:
                child.disabled = True
        if self.winner == 0:
            status = "The board is full, it's a draw!"
        elif self.winner is not None:
            status = f"{self.players[self.winner - 1].mention} connected four!"
        else:
            status = None
        await interaction.response.edit_message(embed=self._embed(status), view=self)
        if over:
            self.stop()

    async def on_timeout(self):
        if self.winner is not None:
            return
        self.winner = (1 - self.current) + 1
        status = f"{self.players[self.current].mention} ran out of time. {self.players[1 - self.current].mention} wins!"
        for child in self.children:
            child.disabled = True
        embed = self._embed(status)
        try:
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass


class _CFButton(discord.ui.Button):
    def __init__(self, col, view, row):
        super().__init__(label=str(col + 1), style=discord.ButtonStyle.primary, row=row)
        self.col = col
        self.host_view = view

    async def callback(self, interaction):
        await self.host_view._move(interaction, self.col)


def _cf_build(challenger, challengee):
    view = ConnectFourVersusView(challenger, challengee)
    return view._embed(), view


# ---------------------------------------------------------------------------
# Rock Paper Scissors 1v1
# ---------------------------------------------------------------------------
TEAM_EMOJI = gm.TEAM_EMOJI
RPS_WINS = gm.RPS_WINS
RPS_MOVES = list(RPS_WINS.keys())


class RPSVersusView(discord.ui.View):
    command_name = "/rps"

    def __init__(self, p1, p2):
        super().__init__(timeout=TURN_TIME)
        self.players = [p1, p2]
        self.picks = {p1.id: None, p2.id: None}
        self.message = None
        self._add_move_buttons()

    def _add_move_buttons(self):
        for move in RPS_MOVES:
            self.add_item(_RPSMoveButton(move, self))

    def _embed(self):
        desc = (
            f"{self.players[0].mention} vs {self.players[1].mention}.\n\n"
            f"Both players pick a move. Results revealed once both have chosen!"
        )
        return _default_footer(discord.Embed(
            title="🪨📄✂️ Rock Paper Scissors",
            description=desc,
            color=VOIDWAVE_COLOR,
        ))

    async def _pick(self, interaction, move):
        pid = interaction.user.id
        if pid not in self.picks:
            await interaction.response.send_message("You are not in this game!", ephemeral=True)
            return
        if self.picks[pid] is not None:
            await interaction.response.send_message("You already picked! Waiting for the other player...", ephemeral=True)
            return
        self.picks[pid] = move
        await interaction.response.send_message(f"Locked in **{move.title()}**. Waiting for the other player...", ephemeral=True)
        if all(v is not None for v in self.picks.values()):
            await self._reveal()

    async def _reveal(self):
        p1_move = self.picks[self.players[0].id]
        p2_move = self.picks[self.players[1].id]

        if p1_move == p2_move:
            result = "It's a tie!"
            color = discord.Color(0xf1c40f)
        elif RPS_WINS[p1_move] == p2_move:
            result = f"{self.players[0].mention} wins!"
            color = discord.Color(0x2ecc71)
        else:
            result = f"{self.players[1].mention} wins!"
            color = discord.Color(0x2ecc71)

        embed = discord.Embed(
            title="🪨📄✂️ Rock Paper Scissors",
            description=(
                f"{TEAM_EMOJI[p1_move]} **{self.players[0].display_name}** - **{p1_move.title()}**\n"
                f"{TEAM_EMOJI[p2_move]} **{self.players[1].display_name}** - **{p2_move.title()}**\n\n"
                f"**{result}**"
            ),
            color=color,
        )
        _default_footer(embed)
        for child in self.children:
            child.disabled = True
        await self.message.edit(embed=embed, view=self)
        self.revealed = True
        self.stop()

    async def on_timeout(self):
        if getattr(self, "revealed", False):
            return
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="🪨📄✂️ Rock Paper Scissors",
            description="The game timed out because someone did not pick a move.",
            color=discord.Color(0x95a5a6),
        )
        _default_footer(embed)
        try:
            await self.message.edit(embed=embed, view=None)
        except discord.HTTPException:
            pass


class _RPSMoveButton(discord.ui.Button):
    def __init__(self, move, view):
        super().__init__(emoji=TEAM_EMOJI[move], style=discord.ButtonStyle.secondary)
        self.move = move
        self.host_view = view

    async def callback(self, interaction):
        await self.host_view._pick(interaction, self.move)


def _rps_build(challenger, challengee):
    view = RPSVersusView(challenger, challengee)
    return view._embed(), view


# ---------------------------------------------------------------------------
# Multiplayer Blackjack (lobby + shared hands vs dealer)
# ---------------------------------------------------------------------------
MAX_BLACKJACK_PLAYERS = 4


class BlackjackLobbyView(discord.ui.View):
    command_name = "/blackjack"

    def __init__(self, interaction, max_players=MAX_BLACKJACK_PLAYERS):
        super().__init__(timeout=120)
        self.interaction = interaction
        self.host = interaction.user
        self.players = [interaction.user]
        self.max_players = min(max_players, MAX_BLACKJACK_PLAYERS)
        self.started = False
        self.add_item(_BJJoinButton(self))
        self.add_item(_BJLeaveButton(self))
        self.add_item(_BJStartButton(self))

    def _embed(self):
        players = "\n".join(
            f"{p.mention}" + (" *(host)*" if p.id == self.host.id else "")
            for p in self.players
        )
        desc = (
            f"**{self.host.mention}** is hosting multiplayer blackjack!\n\n"
            f"**Players ({len(self.players)}/{self.max_players})**\n\n"
            f"{players}\n\n"
            f"Everyone plays their own hand against the dealer.\n\n"
            f"Click **Join** to enter. The host starts, or the game auto-starts when the table is full."
        )
        return _default_footer(discord.Embed(
            title="🃏 Blackjack",
            description=desc,
            color=VOIDWAVE_COLOR,
        ))

    async def _join(self, interaction):
        if self.started:
            await interaction.response.send_message("The game has already started!", ephemeral=True)
            return
        if interaction.user.id in [p.id for p in self.players]:
            await interaction.response.send_message("You are already in!", ephemeral=True)
            return
        if len(self.players) >= self.max_players:
            await interaction.response.send_message(f"This game is full ({self.max_players} players)!", ephemeral=True)
            return
        self.players.append(interaction.user)
        if len(self.players) >= self.max_players:
            await self._begin(interaction)
        else:
            await interaction.response.edit_message(embed=self._embed(), view=self)

    async def _leave(self, interaction):
        if self.started:
            await interaction.response.send_message("The game has already started, you cannot leave!", ephemeral=True)
            return
        if interaction.user.id == self.host.id:
            await self._host_left()
            return
        self.players = [p for p in self.players if p.id != interaction.user.id]
        await interaction.response.edit_message(embed=self._embed(), view=self)

    async def _host_left(self):
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="🃏 Blackjack",
            description="The host left, so the game was cancelled.",
            color=discord.Color(0x95a5a6),
        )
        _default_footer(embed)
        try:
            await self.interaction.edit_original_response(embed=embed, view=self)
        except discord.HTTPException:
            pass

    async def _start(self, interaction):
        if self.started:
            return
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("Only the host can start!", ephemeral=True)
            return
        if len(self.players) < 2:
            await interaction.response.send_message("You need at least 2 players!", ephemeral=True)
            return
        await self._begin(interaction)

    async def _begin(self, interaction):
        self.started = True
        for child in self.children:
            child.disabled = True
        embed, view = BlackjackVersusView.build(self.players)
        await interaction.response.edit_message(embed=embed, view=view)


class _BJJoinButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Join", style=discord.ButtonStyle.primary, row=0)
        self.host_view = view

    async def callback(self, interaction):
        await self.host_view._join(interaction)


class _BJLeaveButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Leave", style=discord.ButtonStyle.danger, row=0)
        self.host_view = view

    async def callback(self, interaction):
        await self.host_view._leave(interaction)


class _BJStartButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Start", style=discord.ButtonStyle.success, row=0)
        self.host_view = view

    async def callback(self, interaction):
        await self.host_view._start(interaction)


class BlackjackVersusView(discord.ui.View):
    command_name = "/blackjack"

    def __init__(self, players):
        super().__init__(timeout=180)
        self.players = list(players)
        self.hands = {p.id: [] for p in players}
        self.done = {p.id: False for p in players}
        self.message = None
        self.deck = gm._build_deck()
        random.shuffle(self.deck)
        self.dealer_hand = []
        self.over = False
        self._deal()
        self._add_hand_buttons()

    @classmethod
    def build(cls, players):
        view = cls(players)
        return view._embed(), view

    def _add_hand_buttons(self):
        self.add_item(_BJHandHitButton(self))
        self.add_item(_BJHandStandButton(self))

    def _deal(self):
        for p in self.players:
            self.hands[p.id] = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]

    def _embed(self):
        lines = []
        for p in self.players:
            hand = self.hands[p.id]
            value = gm._hand_value(hand)
            done = " *(done)*" if self.done[p.id] and not self.over else ""
            lines.append(f"**{p.mention}:** {' '.join(hand)} ({value}){done}")
        desc = "\n".join(lines)
        dealer_hidden = f"{self.dealer_hand[0]} ?" if not self.over else f"{' '.join(self.dealer_hand)} ({gm._hand_value(self.dealer_hand)})"
        desc += f"\n\n**Dealer:** {dealer_hidden}\n\n"
        if self.over:
            desc += self._result_block()
        else:
            desc += "Use **Hit** or **Stand** on your own hand below. The dealer plays once everyone is done."
        return _default_footer(discord.Embed(
            title="🃏 Blackjack",
            description=desc,
            color=VOIDWAVE_COLOR,
        ))

    def _result_block(self):
        dealer_val = gm._hand_value(self.dealer_hand)
        lines = []
        for p in self.players:
            val = gm._hand_value(self.hands[p.id])
            if val > 21:
                res = "Bust, VoidWave wins"
            elif dealer_val > 21:
                res = "Wins, dealer busts!"
            elif val > dealer_val:
                res = "Wins!"
            elif val < dealer_val:
                res = "Loses"
            else:
                res = "Push"
            lines.append(f"{p.mention} {res}")
        return "\n".join(lines)

    def _remaining(self):
        return [p.id for p in self.players if not self.done[p.id]]

    async def _action(self, interaction, hit):
        pid = interaction.user.id
        if pid not in self.done:
            await interaction.response.send_message("You are not in this game!", ephemeral=True)
            return
        if self.over:
            return
        if self.done[pid]:
            await interaction.response.send_message("You're all set, just wait for the dealer.", ephemeral=True)
            return
        if hit:
            self.hands[pid].append(self.deck.pop())
            if gm._hand_value(self.hands[pid]) > 21:
                self.done[pid] = True
        else:
            self.done[pid] = True

        if not self._remaining():
            self.over = True
            while gm._hand_value(self.dealer_hand) < 17:
                self.dealer_hand.append(self.deck.pop())
            for child in list(self.children):
                child.disabled = True
            await interaction.response.edit_message(embed=self._embed(), view=self)
            self.stop()
            return
        await interaction.response.edit_message(embed=self._embed(), view=self)


class _BJHandHitButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Hit", style=discord.ButtonStyle.success, row=0)
        self.host_view = view

    async def callback(self, interaction):
        await self.host_view._action(interaction, True)


class _BJHandStandButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Stand", style=discord.ButtonStyle.danger, row=0)
        self.host_view = view

    async def callback(self, interaction):
        await self.host_view._action(interaction, False)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------
def _to_member(interaction, user):
    if isinstance(user, discord.Member):
        return user
    guild = interaction.guild
    if guild:
        m = guild.get_member(user.id)
        if m:
            return m
    return user


async def _send_challenge(interaction, opponent, game_name, build, hidden):
    view = ChallengeView(interaction.user, _to_member(interaction, opponent), build)
    view.game_name = game_name
    await interaction.response.send_message(embed=view._embed(), ephemeral=hidden, view=view)
    view.message = await interaction.original_response()


class MultiplayerGamesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="tictactoe", description="Play tic-tac-toe against VoidWave or a friend.")
    @app_commands.describe(opponent="Challenge another player (leave empty to play the bot)", hidden="Hide the command from others")
    async def tictactoe(self, interaction, opponent: discord.User = None, hidden: bool = False):
        if opponent is None:
            view = gm.TicTacToeView(interaction.user)
            await interaction.response.send_message(embed=view._state_embed(), ephemeral=hidden, view=view)
            return
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("You cannot challenge yourself!", ephemeral=True)
            return
        await _send_challenge(interaction, opponent, "Tic-Tac-Toe", _ttt_build, hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="connectfour", description="Play connect four against VoidWave or a friend.")
    @app_commands.describe(opponent="Challenge another player (leave empty to play the bot)", hidden="Hide the command from others")
    async def connectfour(self, interaction, opponent: discord.User = None, hidden: bool = False):
        if opponent is None:
            view = gm.ConnectFourView(interaction.user)
            for col in range(gm.CONNECT_FOUR_COLS):
                row = 0 if col < 4 else 1
                view.add_item(gm.ConnectFourButton(col, view, row))
            await interaction.response.send_message(embed=view._board_embed(), ephemeral=hidden, view=view)
            return
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("You cannot challenge yourself!", ephemeral=True)
            return
        await _send_challenge(interaction, opponent, "Connect Four", _cf_build, hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="rps", description="Play rock, paper, scissors against VoidWave or a friend.")
    @app_commands.describe(opponent="Challenge another player (leave empty to play the bot)", hidden="Hide the command from others")
    async def rps(self, interaction, opponent: discord.User = None, hidden: bool = False):
        if opponent is None:
            embed = discord.Embed(
                title="🪨📄✂️ Rock Paper Scissors",
                description="Pick your move below!",
                color=VOIDWAVE_COLOR,
            )
            _default_footer(embed)
            await interaction.response.send_message(embed=embed, ephemeral=hidden, view=gm.RPSView(interaction.user))
            return
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("You cannot challenge yourself!", ephemeral=True)
            return
        await _send_challenge(interaction, opponent, "Rock Paper Scissors", _rps_build, hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="blackjack", description="Play blackjack against VoidWave or with friends.")
    @app_commands.describe(max_players="How many players can join (default 4, max 4)", hidden="Hide the command from others")
    async def blackjack(self, interaction, max_players: int = 4, hidden: bool = False):
        max_players = max(2, min(MAX_BLACKJACK_PLAYERS, max_players))
        view = BlackjackLobbyView(interaction, max_players=max_players)
        await interaction.response.send_message(embed=view._embed(), ephemeral=hidden, view=view)


async def setup(bot):
    await bot.add_cog(MultiplayerGamesCog(bot))
