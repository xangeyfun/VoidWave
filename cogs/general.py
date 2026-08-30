from discord import app_commands
from discord.ext import commands
import discord
import time
import datetime
from utils import startup, get_db, is_blocked, block_reply


class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.feedback_cooldowns = {}

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="help", description="Get help about the bot.")
    @app_commands.describe(topic="Get help for a specific category")
    @app_commands.choices(topic=[
        app_commands.Choice(name="Leveling", value="leveling"),
        app_commands.Choice(name="Utilities", value="utilities"),
        app_commands.Choice(name="Fun", value="fun"),
        app_commands.Choice(name="Games", value="games"),
        app_commands.Choice(name="Moderation", value="moderation"),
        app_commands.Choice(name="Configuration", value="configuration"),
    ])
    async def help_command(self, interaction: discord.Interaction, topic: str = None):
        if topic == "leveling":
            embed = discord.Embed(title="📊 Leveling Commands", color=discord.Color(0x7128fc))
            embed.add_field(
                name="Commands",
                value=(
                    "`/level [user] [hidden]` - Check your server level\n"
                    "`/leaderboard <sort> [global_lb]` - Check the server level leaderboard\n"
                    "`/profile [user]` - Check your profile"
                ),
                inline=False
            )
            embed.set_footer(text="Vote for 2x XP! /vote")
        elif topic == "utilities":
            embed = discord.Embed(title="🔧 Utility Commands", color=discord.Color(0x7128fc))
            embed.add_field(
                name="Commands",
                value=(
                    "`/ping` - Test the bot's latency\n"
                    "`/uptime` - Check the bot's uptime and useful links\n"
                    "`/github` - View the source code and report issues\n"
                    "`/vote` - Vote for the bot on Top.gg\n"
                    "`/vote-remind` - Toggle vote reminders\n"
                    "`/calc <expression>` - Simple calculator\n"
                    "`/ai <message> [stats] [hidden]` - Chat with the bot's AI\n"
                    "`/userinfo <user> [hidden]` - Get info about a user\n"
                    "`/feedback <feedback>` - Send feedback to the developers"
                ),
                inline=False
            )
            embed.set_footer(text="Vote for 2x XP! /vote")
        elif topic == "fun":
            embed = discord.Embed(title="🎉 Fun Commands", color=discord.Color(0x7128fc))
            embed.add_field(
                name="Commands",
                value=(
                    "`/flip [hidden]` - Flip a coin\n"
                    "`/random <int> <int> [hidden]` - Generate a random number\n"
                    "`/quote <choice>` - Get a quote (Today or Random)\n"
                    "`/fact <choice>` - Get a daily fact (Today or Random)\n"
                    "`/animal <animal> [hidden]` - Get a random animal picture"
                ),
                inline=False
            )
            embed.set_footer(text="Vote for 2x XP! /vote")
        elif topic == "games":
            embed = discord.Embed(title="🎮 Games", color=discord.Color(0x7128fc))
            embed.add_field(
                name="Commands",
                value=(
                    "`/8ball <question>` - Ask the magic 8-ball a question\n"
                    "`/rps` - Play rock, paper, scissors against the bot\n"
                    "`/tictactoe` - Play tic-tac-toe against the bot\n"
                    "`/connectfour` - Play connect four against the bot\n"
                    "`/hangman` - Play hangman against the bot\n"
                    "`/blackjack` - Play blackjack against the bot\n"
                    "`/trivia` - Test your knowledge with a trivia question\n"
                    "`/wordle` - Guess the 5-letter word in 6 tries\n"
                    "`/minesweeper [mines]` - Clear the minefield without hitting a bomb\n"
                    "`/battleship` - Sink the enemy fleet before they sink yours\n"
                    "`/15puzzle` - Slide the tiles to solve the 15-puzzle\n"
                    "`/akinator <theme>` - Let VoidWave guess what you're thinking of"
                ),
                inline=False
            )
            embed.set_footer(text="Vote for 2x XP! /vote")
        elif topic == "moderation":
            embed = discord.Embed(title="🛡️ Moderation Commands", color=discord.Color(0x7128fc))
            embed.add_field(
                name="Commands",
                value=(
                    "`/moderation kick <member> [reason]` - Kick a member\n"
                    "`/moderation ban <member> [delete_days] [reason]` - Ban a member\n"
                    "`/moderation unban <user> [reason]` - Unban a user by ID\n"
                    "`/moderation timeout <member> <amount> [unit] [reason]` - Timeout a member\n"
                    "`/moderation slowmode <seconds> [channel]` - Set or clear slowmode\n"
                    "`/moderation lock [channel] [reason]` - Lock a channel\n"
                    "`/moderation unlock [channel]` - Unlock a channel\n"
                    "`/moderation role add/remove <member> <role>` - Manage a member's roles"
                ),
                inline=False
            )
            embed.set_footer(text="Requires the matching permission, granted to moderators • Vote for 2x XP! /vote")
        elif topic == "configuration":
            embed = discord.Embed(title="⚙️ Configuration Commands", color=discord.Color(0x7128fc))
            embed.add_field(
                name="Commands",
                value=(
                    "`/config auto [level] [qotd]` - Automatically set up features\n"
                    "`/config view` - View current configuration\n"
                    "`/config help` - View all configuration commands"
                ),
                inline=False
            )
            embed.set_footer(text="Only available to server admins • Vote for 2x XP! /vote")
        else:
            embed = discord.Embed(
                title="VoidWave Help",
                description="Select a category below or use `/help topic:<category>` for details.",
                color=discord.Color(0x7128fc)
            )
            embed.add_field(
                name="📊 Leveling",
                value="`/level`, `/leaderboard`, `/profile`",
                inline=True
            )
            embed.add_field(
                name="🔧 Utilities",
                value="`/ping`, `/uptime`, `/github`, `/vote`, `/vote-remind`, `/calc`, `/ai`, `/userinfo`, `/feedback`",
                inline=True
            )
            embed.add_field(
                name="🎉 Fun",
                value="`/flip`, `/random`, `/quote`, `/fact`, `/animal`",
                inline=True
            )
            embed.add_field(
                name="🎮 Games",
                value="`/8ball`, `/rps`, `/tictactoe`, `/connectfour`, `/hangman`, `/blackjack`, `/trivia`, `/wordle`, `/minesweeper`, `/battleship`, `/15puzzle`, `/akinator`",
                inline=True
            )
            embed.add_field(
                name="🛡️ Moderation",
                value="`/moderation kick, ban, unban, timeout, slowmode, lock, unlock, role`",
                inline=True
            )
            embed.add_field(
                name="⚙️ Configuration",
                value="`/config auto`, `/config view`, `/config help`",
                inline=True
            )
            embed.set_footer(text="Use /help topic:<category> for details • Vote for 2x XP! /vote")

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
            boost_line = "> ⚡ **Vote now to get 2x XP for 2 hours!** (3 hours on weekends)"

        reminder_line = ""
        if reminder:
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
            name="Vote Links",
            value=(
                "> <https://top.gg/bot/1442229230384709752/vote>\n"
                "> <https://discordlist.gg/bot/1442229230384709752/vote>\n"
                "> <https://discordbotlist.com/bots/voidwave/upvote>"
            ),
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
