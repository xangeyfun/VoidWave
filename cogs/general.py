import datetime
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from cogs.config import config_help_embed
from cogs.rating import send_rating_prompt
from utils import (
    VOTE_LINKS,
    VOTE_PRIMARY_LINK,
    block_reply,
    get_db,
    is_blocked,
    startup,
    vote_badge_progress,
    vote_player_info,
    vote_site_emoji,
    vote_site_rows,
    vote_site_status,
)

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
    "utilities": {"help", "ping", "uptime", "github", "vote", "vote-remind", "ai", "aitoggle", "kirkify", "userinfo", "feedback", "rate", "prefs view", "prefs private", "prefs source", "prefs autoplay"},
    "fun": {"animal", "calc", "flip", "random", "quote", "fact"},
    "games": {"8ball", "rps", "tictactoe", "connectfour", "trivia-battle", "blackjack", "hangman", "wordle", "minesweeper", "battleship", "15puzzle"},
    "music": {"music play", "music random", "music radio", "music queue", "music nowplaying", "music pause", "music resume", "music skip", "music stop", "music shuffle", "music loop", "music volume", "music seek", "music lyrics", "music lyricslive", "music autoplay", "music controller", "music disconnect", "music playlist create", "music playlist add", "music playlist addcurrent", "music playlist savequeue", "music playlist remove", "music playlist rename", "music playlist delete", "music playlist list", "music playlist clear", "music playlist shuffle", "music playlist play"},
    "reminders": {"remind create", "remind list", "remind edit", "remind delete", "remind clear", "remind timezone", "remind defaults"},
    "giveaways": {"giveaway start", "giveaway end", "giveaway reroll", "giveaway cancel", "giveaway list"},
    "moderation": {"moderation kick", "moderation ban", "moderation unban", "moderation timeout", "moderation slowmode", "moderation lock", "moderation unlock", "moderation role add", "moderation role remove"},
    "configuration": {"config auto", "config view", "config test", "config help", "config level set_channel", "config level toggle_channel", "config level toggle_ping", "config level toggle_vote_announce", "config level add_role", "config level remove_role", "config qotd set_channel", "config qotd set_time", "config qotd enable", "config qotd set_role", "config qotd delete_old", "config ai toggle"},
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


def _check_help_docs(bot, cog):
    registered = {cmd.qualified_name for cmd in bot.tree.walk_commands() if not getattr(cmd, "commands", None)}
    documented = {cmd for cmds in DOCUMENTED_COMMANDS.values() for cmd in cmds}
    for cmd in sorted(registered - documented):
        logger.warning("Command /%s is registered but missing from the /help menu", cmd)
    for cmd in sorted(documented - registered):
        logger.warning("Help menu documents /%s but it isn't registered (removed or renamed?)", cmd)
    for cat in LABELS:
        try:
            embed = cog._help_embed(cat)
        except Exception:
            logger.warning("Help embed for '%s' failed to build", cat, exc_info=True)
            continue
        if len(embed.title or "") > 256:
            logger.warning("Help embed '%s' title is %s chars (limit 256)", cat, len(embed.title))
        if len(embed.description or "") > 4096:
            logger.warning("Help embed '%s' description is %s chars (limit 4096)", cat, len(embed.description or ""))
        for field in embed.fields:
            if len(field.value) > 1024:
                logger.warning("Help embed '%s' field '%s' is %s chars (limit 1024)", cat, field.name, len(field.value))


