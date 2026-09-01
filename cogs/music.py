from discord import app_commands
from discord.ext import commands
import discord
import asyncio
import os
import re

import wavelink

from utils import date, is_blocked, block_reply


VOIDWAVE_COLOR = 0x7128fc
QUEUE_PAGE_SIZE = 10


def fmt(len_ms):
    total = max(0, int(len_ms)) // 1000
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}:{seconds:02d}"


def _footer(embed):
    embed.set_footer(text="Vote for 2x XP! /vote")
    return embed


_KNOWN_PREFIXES = ("ytsearch:", "ytmsearch:", "scsearch:", "spsearch:", "http://", "https://")

_DASHES = str.maketrans({"—": " ", "–": " ", "-": " "})


def _clean_text(text):
    """Normalize title/author text: collapse dashes/em-dashes and whitespace."""
    if not text:
        return text
    return " ".join(text.translate(_DASHES).split())


def _best_result(query, results):
    """Pick the search result whose cleaned title overlaps the query most.

    Falls back to the first result when nothing overlaps (uncertain).
    """
    if not results:
        return None
    q_words = [
        w for w in " ".join(query.lower().translate(_DASHES).split()).split()
        if w and len(w) > 2
    ]
    if not q_words:
        return results[0]
    best = results[0]
    best_score = 0
    for r in results[:8]:
        t = _clean_text(r.title).lower()
        score = sum(1 for w in q_words if w in t)
        if score > best_score:
            best_score = score
            best = r
    return best


def _normalize_query(query: str) -> str | None:
    """Return a URL/search-identifier for wavelink, or None if not usable."""
    if not query or not query.strip():
        return None
    query = query.strip()
    low = query.lower()
    if low.startswith("query:") or low.startswith("/"):
        query = query.split(":", 1)[1].strip() if ":" in query else query
    if not query:
        return None
    if query.lower().startswith(_KNOWN_PREFIXES):
        return query
    return f"ytsearch:{query}"


