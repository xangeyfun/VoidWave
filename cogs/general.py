from discord import app_commands
from discord.ext import commands
import discord
import time
from utils import startup, get_db


class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="help", description="Get help about the bot.")
    @app_commands.describe(topic="Get help for a specific category")
    @app_commands.choices(topic=[
        app_commands.Choice(name="Leveling", value="leveling"),
        app_commands.Choice(name="Utilities", value="utilities"),
        app_commands.Choice(name="Fun", value="fun"),
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
        elif topic == "utilities":
            embed = discord.Embed(title="🔧 Utility Commands", color=discord.Color(0x7128fc))
            embed.add_field(
                name="Commands",
                value=(
                    "`/ping` - Test the bot's latency\n"
                    "`/uptime` - Check the bot's uptime and useful links\n"
                    "`/vote` - Vote for the bot on Top.gg\n"
                    "`/calc <expression>` - Simple calculator\n"
                    "`/ai <message> [stats] [hidden]` - Chat with the bot's AI\n"
                    "`/userinfo <user> [hidden]` - Get info about a user"
                ),
                inline=False
            )
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
            embed.set_footer(text="Only available to server admins")
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
                value="`/ping`, `/uptime`, `/calc`, `/ai`, `/userinfo`",
                inline=True
            )
            embed.add_field(
                name="🎉 Fun",
                value="`/flip`, `/random`, `/quote`, `/fact`, `/animal`",
                inline=True
            )
            embed.add_field(
                name="🛡️ Moderation",
                value="`/moderation purge`",
                inline=True
            )
            embed.add_field(
                name="⚙️ Configuration",
                value="`/config auto`, `/config view`, `/config help`",
                inline=True
            )
            embed.set_footer(text="Use /help topic:<category> for details • Vote for the bot! /vote")

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
            f"> Vote on DiscordBotList: <https://discordbotlist.com/bots/voidwave/upvote>",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False)
        )

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="vote", description="Vote for VoidWave!")
    async def vote(self, interaction: discord.Interaction):
        boost = None
        conn = get_db()
        try:
            cur = conn.cursor()
            boost = cur.execute("SELECT multiplier, expires_at FROM vote_boosts WHERE user_id=? AND expires_at > ?", (interaction.user.id, int(time.time()))).fetchone()
        finally:
            conn.close()

        if boost:
            minutes = int((boost["expires_at"] - time.time()) // 60)
            msg = (
                "🗳️ **Vote for VoidWave!**\n"
                f"> <https://top.gg/bot/1442229230384709752/vote>\n"
                f"> <https://discordbotlist.com/bots/voidwave/upvote>\n\n"
                f"⚡ Your **{boost['multiplier']:.1f}x XP boost** is active for another **{minutes} minute{'s' if minutes != 1 else ''}**!"
            )
        else:
            msg = (
                "🗳️ **Vote for VoidWave!**\n"
                f"> <https://top.gg/bot/1442229230384709752/vote>\n"
                f"> <https://discordbotlist.com/bots/voidwave/upvote>\n\n"
                "⚡ **Vote now to get 2x XP for 2 hours!** (3 hours on weekends)"
            )
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