def _resolve_topic(text):
    query = text.strip().lower().replace("/", "")
    if not query:
        return None
    if query in LABELS:
        return query
    for cat, label in LABELS.items():
        if query == label.lower():
            return cat
    alias = DOCUMENTED_ALIASES.get(query)
    if alias:
        return alias
    for cat, cmds in DOCUMENTED_COMMANDS.items():
        if query in cmds:
            return cat
    return None


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
                    f"> <{VOTE_PRIMARY_LINK}> Vote for 2x XP (both lists)"
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
                    "`/leaderboard <sort> [period] [global_lb] [combined]` - Server level leaderboard (period: All Time/Daily/Weekly/Monthly; toggle Separate/Combined with the buttons)\n"
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
                    "`/vote` - Vote on Top.gg and Discord List for 2x XP\n"
                    "`/vote-remind` - Toggle vote reminders\n"
                    "`/ai <message>` - Chat with the AI\n"
                    "`/aitoggle [enabled]` - Turn AI replies on or off for yourself\n"
                    "`/kirkify <image> [hidden]` - Kirkify an image with AI (Kirk swap)\n"
                    "`/userinfo <user>` - Look up a user (account, roles, server, permissions, profile)\n"
                    "`/feedback <feedback>` - Message the developers\n"
                    "`/rate` - Rate VoidWave\n"
                    "`/prefs` - Your defaults: private replies, music source, autoplay on play"
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
                    "`/music play <query> [source]` - Play or queue a song (all/youtube/soundcloud/spotify)\n"
                    "`/music random [genre] [source]` - Queue a random track, optionally by genre\n"
                    "`/music radio <query> [source]` - Start an endless radio station from a seed\n"
                    "`/music queue` - View the queue\n"
                    "`/music nowplaying` - Show the current track\n"
                    "`/music pause` / `resume` - Pause and resume\n"
                    "`/music skip` - Skip the current track\n"
                    "`/music stop` - Stop and clear the queue\n"
                    "`/music shuffle` - Shuffle the queue\n"
                    "`/music loop <mode>` - Loop off/track/queue\n"
                    "`/music volume <level>` - Volume (1-100)\n"
                    "`/music seek <time>` - Seek to a position (1:30)\n"
                    "`/music lyrics` - Lyrics for the current track\n"
                    "`/music lyricslive <on|off>` - Live synced lyrics on the player\n"
                    "`/music autoplay <on|off>` - Auto-play related tracks\n"
                    "`/music controller` - Re-open the player controller\n"
                    "`/music disconnect` - Leave the voice channel\n\n"
                    "**Idle:** auto-leaves 3 min after the queue ends; pauses when the channel "
                    "empties and resumes on rejoin (leaves after 3 min)."
                ),
                inline=False,
            ).add_field(
                name="Playlists",
                value=(
                    "Save and play your own track lists, available in any server.\n"
                    "`/music playlist add` accepts a track, or a full playlist/album URL to bulk import.\n"
                    "`/music playlist list [name]` opens a manager to play, reorder, or remove tracks.\n"
                    "`/music playlist addcurrent` saves the current track · `savequeue` saves your queue.\n"
                    "`/music playlist remove` (by title or number) / `clear` / `shuffle` / `rename` / `delete`"
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
                    "`/remind create <message> [time] [recurring] [timezone]` - Set a reminder (time can use your saved default)\n"
                    "`/remind list` - List your active reminders\n"
                    "`/remind edit <id> [message] [time] [timezone]` - Edit a reminder\n"
                    "`/remind delete <id>` - Delete a reminder by ID\n"
                    "`/remind clear` - Delete all your reminders\n"
                    "`/remind timezone [timezone]` - Set your default timezone (defaults to UTC)\n"
                    "`/remind defaults [timezone] [recurring] [time] [channel]` - View/set your defaults (zone, repeat, time of day, delivery channel)"
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
            categories=list(LABELS),
        )

    def _help_buttons(self):
        app_id = getattr(self.bot, "application_id", None) or (self.bot.user.id if self.bot.user else None)
        invite = discord.utils.oauth_url(app_id) if app_id else "https://voidwave.xangey.dev/"
        buttons = [
            discord.ui.Button(label="Website", style=discord.ButtonStyle.link, url="https://voidwave.xangey.dev/", emoji="🌐", row=1),
            discord.ui.Button(label="Invite", style=discord.ButtonStyle.link, url=invite, emoji="➕", row=1),
            discord.ui.Button(label="Vote", style=discord.ButtonStyle.link, url=VOTE_PRIMARY_LINK, emoji="🗳️", row=1),
            discord.ui.Button(label="Source", style=discord.ButtonStyle.link, url="https://github.com/xangeyfun/VoidWave", emoji="📘", row=1),
        ]
        return buttons

    @commands.Cog.listener()
    async def on_ready(self):
        _check_help_docs(self.bot, self)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="help", description="Get help about the bot.")
    @app_commands.describe(topic="Get help for a specific category (or search a command)")
    @app_commands.autocomplete(topic=_help_topic_autocomplete)
    async def help_command(self, interaction: discord.Interaction, topic: str = None):
        if not topic:
            embed = self._help_embed("overview")
            view = HelpView(self, self._help_select("overview"))
            view.author_id = interaction.user.id
            await interaction.response.send_message(embed=embed, ephemeral=True, view=view)
            return
        category = _resolve_topic(topic)
        if category is None:
            labels = ", ".join(LABELS.values())
            await interaction.response.send_message(
                f"I don't have a help topic for `{topic.strip()}`. Try one of: {labels}, "
                "or run `/help` to browse the menu.",
                ephemeral=True,
            )
            return
        embed = self._help_embed(category)
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
            f"> Vote on Discord List: <https://discordlist.gg/bot/1442229230384709752/vote>",
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
        vote_count = 0
        conn = get_db()
        try:
            cur = conn.cursor()
            row = cur.execute("SELECT multiplier, expires_at, vote_count FROM vote_boosts WHERE user_id=?", (interaction.user.id,)).fetchone()
            if row:
                vote_count = row["vote_count"] or 0
                if row["expires_at"] and row["expires_at"] > time.time():
                    boost = row
            reminder = cur.execute("SELECT remind_at FROM vote_reminders WHERE user_id=?", (interaction.user.id,)).fetchone()
        finally:
            conn.close()

        info = vote_player_info(interaction.user.id)

        if boost:
            minutes = int((boost["expires_at"] - time.time()) // 60)
            boost_value = (
                f"**{boost['multiplier']:.1f}x XP** active for **{minutes} minute{'s' if minutes != 1 else ''}**\n"
                "More votes stack more time."
            )
        else:
            boost_value = (
                "**Not active.** Vote now for **2x XP** for 4 hours (6 on top.gg weekends).\n"
                "Votes on both lists stack."
            )

        stats_bits = []
        if vote_count:
            stats_bits.append(f"**{vote_count} vote{'s' if vote_count != 1 else ''}** lifetime")
        else:
            stats_bits.append("No votes yet")
        stats_bits.append(info["badge"] or "No badge yet")
        progress = vote_badge_progress(vote_count)
        if progress:
            stats_bits.append(f"{progress['remaining']} more to {progress['label']}")
        else:
            stats_bits.append("Top badge reached")
        if info["streak"] >= 2:
            streak_bit = f"🔥 **{info['streak']} day streak**"
            if info["longest_streak"] > info["streak"]:
                streak_bit += f" (best {info['longest_streak']})"
            stats_bits.append(streak_bit)
        else:
            stats_bits.append("Streak starts at 2 days in a row")

        site_lines = []
        for name, url, ready_at in vote_site_status(interaction.user.id):
            emoji = vote_site_emoji(name)
            prefix = f"<:{emoji[0]}:{emoji[1]}> " if emoji else ""
            timer = f"ready <t:{int(ready_at)}:R>" if ready_at else "**ready now**"
            site_lines.append(f"> {prefix}**{name}** · {timer}\n> <{url}>")

        embed = discord.Embed(
            title="🗳️ Vote for VoidWave",
            description=(
                "Voting is free, takes a few seconds, and helps more servers find VoidWave. "
                "Every vote doubles XP on **messages and voice** for 4 hours, and votes on both lists stack."
            ),
            color=0x7128fc,
        )
        embed.add_field(name="⚡ Your boost", value=boost_value, inline=True)
        embed.add_field(name="🎖️ Your stats", value="\n".join(stats_bits), inline=True)
        embed.add_field(name="🗳️ Vote now", value="\n".join(site_lines), inline=False)
        if reminder and reminder["remind_at"]:
            embed.add_field(
                name="⏰ Reminder",
                value=f"You'll get a DM when your first list is ready again (<t:{reminder['remind_at']}:R>).",
                inline=False,
            )
        else:
            embed.add_field(
                name="⏰ Never miss a vote",
                value="Run `/vote-remind` and I'll DM you when a list is ready again.",
                inline=False,
            )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="Both lists count · stack both · 4h each (6h Top.gg weekends)")
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

        view = discord.ui.View()
        for name, url, emoji in VOTE_LINKS:
            view.add_item(discord.ui.Button(
                label=name, url=url, emoji=discord.PartialEmoji(name=emoji[0], id=emoji[1])
            ))
        view.add_item(discord.ui.Button(label="Top voters", url=VOTE_PRIMARY_LINK, emoji="🏆"))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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
                history = vote_site_rows(interaction.user.id)

                if not history:
                    remind_at = now + 12 * 3600
                    confirm = f"⏰ Got it! I'll DM you **12 hours** from now (<t:{remind_at}:R>). Vote any time before then and I'll sync the reminder to your lists."
                else:
                    nexts = [
                        ready_at
                        for _, _, ready_at in vote_site_status(interaction.user.id, now)
                        if ready_at
                    ]
                    if nexts:
                        remind_at = min(nexts)
                        confirm = f"⏰ Got it! I'll DM you as soon as your first list is ready again (<t:{remind_at}:R>). Each list has its own 12 hour cooldown."
                    else:
                        remind_at = now + 60
                        confirm = "⏰ Your vote cooldown is already over! I'll DM you in about a minute so you can vote again."

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
