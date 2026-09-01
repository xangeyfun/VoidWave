from discord import app_commands
from discord.ext import commands
import discord
import time
import datetime
from utils import startup, get_db, is_blocked, block_reply


LABELS = {
    "overview": "Overview",
    "leveling": "Leveling",
    "utilities": "Utilities",
    "fun": "Fun",
    "games": "Games",
    "music": "Music",
    "moderation": "Moderation",
    "configuration": "Configuration",
}
EMOJIS = {
    "overview": "🏠",
    "leveling": "📊",
    "utilities": "🔧",
    "fun": "🎉",
    "games": "🎮",
    "music": "🎵",
    "moderation": "🛡️",
    "configuration": "⚙️",
}


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, placeholder, disabled_category, categories):
        self.disabled_category = disabled_category
        options = [
            discord.SelectOption(
                label=LABELS[cat],
                value=cat,
                emoji=EMOJIS[cat],
                default=(cat == disabled_category),
            )
            for cat in categories
        ]
        super().__init__(
            placeholder=f"{EMOJIS[disabled_category]} {LABELS[disabled_category]}",
            options=options,
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.author_id:
            await interaction.response.send_message("This help menu isn't for you.", ephemeral=True)
            return
        category = self.values[0]
        embed = self.view.cog._help_embed(category)
        self.view.cog._set_select(self, category)
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, cog, select):
        super().__init__(timeout=120)
        self.cog = cog
        self.author_id = None
        self.add_item(select)
        close = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary, row=1)
        close.callback = self._close
        self.add_item(close)

    async def _close(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This help menu isn't for you.", ephemeral=True)
            return
        await interaction.response.edit_message(view=None)
        self.stop()


class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.feedback_cooldowns = {}

    def _help_embed(self, category):
        embeds = {
            "overview": discord.Embed(
                title="VoidWave Help",
                description=(
                    "Select a category below, or run `/help topic:<category>` to jump straight to it.\n\n"
                    "Every command supports `hidden:` to keep the reply private."
                ),
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Quick links",
                value=(
                    "> <https://voidwave.xangey.dev/> Website\n"
                    "> <https://github.com/xangeyfun/VoidWave> Source & issues\n"
                    "> <https://top.gg/bot/1442229230384709752/vote> Vote for 2x XP"
                ),
                inline=False,
            ),
            "leveling": discord.Embed(
                title="📊 Leveling",
                description="Earn XP by chatting and hanging out in voice channels.",
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Commands",
                value=(
                    "`/level [user] [hidden]` - Your (or a member's) server level\n"
                    "`/leaderboard <sort> [global_lb]` - Server level leaderboard\n"
                    "`/profile [user]` - Detailed profile & stats"
                ),
                inline=False,
            ),
            "utilities": discord.Embed(
                title="🔧 Utility",
                description="Everyday tools and bot info.",
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Commands",
                value=(
                    "`/ping` - Bot latency\n"
                    "`/uptime` - Uptime & links\n"
                    "`/github` - Source code & issues\n"
                    "`/vote` - Vote for the bot on Top.gg\n"
                    "`/vote-remind` - Toggle vote reminders\n"
                    "`/calc <expression>` - Calculator\n"
                    "`/ai <message>` - Chat with the AI\n"
                    "`/userinfo <user>` - Look up a user\n"
                    "`/feedback <feedback>` - Message the developers"
                ),
                inline=False,
            ),
            "fun": discord.Embed(
                title="🎉 Fun",
                description="A bit of randomness to pass the time.",
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Commands",
                value=(
                    "`/flip [hidden]` - Flip a coin\n"
                    "`/random <int> <int> [hidden]` - Random number\n"
                    "`/quote <choice>` - A quote\n"
                    "`/fact <choice>` - A daily fact\n"
                    "`/animal <animal> [hidden]` - Random animal picture"
                ),
                inline=False,
            ),
            "games": discord.Embed(
                title="🎮 Games",
                description=(
                    "Play solo against the bot, or challenge a friend with the `opponent:` option.\n"
                    "Multiplayer challenge links expire after 60 seconds."
                ),
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Versus a friend",
                value=(
                    "`/rps [opponent]` - Rock, paper, scissors\n"
                    "`/tictactoe [opponent]` - Tic-tac-toe\n"
                    "`/connectfour [opponent]` - Connect four\n"
                    "`/trivia-battle` - Multiplayer trivia battle\n"
                    "`/blackjack [max_players]` - Multiplayer blackjack table"
                ),
            ).add_field(
                name="Solo",
                value=(
                    "`/hangman` - Guess the word\n"
                    "`/wordle` - 5-letter word in 6 tries\n"
                    "`/minesweeper [mines]` - Clear the minefield\n"
                    "`/battleship` - Sink the enemy fleet\n"
                    "`/15puzzle` - Slide-tile puzzle\n"
                    "`/8ball <question>` - Ask the 8-ball"
                ),
            ),
            "music": discord.Embed(
                title="🎵 Music",
                description=(
                    "Play music in voice channels. Join a voice channel and run `/music play`. "
                    "Control commands (skip, pause, stop...) require you to be in the same voice channel as the bot."
                ),
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Commands",
                value=(
                    "`/music play <query>` - Play a song or add to the queue\n"
                    "`/music queue` - View the current queue\n"
                    "`/music nowplaying` - Show the current track\n"
                    "`/music pause` / `/music resume` - Pause and resume\n"
                    "`/music skip` - Skip the current track\n"
                    "`/music stop` - Stop and clear the queue\n"
                    "`/music shuffle` - Shuffle the queue\n"
                    "`/music loop <mode>` - Loop off/track/queue\n"
                    "`/music volume <level>` - Set volume (1-100)\n"
                    "`/music disconnect` - Leave the voice channel"
                ),
                inline=False,
            ),
            "moderation": discord.Embed(
                title="🛡️ Moderation",
                description="Requires the matching permission (granted to moderators).",
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Commands",
                value=(
                    "`/moderation kick <member> [reason]`\n"
                    "`/moderation ban <member> [delete_days] [reason]`\n"
                    "`/moderation unban <user> [reason]`\n"
                    "`/moderation timeout <member> <amount> [unit] [reason]`\n"
                    "`/moderation slowmode <seconds> [channel]`\n"
                    "`/moderation lock [channel] [reason]`\n"
                    "`/moderation unlock [channel]`\n"
                    "`/moderation role add/remove <member> <role>`"
                ),
                inline=False,
            ),
            "configuration": discord.Embed(
                title="⚙️ Configuration",
                description="Server setup, admin only.",
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Commands",
                value=(
                    "`/config auto [level] [qotd]` - One-command setup\n"
                    "`/config view` - Show current config\n"
                    "`/config help` - All config commands"
                ),
                inline=False,
            ),
        }
        embed = embeds[category]
        embed.set_footer(text="Vote for 2x XP! /vote")
        return embed

    def _set_select(self, select, category):
        for opt in select.options:
            opt.default = (opt.value == category)
        select.placeholder = f"{EMOJIS[category]} {LABELS[category]}"

    def _help_select(self, current):
        return HelpCategorySelect(
            placeholder=current,
            disabled_category=current,
            categories=["overview", "leveling", "utilities", "fun", "games", "music", "moderation", "configuration"],
        )

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="help", description="Get help about the bot.")
    @app_commands.describe(topic="Get help for a specific category")
    @app_commands.choices(topic=[
        app_commands.Choice(name="Leveling", value="leveling"),
        app_commands.Choice(name="Utilities", value="utilities"),
        app_commands.Choice(name="Fun", value="fun"),
        app_commands.Choice(name="Games", value="games"),
        app_commands.Choice(name="Music", value="music"),
        app_commands.Choice(name="Moderation", value="moderation"),
        app_commands.Choice(name="Configuration", value="configuration"),
    ])
    async def help_command(self, interaction: discord.Interaction, topic: str = None):
        category = topic or "overview"
        embed = self._help_embed(category)
        if topic is None:
            view = HelpView(self, self._help_select(category))
            view.author_id = interaction.user.id
            await interaction.response.send_message(embed=embed, ephemeral=True, view=view)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="ping", description="Test the bot's latency.")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"Pong! {round(self.bot.latency * 1000)}ms :ping_pong:", ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="uptime", description="Check the bot's uptime.")
    async def uptime(self, interaction: discord.Interaction):
        current_time = time.time()
        uptime_seconds = int(current_time - startup)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
        await interaction.response.send_message(
            f"⏱️ **Bot Uptime**\n> {uptime_str}\n\n"
            f"🔗 **Links**\n"
            f"> Status Page: <https://status.xangey.dev/>\n"
            f"> GitHub: <https://github.com/xangeyfun/VoidWave>\n"
            f"> Website: <https://voidwave.xangey.dev/>\n"
            f"> Vote on Top.gg: <https://top.gg/bot/1442229230384709752/vote>\n"
            f"> Vote on Discord List: <https://discordlist.gg/bot/1442229230384709752/vote>\n"
            f"> Vote on DiscordBotList: <https://discordbotlist.com/bots/voidwave/upvote>",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False)
        )

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="github", description="View the source code and report issues")
    async def github(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "> **GitHub** <https://github.com/xangeyfun/VoidWave>\n\n"
            "Open an issue to report a bug or request a feature, or submit a pull request to contribute.",
            ephemeral=True
        )

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="vote", description="Vote for VoidWave!")
    async def vote(self, interaction: discord.Interaction):
        boost = None
        reminder = None
        conn = get_db()
        try:
            cur = conn.cursor()
            boost = cur.execute("SELECT multiplier, expires_at FROM vote_boosts WHERE user_id=? AND expires_at > ?", (interaction.user.id, int(time.time()))).fetchone()
            reminder = cur.execute("SELECT remind_at FROM vote_reminders WHERE user_id=?", (interaction.user.id,)).fetchone()
        finally:
            conn.close()

        if boost:
            minutes = int((boost["expires_at"] - time.time()) // 60)
            boost_line = f"> ⚡ Your **{boost['multiplier']:.1f}x XP boost** is active for another **{minutes} minute{'s' if minutes != 1 else ''}**!"
        else:
            boost_line = "> ⚡ **Vote now to get 2x XP for 4 hours!** (6 hours on weekends)"

        reminder_line = ""
        if reminder and reminder["remind_at"]:
            reminder_line = f"\n> ⏰ Reminder set! I'll DM you when it's time to vote again (<t:{reminder['remind_at']}:R>)."

        embed = discord.Embed(
            title="🗳️ Vote for VoidWave!",
            description=(
                "Voting is free, takes 5 seconds, and helps VoidWave reach more servers. 🚀\n\n"
                f"{boost_line}{reminder_line}"
            ),
            color=0x7128fc,
        )
        embed.add_field(
            name="Vote Link",
            value="> <https://top.gg/bot/1442229230384709752/vote>",
            inline=False,
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="Vote for 2x XP! /vote")
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="vote-remind", description="Get a DM when you can vote for VoidWave again.")
    @app_commands.describe(enabled="Turn reminders on or off (leave out to toggle)")
    async def vote_remind(self, interaction: discord.Interaction, enabled: bool = None):
        confirm = None
        conn = get_db()
        try:
            cur = conn.cursor()
            row = cur.execute("SELECT remind_at FROM vote_reminders WHERE user_id=?", (interaction.user.id,)).fetchone()
            turn_on = enabled if enabled is not None else row is None

            if turn_on:
                now = int(time.time())
                boost = cur.execute("SELECT last_vote_at FROM vote_boosts WHERE user_id=?", (interaction.user.id,)).fetchone()
                last_vote = boost["last_vote_at"] if boost else None

                if last_vote is None:
                    remind_at = now + 12 * 3600
                    confirm = f"⏰ Got it! I'll DM you **12 hours** from now (<t:{remind_at}:R>). Once you vote, reminders stay synced to your most recent vote."
                else:
                    remind_at = max(last_vote + 12 * 3600, now + 60)
                    if last_vote + 12 * 3600 <= now:
                        confirm = "⏰ Your Top.gg cooldown is already over! I'll DM you in about a minute so you can vote again."
                    else:
                        confirm = f"⏰ Got it! Your Top.gg cooldown ends <t:{remind_at}:R>, and I'll DM you then."

                cur.execute(
                    "INSERT INTO vote_reminders (user_id, remind_at) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET remind_at = excluded.remind_at",
                    (interaction.user.id, remind_at),
                )
            else:
                cur.execute("DELETE FROM vote_reminders WHERE user_id=?", (interaction.user.id,))
            conn.commit()
        finally:
            conn.close()

        if not turn_on:
            await interaction.response.send_message("🔕 Vote reminders are now off. Run `/vote-remind` any time to turn them back on.", ephemeral=True)
            return

        await interaction.response.send_message(confirm, ephemeral=True)


    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="feedback", description="Send feedback to the VoidWave developers.")
    async def feedback(self, interaction: discord.Interaction, feedback: str):
        if is_blocked(interaction.user.id, "feedback"):
            await interaction.response.send_message(block_reply(interaction.user.id, "feedback", "using /feedback"), ephemeral=True)
            return

        remaining = self.feedback_cooldowns.get(interaction.user.id, 0) + 60 - time.time()
        if remaining > 0:
            await interaction.response.send_message(f"Slow down! You can send feedback again in `{remaining:.0f} seconds`.", ephemeral=True)
            return

        if not feedback.strip():
            await interaction.response.send_message("Please include some actual feedback in your message.", ephemeral=True)
            return

        channel = self.bot.get_channel(1540471117557403648)
        if not channel:
            await interaction.response.send_message("Feedback is unavailable right now, please try again later.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="💡 New feedback via /feedback",
            description=feedback[:4000],
            color=0x7128fc,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="From", value=f"{interaction.user} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Sent from", value=interaction.guild.name if interaction.guild else "DMs", inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="VoidWave • /feedback")

        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ERROR  Failed to relay /feedback from {interaction.user}: {e}")
            await interaction.followup.send("Something went wrong while sending your feedback, please try again later.", ephemeral=True)
            return

        self.feedback_cooldowns[interaction.user.id] = time.time()
        await interaction.followup.send("Thank you! Your feedback has been sent straight to the VoidWave developers. 💜", ephemeral=True)


async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