class MusicCog(commands.Cog):
    """Play music in voice channels via Lavalink."""

    music = discord.app_commands.Group(
        name="music",
        description="Music playback commands",
        allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=False),
        allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False),
    )

    def __init__(self, bot):
        self.bot = bot
        self.players: dict[int, wavelink.Player] = {}
        self.skip_votes: dict[int, set[int]] = {}
        self.players_owner: dict[int, int] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _deny_if_blocked(self, interaction: discord.Interaction) -> bool:
        """Return True when the user is blocked from music and a reply was sent."""
        if is_blocked(interaction.user.id, "music"):
            await interaction.response.send_message(
                block_reply(interaction.user.id, "music", "using music commands"),
                ephemeral=True,
            )
            return True
        return False

    def _player(self, interaction: discord.Interaction) -> wavelink.Player | None:
        return self.players.get(interaction.guild_id)  # type: ignore

    def _same_vc(self, interaction: discord.Interaction, player: wavelink.Player) -> bool:
        vc = interaction.user.voice
        return bool(vc and vc.channel and player.channel and vc.channel.id == player.channel.id)

    def _reset_skip_votes(self, guild_id: int):
        self.skip_votes.pop(guild_id, None)

    async def _disconnect(self, player: wavelink.Player):
        player.queue.clear()
        if player.guild:
            self.players.pop(player.guild.id, None)
            self._reset_skip_votes(player.guild.id)
            self.players_owner.pop(player.guild.id, None)
        try:
            await player.disconnect()
        except Exception as e:
            print(f"{date()} ERROR  Failed to disconnect music player: {e}")

    # ------------------------------------------------------------------
    # Node connection
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        if wavelink.Pool.nodes:
            return
        uri = os.getenv("LAVALINK_URI", "http://localhost:2333")
        password = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
        try:
            node = wavelink.Node(uri=uri, password=password)
            await wavelink.Pool.connect(nodes=[node], client=self.bot)
        except Exception as e:
            print(f"{date()} ERROR  Failed to connect to Lavalink node at {uri}: {e}")

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        print(f"{date()} INFO  Lavalink node ready: {payload.node.uri}")

    @commands.Cog.listener()
    async def on_wavelink_node_closed(self, node, disconnected: bool):
        print(f"{date()} WARN  Lavalink node closed: {node.uri} (disconnected={disconnected})")

    # ------------------------------------------------------------------
    # Play
    # ------------------------------------------------------------------
    @music.command(name="play", description="Play a song or add it to the queue")
    @app_commands.describe(query='A URL (YouTube/Spotify/SoundCloud/etc.) or a search term', hidden="Hide the command from others")
    async def play_music(self, interaction: discord.Interaction, query: str, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return

        vc = interaction.user.voice
        if not vc or not vc.channel:
            await interaction.response.send_message("You need to be in a voice channel to play music.", ephemeral=hidden)
            return

        if not wavelink.Pool.nodes:
            await interaction.response.send_message("Music hasn't connected to the audio server yet, please try again in a moment.", ephemeral=hidden)
            return

        try:
            node = wavelink.Pool.get_node()
        except Exception as e:
            print(f"{date()} ERROR  No available Lavalink node: {e}")
            await interaction.response.send_message("Music server unavailable right now, please try again in a moment.", ephemeral=hidden)
            return
        await interaction.response.defer(ephemeral=hidden)

        player = self._player(interaction)
        if isinstance(player, wavelink.Player):
            if player.channel and player.channel.id != vc.channel.id:
                try:
                    await player.move_to(vc.channel)  # type: ignore
                except Exception as e:
                    print(f"{date()} ERROR  Failed to move music player: {e}")
                    await interaction.followup.send("I couldn't move to your voice channel. Please try again.", ephemeral=hidden)
                    return
        else:
            try:
                player = await vc.channel.connect(cls=wavelink.Player, self_deaf=True)  # type: ignore
                self.players[interaction.guild_id] = player  # type: ignore
                self.players_owner[interaction.guild_id] = interaction.user.id
            except Exception as e:
                print(f"{date()} ERROR  Failed to connect music player to voice: {e}")
                await interaction.followup.send("I couldn't join your voice channel. Please try again.", ephemeral=hidden)
                return

        try:
            normalized = _normalize_query(query)
            if normalized is None:
                await interaction.followup.send("I couldn't find anything for that query. Please try again.", ephemeral=hidden)
                return
            tracks = await wavelink.Playable.search(normalized, node=node)
        except Exception as e:
            print(f"{date()} ERROR  Music search failed: {e}")
            await interaction.followup.send("I couldn't find anything for that query. Please try again.", ephemeral=hidden)
            return

        if not tracks:
            await interaction.followup.send(f"No results found for `{query}`.", ephemeral=hidden)
            return

        if isinstance(tracks, wavelink.Playlist):
            await player.queue.put_wait(tracks.tracks)
            embed = discord.Embed(
                title="🎵 Playlist added to queue",
                description=f"**[{tracks.name}]({query})** · **{len(tracks.tracks)}** songs",
                color=VOIDWAVE_COLOR,
            )
            if tracks.tracks:
                embed.add_field(name="First up", value=f"`{tracks.tracks[0].title}`", inline=False)
                embed.set_thumbnail(url=tracks.tracks[0].artwork or None)
            _footer(embed)
            if not player.playing and tracks.tracks:
                self._reset_skip_votes(interaction.guild_id)
                await player.play(player.queue.get())
            await interaction.followup.send(embed=embed, ephemeral=hidden)
            return

        if isinstance(tracks, (list, tuple)):
            track = _best_result(query, list(tracks))
        else:
            track = tracks
        if player.playing:
            await player.queue.put_wait(track)
            embed = discord.Embed(
                title="🎵 Added to queue",
                description=f"**[{track.title}]({track.uri})**",
                color=VOIDWAVE_COLOR,
            )
            embed.set_thumbnail(url=track.artwork or None)
            embed.add_field(name="Position in queue", value=f"`#{player.queue.count}`", inline=True)
            embed.add_field(name="Length", value=f"`{fmt(track.length)}`", inline=True)
            await interaction.followup.send(embed=embed, ephemeral=hidden)
        else:
            self._reset_skip_votes(interaction.guild_id)
            await player.play(track)
            embed = discord.Embed(
                title="▶️ Now Playing",
                description=f"**[{track.title}]({track.uri})**\n\n> {track.author} • `{fmt(track.length)}`",
                color=VOIDWAVE_COLOR,
            )
            embed.set_thumbnail(url=track.artwork or None)
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            _footer(embed)
            await interaction.followup.send(embed=embed, ephemeral=hidden)

    # ------------------------------------------------------------------
    # Pause / Resume
    # ------------------------------------------------------------------
    @music.command(name="pause", description="Pause the current track")
    @app_commands.describe(hidden="Hide the command from others")
    async def pause(self, interaction: discord.Interaction, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.playing:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return
        await player.pause(True)
        await interaction.response.send_message("⏸️ Paused.", ephemeral=hidden)

    @music.command(name="resume", description="Resume the paused track")
    @app_commands.describe(hidden="Hide the command from others")
    async def resume(self, interaction: discord.Interaction, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            await interaction.response.send_message("I'm not connected to a voice channel.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return
        if not player.paused:
            await interaction.response.send_message("Nothing is paused right now.", ephemeral=hidden)
            return
        await player.pause(False)
        await interaction.response.send_message("▶️ Resumed.", ephemeral=hidden)

    # ------------------------------------------------------------------
    # Skip / Stop
    # ------------------------------------------------------------------
    @music.command(name="skip", description="Skip the current track")
    @app_commands.describe(hidden="Hide the command from others")
    async def skip(self, interaction: discord.Interaction, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.playing:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return
        current = player.current
        if not current:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=hidden)
            return

        guild_id = interaction.guild_id
        if self.players_owner.get(guild_id) == interaction.user.id:
            self._reset_skip_votes(guild_id)
            await player.skip(force=True)
            await interaction.response.send_message(f"⏭️ Skipped **{current.title}**.", ephemeral=hidden, allowed_mentions=discord.AllowedMentions.none())
            return

        listeners = [m for m in player.channel.members if not m.bot] if player.channel else []
        required = len(listeners) // 2 + 1

        votes = self.skip_votes.setdefault(guild_id, set())
        votes.add(interaction.user.id)

        if len(votes) >= required:
            self._reset_skip_votes(guild_id)
            await player.skip(force=True)
            await interaction.response.send_message(f"⏭️ Vote-to-skip passed, skipping **{current.title}**.", ephemeral=hidden, allowed_mentions=discord.AllowedMentions.none())
            return

        await interaction.response.send_message(
            f"🗳️ **{interaction.user.display_name}** wants to skip **{current.title}**. "
            f"Votes `{len(votes)}/{required}` needed to skip.",
            ephemeral=hidden,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @music.command(name="stop", description="Stop playback and clear the queue")
    @app_commands.describe(hidden="Hide the command from others")
    async def stop(self, interaction: discord.Interaction, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            await interaction.response.send_message("I'm not playing anything.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return
        player.queue.clear()
        self._reset_skip_votes(interaction.guild_id)
        await player.stop()
        await interaction.response.send_message("⏹️ Stopped and cleared the queue.", ephemeral=hidden)

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------
    @music.command(name="queue", description="View the current queue")
    @app_commands.describe(hidden="Hide the command from others")
    async def queue(self, interaction: discord.Interaction, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            await interaction.response.send_message("I'm not connected to a voice channel.", ephemeral=hidden)
            return

        current = player.current
        upcoming = list(player.queue)
        if current is None and not upcoming:
            await interaction.response.send_message("The queue is empty.", ephemeral=hidden)
            return

        embed = discord.Embed(
            title=f"📋 Music Queue ({len(upcoming)} track{'s' if len(upcoming) != 1 else ''})",
            color=VOIDWAVE_COLOR,
        )
        if current:
            embed.description = f"**Now playing:** [{current.title}]({current.uri})\n> `{fmt(player.position)}` / `{fmt(current.length)}`"
        else:
            embed.description = "**Now playing:** nothing"

        if not upcoming:
            embed.add_field(name="Up next", value="Nothing in the queue yet.", inline=False)
        else:
            lines = [f"`{i}.` **{track.title}** • *{track.author}*\n> `{fmt(track.length)}`" for i, track in enumerate(upcoming[:QUEUE_PAGE_SIZE], 1)]
            embed.add_field(name="Up next", value="\n".join(lines), inline=False)
            if len(upcoming) > QUEUE_PAGE_SIZE:
                embed.add_field(name="⛔ Truncated", value=f"Showing the first **{len(lines)}** of **{len(upcoming)}** track{'s' if len(upcoming) != 1 else ''}.", inline=False)

        remaining = sum(t.length for t in upcoming)
        if current is not None:
            remaining += max(0, current.length - player.position)
        embed.add_field(name="⏱️ Total remaining", value=f"`{fmt(remaining)}`", inline=False)
        _footer(embed)
        await interaction.response.send_message(embed=embed, ephemeral=hidden)

    # ------------------------------------------------------------------
    # Now playing
    # ------------------------------------------------------------------
    @music.command(name="nowplaying", description="Show what's currently playing")
    @app_commands.describe(hidden="Hide the command from others")
    async def nowplaying(self, interaction: discord.Interaction, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.playing or player.current is None:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=hidden)
            return

        track = player.current
        position_ms = player.position
        length_ms = track.length
        progress = min(position_ms / length_ms, 1) if length_ms else 0
        filled = round(progress * 16)
        bar = f"{'▰' * filled}{'▱' * (16 - filled)}"
        paused = " ⏸️" if player.paused else ""

        embed = discord.Embed(
            title=f"▶️ Now Playing{paused}",
            description=(
                f"**[{track.title}]({track.uri})**\n\n"
                f"> {track.author}\n"
                f"> `{bar}` `{fmt(position_ms)}` / `{fmt(length_ms)}`"
            ),
            color=VOIDWAVE_COLOR,
        )
        embed.set_thumbnail(url=track.artwork or None)
        embed.add_field(name="Volume", value=f"`{player.volume}%`", inline=True)
        embed.add_field(name="Source", value=f"`{track.source or 'Unknown'}`", inline=True)
        if player.queue.count:
            embed.add_field(name="Up next", value=f"`#{player.queue.count}` track{'s' if player.queue.count != 1 else ''}", inline=True)
        _footer(embed)
        await interaction.response.send_message(embed=embed, ephemeral=hidden)

    # ------------------------------------------------------------------
    # Shuffle / Loop / Volume
    # ------------------------------------------------------------------
    @music.command(name="shuffle", description="Shuffle the upcoming queue")
    @app_commands.describe(hidden="Hide the command from others")
    async def shuffle(self, interaction: discord.Interaction, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            await interaction.response.send_message("I'm not connected to a voice channel.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return
        if player.queue.is_empty:
            await interaction.response.send_message("There's nothing in the queue to shuffle.", ephemeral=hidden)
            return
        player.queue.shuffle()
        await interaction.response.send_message(f"🔀 Shuffled the queue! (`{player.queue.count}` track{'s' if player.queue.count != 1 else ''})", ephemeral=hidden)

    @music.command(name="loop", description="Set loop mode: off, track or queue")
    @app_commands.describe(mode="Loop mode to set", hidden="Hide the command from others")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Off", value="off"),
        app_commands.Choice(name="Track", value="track"),
        app_commands.Choice(name="Queue", value="queue"),
    ])
    async def loop(self, interaction: discord.Interaction, mode: str, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            await interaction.response.send_message("I'm not connected to a voice channel.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return

        if mode == "track":
            player.queue.mode = wavelink.QueueMode.loop
            label = "🔂 Looping the current track"
        elif mode == "queue":
            player.queue.mode = wavelink.QueueMode.loop_all
            label = "🔁 Looping the whole queue"
        else:
            player.queue.mode = wavelink.QueueMode.normal
            label = "➡️ Loop mode is off"
        await interaction.response.send_message(f"{label}.", ephemeral=hidden)

    @music.command(name="volume", description="Set the playback volume (1-100)")
    @app_commands.describe(level="Volume level from 1 to 100", hidden="Hide the command from others")
    async def volume(self, interaction: discord.Interaction, level: int, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            await interaction.response.send_message("I'm not connected to a voice channel.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return
        level = max(1, min(level, 100))
        await player.set_volume(level)
        await interaction.response.send_message(f"🔊 Volume set to **{level}%**.", ephemeral=hidden)

    # ------------------------------------------------------------------
    # Disconnect
    # ------------------------------------------------------------------
    @music.command(name="disconnect", description="Stop music and leave the voice channel")
    @app_commands.describe(hidden="Hide the command from others")
    async def disconnect(self, interaction: discord.Interaction, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            await interaction.response.send_message("I'm not in a voice channel.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return
        await self._disconnect(player)
        await interaction.response.send_message("👋 Disconnected and cleared the queue.", ephemeral=hidden)

    # ------------------------------------------------------------------
    # Background handling
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        for guild_id, player in list(self.players.items()):
            if not isinstance(player, wavelink.Player):
                continue
            if not player.connected or not player.channel:
                self.players.pop(guild_id, None)
                continue
            humans = [m for m in player.channel.members if not m.bot]
            if not humans:
                print(f"{date()} INFO  Leaving empty voice channel in guild {guild_id}")
                await self._disconnect(player)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player = payload.player
        if not isinstance(player, wavelink.Player):
            return

        if not player.queue.is_empty:
            if player.guild:
                self._reset_skip_votes(player.guild.id)
            next_track = player.queue.get()
            await player.play(next_track)
            return

        await asyncio.sleep(2)
        if player.guild and player.queue.is_empty and not player.playing:
            await self._disconnect(player)


async def setup(bot):
    await bot.add_cog(MusicCog(bot))