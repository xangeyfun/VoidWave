import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import get_user_pref, set_user_pref

logger = logging.getLogger("cogs.prefs")

MUSIC_SOURCES = {
    "auto": "All",
    "youtube": "YouTube",
    "soundcloud": "SoundCloud",
    "spotify": "Spotify",
}

_PREF_LABELS = {
    "default_hidden": ("Private replies", lambda v: "on" if v else "off"),
    "music_source": ("Music source", lambda v: MUSIC_SOURCES.get(v or "auto", v or "auto")),
    "music_autoplay": ("Autoplay on play", lambda v: "on" if v else "off"),
    "music_volume": ("Playback volume", lambda v: f"{v}%" if v else ("30% (default)" if v is None else "off")),
    "music_autopick": ("Search auto pick", lambda v: "on" if v else "off"),
    "remind_tz": ("Reminder timezone", lambda v: v or "UTC"),
    "remind_recurring": ("Reminder repeat", lambda v: v or "none"),
    "remind_channel": ("Reminder delivery", lambda v: f"<#{v}>" if v else "your DMs"),
    "remind_time": ("Reminder time of day", lambda v: v or "none"),
}


class PrefsCog(commands.Cog):
    """Personal defaults for how VoidWave behaves towards you."""

    def __init__(self, bot):
        self.bot = bot

    prefs = app_commands.Group(
        name="prefs",
        description="Your saved defaults for how VoidWave replies to you",
        allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=True),
        allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True),
    )

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @prefs.command(name="view", description="Show your saved defaults")
    async def prefs_view(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        lines = []
        for column, (label, fmt) in _PREF_LABELS.items():
            value = get_user_pref(user_id, column)
            lines.append(f"**{label}:** `{fmt(value)}`")
        embed = discord.Embed(
            title="Your VoidWave defaults",
            description="\n".join(lines),
            color=0x7128fc,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_footer(text="Set them with /prefs, /remind defaults and /aitoggle")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @prefs.command(name="private", description="Hide your command replies from others by default")
    @app_commands.describe(enabled="on to make replies private by default, off for normal public replies")
    async def prefs_private(self, interaction: discord.Interaction, enabled: bool):
        set_user_pref(interaction.user.id, default_hidden=1 if enabled else 0)
        state = "on" if enabled else "off"
        await interaction.response.send_message(
            f"Private replies are now **{state}** by default. The `hidden:` option on most commands still overrides it for that one command.",
            ephemeral=True,
        )
        logger.info("%s set private replies to %s", interaction.user, state)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @prefs.command(name="source", description="Default music source for /music play, /music random and /music radio")
    @app_commands.describe(source="Which source to search first when playing music")
    @app_commands.choices(source=[
        app_commands.Choice(name="All", value="auto"),
        app_commands.Choice(name="YouTube", value="youtube"),
        app_commands.Choice(name="SoundCloud", value="soundcloud"),
        app_commands.Choice(name="Spotify", value="spotify"),
    ])
    async def prefs_source(self, interaction: discord.Interaction, source: str):
        set_user_pref(interaction.user.id, music_source=source)
        await interaction.response.send_message(
            f"Default music source is now **{MUSIC_SOURCES[source]}**. `/music play`, `/music random` and `/music radio` use it unless you pass a `source:` override.",
            ephemeral=True,
        )
        logger.info("%s set music source default to %s", interaction.user, source)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @prefs.command(name="autoplay", description="Turn autoplay on automatically when you start a fresh playback session")
    @app_commands.describe(enabled="on to enable autoplay when you start playback, off to leave it as-is")
    async def prefs_autoplay(self, interaction: discord.Interaction, enabled: bool):
        set_user_pref(interaction.user.id, music_autoplay=1 if enabled else 0)
        state = "on" if enabled else "off"
        await interaction.response.send_message(
            f"Autoplay will now be turned **{state}** whenever you start a fresh playback session (the queue was empty and nothing was playing).",
            ephemeral=True,
        )
        logger.info("%s set music autoplay-on-play default to %s", interaction.user, state)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @prefs.command(name="volume", description="Set the default volume applied when you start playback")
    @app_commands.describe(level="Volume from 1 to 100, or 0 to stop applying a default")
    async def prefs_volume(self, interaction: discord.Interaction, level: int):
        level = max(0, min(level, 100))
        set_user_pref(interaction.user.id, music_volume=level)
        if level:
            message = f"Default playback volume is now **{level}%**. It will be applied whenever you start a fresh playback session."
        else:
            message = "Default playback volume is now **off**. New sessions will keep the volume where it is."
        await interaction.response.send_message(message, ephemeral=True)
        logger.info("%s set music default volume to %s", interaction.user, level or "off")

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @prefs.command(name="search", description="Skip the /music play search menu and auto play the best match")
    @app_commands.describe(enabled="on to always auto pick the best result, off to show the search picker")
    async def prefs_search(self, interaction: discord.Interaction, enabled: bool):
        set_user_pref(interaction.user.id, music_autopick=1 if enabled else 0)
        if enabled:
            message = "Search auto pick is now **on**. When `/music play` finds several results, it will play the best match automatically, just like pressing the Auto button."
        else:
            message = "Search auto pick is now **off**. `/music play` will show the search picker when there are several results."
        await interaction.response.send_message(message, ephemeral=True)
        logger.info("%s set music search auto pick to %s", interaction.user, "on" if enabled else "off")


async def setup(bot):
    await bot.add_cog(PrefsCog(bot))
