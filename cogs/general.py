import datetime
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from cogs.config import config_help_embed
from cogs.rating import send_rating_prompt
from utils import block_reply, get_db, is_blocked, startup

logger = logging.getLogger("cogs.general")


LABELS = {
    "overview": "Overview",
    "leveling": "Leveling",
    "utilities": "Utilities",
    "fun": "Fun",
    "games": "Games",
    "music": "Music",
    "reminders": "Reminders",
    "giveaways": "Giveaways",
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
    "reminders": "⏰",
    "giveaways": "🎁",
    "moderation": "🛡️",
    "configuration": "⚙️",
}

DOCUMENTED_COMMANDS = {
    "leveling": {"level", "leaderboard", "profile"},
    "utilities": {"help", "ping", "uptime", "github", "vote", "vote-remind", "ai", "aitoggle", "userinfo", "feedback", "rate"},
    "fun": {"animal", "calc", "flip", "random", "quote", "fact"},
    "games": {"8ball", "rps", "tictactoe", "connectfour", "trivia-battle", "blackjack", "hangman", "wordle", "minesweeper", "battleship", "15puzzle"},
    "music": {"music play", "music queue", "music nowplaying", "music pause", "music resume", "music skip", "music stop", "music shuffle", "music loop", "music volume", "music seek", "music lyrics", "music lyricslive", "music autoplay", "music controller", "music disconnect", "music playlist create", "music playlist add", "music playlist remove", "music playlist rename", "music playlist delete", "music playlist list", "music playlist play"},
    "reminders": {"remind create", "remind list", "remind edit", "remind delete", "remind clear", "remind timezone"},
    "giveaways": {"giveaway start", "giveaway end", "giveaway reroll", "giveaway cancel", "giveaway list"},
    "moderation": {"moderation kick", "moderation ban", "moderation unban", "moderation timeout", "moderation slowmode", "moderation lock", "moderation unlock", "moderation role add", "moderation role remove"},
    "configuration": {"config auto", "config view", "config test", "config help", "config level set_channel", "config level toggle_channel", "config level toggle_vote_announce", "config level add_role", "config level remove_role", "config qotd set_channel", "config qotd set_time", "config qotd enable", "config qotd set_role", "config qotd delete_old", "config ai toggle"},
}

DOCUMENTED_ALIASES = {
    "level": "leveling", "xp": "leveling", "lb": "leveling", "stats": "leveling",
    "ping": "utilities", "up": "utilities", "uptime": "utilities", "src": "utilities", "source": "utilities",
    "reminder": "reminders", "reminders": "reminders", "remind": "reminders",
    "giveaway": "giveaways", "giveaways": "giveaways", "gw": "giveaways",
    "calc": "fun", "calculator": "fun", "math": "fun",
    "mod": "moderation", "config": "configuration", "settings": "configuration",
    "ai": "utilities", "chat": "utilities",
}


def _check_help_docs(bot):
    registered = {cmd.qualified_name for cmd in bot.tree.walk_commands() if not getattr(cmd, "commands", None)}
    documented = {cmd for cmds in DOCUMENTED_COMMANDS.values() for cmd in cmds}
    for cmd in sorted(registered - documented):
        logger.warning("Command /%s is registered but missing from the /help menu", cmd)
    for cmd in sorted(documented - registered):
        logger.warning("Help menu documents /%s but it isn't registered (removed or renamed?)", cmd)


async def _help_topic_autocomplete(interaction, current: str):
    query = current.strip().lower().replace("/", "")
    tokens = query.split()

    def matches(text):
        lowered = text.lower()
        return all(token in lowered for token in tokens)

    choices = []
    for cat, label in LABELS.items():
        if cat == "overview":
            continue
        if matches(f"{label} {cat}"):
            choices.append(app_commands.Choice(name=f"{EMOJIS[cat]} {label} (category)", value=cat))
    for cat, cmds in DOCUMENTED_COMMANDS.items():
        for cmd in cmds:
            if matches(cmd):
                choices.append(app_commands.Choice(name=f"/{cmd}", value=cat))
    alias_cat = DOCUMENTED_ALIASES.get(query.strip())
    if alias_cat:
        for cmd in sorted(DOCUMENTED_COMMANDS[alias_cat]):
            choices.append(app_commands.Choice(name=f"/{cmd}", value=alias_cat))

    seen = set()
    out = []
    for choice in choices:
        key = (choice.name, choice.value)
        if key in seen:
            continue
        seen.add(key)
        out.append(choice)
        if len(out) >= 25:
            break
    return out


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
        for button in cog._help_buttons():
            self.add_item(button)
        close = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary, row=2)
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
        self.rating_cooldowns = {}

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
                    "`/leaderboard <sort> [global_lb] [combined]` - Server level leaderboard (toggle Separate/Combined with the buttons)\n"
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
                    "`/help [topic]` - Browse all commands (or jump to a topic)\n"
                    "`/ping` - Bot latency\n"
                    "`/uptime` - Uptime & links\n"
                    "`/github` - Source code & issues\n"
                    "`/vote` - Vote for the bot on Top.gg\n"
                    "`/vote-remind` - Toggle vote reminders\n"
                    "`/ai <message>` - Chat with the AI\n"
                    "`/aitoggle [enabled]` - Turn AI replies on or off for yourself\n"
                    "`/userinfo <user>` - Look up a user\n"
                    "`/feedback <feedback>` - Message the developers\n"
                    "`/rate` - Rate VoidWave"
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
                    "`/random <a> <b> [hidden]` - Random number between two values\n"
                    "`/quote <choice>` - A quote (Today or Random)\n"
                    "`/fact <choice>` - A daily fact (Today or Random)\n"
                    "`/animal <animal> [hidden]` - Random animal picture\n"
                    "`/calc <expression> [hidden]` - Calculator (e.g. 5×2+3, 2^10, sqrt(64))"
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
                    "Paste a YouTube, Spotify, or SoundCloud link, or search by name. Spotify plays natively (links, "
                    "albums, and playlists), and plain text searches check Spotify, SoundCloud, and YouTube (in that order) unless you "
                    "pick a specific source. The interactive player embed lets you control playback without commands. "
                    "The player embed always shows the track's source (YouTube/Spotify/SoundCloud) and who added it; "
                    "autoplay tracks are tagged as such. "
                    "The progress bar updates live. Skips are decided by vote (or owner can force-skip)."
                ),
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Interactive Player Controls",
                value=(
                    "When music plays, an embed with buttons appears:\n"
                    "🔀 Shuffle · ⏮ Prev · ⏯ Pause/Resume · ⏭ Next · 🔁 Loop\n"
                    "👋 Leave · 📜 Queue (remove/clear) · 📝 Lyrics · 🎤 Live Lyrics · ✨ Autoplay"
                ),
                inline=False,
            ).add_field(
                name="Slash Commands",
                value=(
                    "`/music play <query> [source]` - Play a song or add to the queue (source: all/youtube/soundcloud/spotify)\n"
                    "`/music queue` - View the current queue\n"
                    "`/music nowplaying` - Show the current track\n"
                    "`/music pause` / `/music resume` - Pause and resume\n"
                    "`/music skip` - Skip the current track\n"
                    "`/music stop` - Stop and clear the queue\n"
                    "`/music shuffle` - Shuffle the queue\n"
                    "`/music loop <mode>` - Loop off/track/queue\n"
                    "`/music volume <level>` - Set volume (1-100)\n"
                    "`/music seek <time>` - Seek to a position (e.g. 1:30)\n"
                    "`/music lyrics` - Show lyrics for the current track\n"
                    "`/music lyricslive <on|off>` - Live synced lyrics on the player embed\n"
                    "`/music autoplay <on|off>` - Auto-play related tracks\n"
                    "`/music controller` - Bring the player controller back into view\n"
                    "`/music disconnect` - Leave the voice channel\n\n"
                    "**Idle behavior:** if the queue finishes, VoidWave waits "
                    "**3 minutes** before leaving. If the voice channel becomes empty "
                    "while music is playing, playback **pauses** and resumes when "
                    "someone joins; if nobody joins within 3 minutes it leaves."
                ),
                inline=False,
            ).add_field(
                name="Playlists",
                value=(
                    "Save and play your own track lists, available in any server:\n"
                    "`/music playlist create <name>` · Add tracks with `/music playlist add`\n"
                    "`/music playlist list [name]` · Play with `/music playlist play <name>`\n"
                    "`/music playlist remove` / `rename` / `delete`"
                ),
                inline=False,
            ),
            "reminders": discord.Embed(
                title="⏰ Reminders",
                description=(
                    "Get DM'd (or posted to a channel) at a time you choose. Times are human friendly: "
                    "`10m`, `2h`, `tomorrow 16:00`, `friday 18:30`. Recurring options include hourly, "
                    "daily, weekly, biweekly, weekdays, weekends, monthly, yearly, or a custom `every 2h`."
                ),
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Commands",
                value=(
                    "`/remind create <time> <message> [recurring] [timezone]` - Set a reminder\n"
                    "`/remind list` - List your active reminders\n"
                    "`/remind edit <id> [message] [time] [timezone]` - Edit a reminder\n"
                    "`/remind delete <id>` - Delete a reminder by ID\n"
                    "`/remind clear` - Delete all your reminders\n"
                    "`/remind timezone [timezone]` - Set your default timezone (defaults to UTC)"
                ),
                inline=False,
            ),
            "giveaways": discord.Embed(
                title="🎁 Giveaways",
                description=(
                    "Host giveaways in your server. Members enter with a button, and winners are drawn "
                    "automatically when the timer ends. Requires **Manage Server** to run the commands."
                ),
                color=discord.Color(0x7128fc),
            ).add_field(
                name="Commands",
                value=(
                    "`/giveaway start <prize> <duration> [winners] [channel] [required_role]` - Start a giveaway\n"
                    "`/giveaway list` - List active giveaways in the server\n"
                    "`/giveaway end <giveaway>` - End a giveaway early and draw winners\n"
                    "`/giveaway reroll <giveaway> [winners]` - Draw new winners for an ended giveaway\n"
                    "`/giveaway cancel <giveaway>` - Cancel a giveaway without winners"
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
            "configuration": config_help_embed("overview"),
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
            categories=["overview", "leveling", "utilities", "fun", "games", "music", "reminders", "giveaways", "moderation", "configuration"],
        )

    def _help_buttons(self):
        app_id = getattr(self.bot, "application_id", None) or (self.bot.user.id if self.bot.user else None)
        invite = discord.utils.oauth_url(app_id) if app_id else "https://voidwave.xangey.dev/"
        buttons = [
            discord.ui.Button(label="Website", style=discord.ButtonStyle.link, url="https://voidwave.xangey.dev/", emoji="🌐", row=1),
            discord.ui.Button(label="Invite", style=discord.ButtonStyle.link, url=invite, emoji="➕", row=1),
            discord.ui.Button(label="Vote", style=discord.ButtonStyle.link, url="https://top.gg/bot/1442229230384709752/vote", emoji="🗳️", row=1),
            discord.ui.Button(label="Source", style=discord.ButtonStyle.link, url="https://github.com/xangeyfun/VoidWave", emoji="📘", row=1),
        ]
        return buttons

    @commands.Cog.listener()
    async def on_ready(self):
        _check_help_docs(self.bot)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="help", description="Get help about the bot.")
    @app_commands.describe(topic="Get help for a specific category (or search a command)")
    @app_commands.autocomplete(topic=_help_topic_autocomplete)
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
            logger.info("%s (ID: %s) turned off vote reminders", interaction.user, interaction.user.id)
            return

        await interaction.response.send_message(confirm, ephemeral=True)
        logger.info("%s (ID: %s) turned on vote reminders", interaction.user, interaction.user.id)


    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="feedback", description="Send feedback to the VoidWave developers.")
    async def feedback(self, interaction: discord.Interaction, feedback: str):
        if is_blocked(interaction.user.id, "feedback"):
            await interaction.response.send_message(block_reply(interaction.user.id, "feedback", "using /feedback"), ephemeral=True)
            return

        remaining = self.feedback_cooldowns.get(interaction.user.id, 0) + 60 - time.monotonic()
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
            logger.error("Failed to relay /feedback from %s: %s", interaction.user, e)
            await interaction.followup.send("Something went wrong while sending your feedback, please try again later.", ephemeral=True)
            return

        self.feedback_cooldowns[interaction.user.id] = time.monotonic()
        await interaction.followup.send("Thank you! Your feedback has been sent straight to the VoidWave developers. 💜", ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="rate", description="Rate VoidWave.")
    async def rate(self, interaction: discord.Interaction):
        remaining = self.rating_cooldowns.get(interaction.user.id, 0) + 60 - time.monotonic()
        if remaining > 0:
            await interaction.response.send_message(f"Woah there, one rating at a time! Try again in `{remaining:.0f} seconds`.", ephemeral=True)
            return

        try:
            sent = await send_rating_prompt(self.bot, interaction.user.id, interaction.guild.name if interaction.guild else "DMs")
        except Exception as e:
            logger.error("Failed to send rating prompt to %s: %s", interaction.user.id, e)
            await interaction.response.send_message("Something went wrong while opening the rating prompt. Please try again later.", ephemeral=True)
            return

        self.rating_cooldowns[interaction.user.id] = time.monotonic()

        if sent:
            await interaction.response.send_message("Rating prompt sent to your DMs! Check your DMs to rate VoidWave. 💜", ephemeral=True)
        else:
            await interaction.response.send_message("Couldn't reach you in DMs. Open your DMs to user-installed apps and try again. 💜", ephemeral=True)


async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
