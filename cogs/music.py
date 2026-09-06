from discord import app_commands
from discord.ext import commands
import discord
import aiohttp
import asyncio
import os
import logging
import time
from difflib import SequenceMatcher

import wavelink

from utils import is_blocked, block_reply

logger = logging.getLogger("cogs.music")


VOIDWAVE_COLOR = 0x7128fc
QUEUE_PAGE_SIZE = 10
_LYRIC_OFFSET_MS = 2500
_LOOP_MODES = (wavelink.QueueMode.normal, wavelink.QueueMode.loop, wavelink.QueueMode.loop_all)
_LOOP_LABELS = ("🔁", "🔂", "🔃")
_SOURCE_ICONS = {"youtube": "🎵", "spotify": "🎧", "soundcloud": "☁️"}


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
    if not text:
        return text
    return " ".join(text.translate(_DASHES).split())


_SEARCH_CACHE_TTL = 60
_MAX_SEARCH_RESULTS = 10


def _fuzzy_score(query_word: str, target: str) -> float:
    """Return a 0-1 fuzzy match score of query_word against target."""
    if not target or not query_word:
        return 0.0
    if query_word in target:
        return 1.0
    return SequenceMatcher(None, query_word, target).ratio()


def _best_result(query, results):
    if not results:
        return None
    q_words = [
        w for w in " ".join(query.lower().translate(_DASHES).split()).split()
        if w and len(w) > 1
    ]
    if not q_words:
        return results[0]
    best = results[0]
    best_score = -1.0
    for idx, r in enumerate(results[:12]):
        title = _clean_text(r.title).lower()
        artist = _clean_text(getattr(r, "author", "") or "").lower()
        score = 0.0
        for w in q_words:
            title_score = _fuzzy_score(w, title)
            artist_score = _fuzzy_score(w, artist) * 0.8
            score += max(title_score, artist_score)
        position_bonus = max(0, 1.0 - idx * 0.1)
        score += position_bonus
        length_ms = getattr(r, "length", 0) or 0
        if length_ms > 3 * 3600 * 1000:
            score -= 1.5
        if score > best_score:
            best_score = score
            best = r
    return best


def _normalize_query(query: str) -> str | None:
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


def _progress_bar(position_ms, length_ms, width=18):
    progress = min(position_ms / length_ms, 1) if length_ms else 0
    filled = round(progress * width)
    block = "▓"
    dot = "░"
    bar = f"{block * filled}{dot * (width - filled)}"
    if not (0.05 < progress < 0.95):
        return bar
    marker_pos = round(progress * width) - 1
    marker_pos = max(0, min(width - 1, marker_pos))
    return bar[:marker_pos] + "●" + bar[marker_pos + 1:]


def _parse_seek(time_str: str) -> int | None:
    """Parse a time string like '1:30', '90', '2h5m' into milliseconds."""
    time_str = time_str.strip().lower()
    if not time_str:
        return None
    total_ms = 0
    try:
        if ":" in time_str:
            parts = time_str.split(":")
            if len(parts) == 2:
                total_ms = (int(parts[0]) * 60 + int(parts[1])) * 1000
            elif len(parts) == 3:
                total_ms = (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) * 1000
            else:
                return None
        elif "h" in time_str or "m" in time_str or "s" in time_str:
            import re
            hours = re.search(r"(\d+)h", time_str)
            minutes = re.search(r"(\d+)m", time_str)
            seconds = re.search(r"(\d+)s", time_str)
            total_ms = (
                (int(hours.group(1)) * 3600 if hours else 0)
                + (int(minutes.group(1)) * 60 if minutes else 0)
                + (int(seconds.group(1)) if seconds else 0)
            ) * 1000
        else:
            total_ms = int(time_str) * 1000
    except (ValueError, AttributeError):
        return None
    return max(0, total_ms) if total_ms >= 0 else None


async def _fetch_lyrics(track_title: str, artist: str = "", duration_s: int = 0) -> dict | None:
    """Fetch lyrics from lrclib.net. Returns {"plain": ..., "synced": ...} or None."""
    params = {"track_name": track_title}
    if artist:
        params["artist_name"] = artist
    if duration_s:
        params["duration"] = duration_s
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://lrclib.net/api/get",
                params=params,
                headers={"User-Agent": "VoidWave-Bot/2.0"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    plain = data.get("plainLyrics")
                    synced = data.get("syncedLyrics")
                    if plain or synced:
                        return {"plain": plain, "synced": synced, "album": data.get("albumName", "")}
    except Exception as e:
        logger.debug("Lyrics fetch failed for '%s': %s", track_title, e)
    return None


def _source_icon(source: str) -> str:
    return _SOURCE_ICONS.get((source or "").lower(), "🎵")


_LRC_TIME_RE = None


def _parse_lrc(synced: str) -> list[tuple[int, str]]:
    """Parse synced LRC lyrics into a sorted list of (timestamp_ms, line)."""
    global _LRC_TIME_RE
    if _LRC_TIME_RE is None:
        import re
        _LRC_TIME_RE = re.compile(r"\[(\d+):(\d+)(?:[.:](\d+))?\]")
    entries: list[tuple[int, str]] = []
    for raw_line in synced.splitlines():
        parts = _LRC_TIME_RE.findall(raw_line)
        if not parts:
            continue
        text = _LRC_TIME_RE.sub("", raw_line).strip()
        for minutes, seconds, frac in parts:
            ms = int(minutes) * 60000 + int(seconds) * 1000
            if frac:
                ms += int(frac) * (10 if len(frac) >= 3 else 100)
            entries.append((ms, text))
    if not entries:
        return []
    entries.sort(key=lambda e: e[0])
    merged: list[tuple[int, str]] = []
    for ms, text in entries:
        if merged and merged[-1][0] == ms:
            continue
        merged.append((ms, text))
    return merged


def _current_line(entries: list[tuple[int, str]], position_ms: int) -> int | None:
    """Return the index of the lyric line active at position_ms, else None."""
    if not entries:
        return None
    idx = 0
    for i, (ts, _) in enumerate(entries):
        if ts <= position_ms:
            idx = i
        else:
            break
    return idx


def now_playing_embed(track, player, requester=None, preview_lyrics: str | None = None, live_line: str | None = None, live_next: str | None = None):
    paused = player.paused
    pos = player.position
    length = track.length
    remaining = max(0, length - pos)
    pct = round((pos / length * 100) if length else 0)
    bar = _progress_bar(pos, length)

    title = f"{'⏸️ Paused' if paused else '▶️ Now Playing'}"
    stats = (
        f"`{fmt(pos)}` • `{pct}%` • `{_loop_label(player.queue.mode)}` • "
        f"`{player.volume}% vol`"
        + (f" • `Autoplay on`" if player.autoplay == wavelink.AutoPlayMode.enabled else "")
    )
    desc = (
        f"**[{track.title}]({track.uri})**\n"
        f"{track.author}\n\n"
        f"`{bar}`\n"
        f"`{fmt(pos)}` / `{fmt(length)}` (`{fmt(remaining)}` left)\n\n"
        f"{stats}"
    )

    if live_line:
        desc += "\n\n🎤 " + live_line
        if live_next:
            desc += f"\n_{live_next}_"
    elif live_next:
        desc += f"\n\n🎼 Up next: _{live_next}_"
    elif preview_lyrics:
        preview = "\n".join(preview_lyrics.split("\n")[:5])
        if len(preview) > 200:
            preview = preview[:197] + "..."
        desc += f"\n\n📝 *{preview}*"

    embed = discord.Embed(title=title, description=desc, color=VOIDWAVE_COLOR)
    embed.set_thumbnail(url=track.artwork or None)
    if requester:
        embed.set_author(name=requester.display_name, icon_url=requester.display_avatar.url)
    return embed


def _loop_label(mode):
    return {"normal": "No loop", "loop": "One loop", "loop_all": "Loop all"}.get(str(mode), "No loop")


# ======================================================================
# Interactive Player View
# ======================================================================
class MusicPlayerView(discord.ui.View):
    def __init__(self, cog, guild_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self._message_id: int | None = None

    def _update_button_states(self, player):
        playing = isinstance(player, wavelink.Player) and player.connected and player.playing
        paused = playing and player.paused
        has_queue = playing and not player.queue.is_empty

        for item in self.children:
            match getattr(item, "emoji", None):
                case e if e and e.name == "🔀":
                    item.disabled = not has_queue
                case e if e and e.name in ("⏮️", "⏭️"):
                    item.disabled = not playing
                case e if e and e.name == "⏯️":
                    item.disabled = not playing
                    item.style = discord.ButtonStyle.success if paused else discord.ButtonStyle.primary
                case e if e and e.name == "👋":
                    item.disabled = not playing
                case e if e and e.name == "📝":
                    item.disabled = not playing
                case e if e and e.name == "🎤":
                    item.disabled = not playing

    # -- row 0: shuffle | prev | play/pause | next | loop ----------------
    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=0)
    async def on_shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        player = self.cog._player(interaction)
        if player.queue.is_empty:
            return await interaction.response.send_message("Nothing in the queue to shuffle.", ephemeral=True)
        player.queue.shuffle()
        await interaction.response.send_message("🔀 Queue shuffled!", ephemeral=True)

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def on_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        player = self.cog._player(interaction)
        history = player.queue.history
        if not history or history.is_empty:
            return await interaction.response.send_message("No previous track available.", ephemeral=True)
        prev_track = history.get()
        await player.play(prev_track)
        self.cog._reset_skip_votes(self.guild_id)
        await interaction.response.send_message(f"⏮️ Now playing **{prev_track.title}**.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def on_pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        player = self.cog._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.playing:
            return await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
        await player.pause(not player.paused)
        label = "Paused" if player.paused else "Resumed"
        await interaction.response.send_message(f"{'⏸️' if player.paused else '▶️'} {label}.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def on_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        player = self.cog._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.playing:
            return await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
        current = player.current
        guild_id = self.guild_id
        if self.cog.players_owner.get(guild_id) == interaction.user.id:
            self.cog._reset_skip_votes(guild_id)
            await player.skip(force=True)
            return await interaction.response.send_message(f"⏭️ Skipped **{current.title}**.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        listeners = [m for m in player.channel.members if not m.bot] if player.channel else []
        required = len(listeners) // 2 + 1
        votes = self.cog.skip_votes.setdefault(guild_id, set())
        votes.add(interaction.user.id)
        if len(votes) >= required:
            self.cog._reset_skip_votes(guild_id)
            await player.skip(force=True)
            return await interaction.response.send_message(f"⏭️ Vote-to-skip passed, skipping **{current.title}**.", ephemeral=False, allowed_mentions=discord.AllowedMentions.none())
        await interaction.response.send_message(
            f"🗳️ **{interaction.user.display_name}** wants to skip **{current.title}**. "
            f"Votes `{len(votes)}/{required}` needed to skip.\n"
            f"Press ⏭️ on the music controller or use `/music skip` to vote.",
            ephemeral=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=0)
    async def on_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        player = self.cog._player(interaction)
        current_mode = player.queue.mode
        idx = (_LOOP_MODES.index(current_mode) + 1) % 3 if current_mode in _LOOP_MODES else 0
        player.queue.mode = _LOOP_MODES[idx]
        button.emoji = _LOOP_LABELS[idx]
        labels = ["Loop off", "Looping track", "Looping queue"]
        await interaction.response.send_message(f"🔁 {labels[idx]}.", ephemeral=True)

    # -- row 1: leave | queue | lyrics | live lyrics | autoplay ----------
    @discord.ui.button(emoji="👋", style=discord.ButtonStyle.danger, row=1)
    async def on_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        player = self.cog._player(interaction)
        msg = self.cog.player_messages.get(self.guild_id)
        await self.cog._disconnect(player)
        await interaction.response.send_message("👋 Left the voice channel and cleared the queue.", ephemeral=True)
        if msg:
            try:
                embed = discord.Embed(title="👋 Disconnected", description="Left the voice channel and cleared the queue.", color=VOIDWAVE_COLOR)
                await msg.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass

    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.secondary, row=1)
    async def on_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.cog._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            return await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
        view = QueueView(self.cog, self.guild_id, interaction.user.id)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(emoji="🎤", style=discord.ButtonStyle.secondary, row=1)
    async def on_live_lyrics(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        player = self.cog._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            return await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
        guild_id = self.guild_id
        if guild_id in self.cog.live_lyrics:
            self.cog.live_lyrics.pop(guild_id, None)
            await interaction.response.send_message("🎤 Live lyrics **off**.", ephemeral=True)
        else:
            if not player.current:
                return await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            self.cog.live_lyrics[guild_id] = True
            self.cog._ensure_lyrics_loaded(player.current)
            await interaction.response.send_message("🎤 Live lyrics **on** for the player embed.", ephemeral=True)
        await self.cog._sync_player_view(guild_id)

    @discord.ui.button(emoji="📝", style=discord.ButtonStyle.secondary, row=1)
    async def on_lyrics(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        player = self.cog._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.current:
            return await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        track = player.current
        lyrics = await _fetch_lyrics(track.title, track.author, track.length // 1000)
        if not lyrics:
            return await interaction.followup.send("No lyrics found for this track.", ephemeral=True)
        text = lyrics.get("synced") or lyrics.get("plain") or ""
        if len(text) > 3800:
            text = text[:3800] + "\n\n*...truncated*"
        embed = discord.Embed(title=f"📝 Lyrics for **{track.title}**", description=f"```\n{text}\n```", color=VOIDWAVE_COLOR)
        embed.set_footer(text=f"{track.author}" + (f" • {lyrics['album']}" if lyrics.get("album") else ""))
        view = LyricsView(interaction.user.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(emoji="✨", style=discord.ButtonStyle.secondary, row=1)
    async def on_autoplay(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        player = self.cog._player(interaction)
        if player.autoplay == wavelink.AutoPlayMode.enabled:
            player.autoplay = wavelink.AutoPlayMode.disabled
            await interaction.response.send_message("✨ Autoplay **off**.", ephemeral=True)
        else:
            player.autoplay = wavelink.AutoPlayMode.enabled
            await interaction.response.send_message("✨ Autoplay **on**. Related tracks will play when the queue empties.", ephemeral=True)

    # -- row 2: volume select -------------------------------------------
    @discord.ui.select(
        placeholder="🔊 Volume",
        options=[
            discord.SelectOption(label="10%", value="10", emoji="🔈"),
            discord.SelectOption(label="25%", value="25", emoji="🔉"),
            discord.SelectOption(label="50%", value="50", emoji="🔊"),
            discord.SelectOption(label="75%", value="75", emoji="🔊"),
            discord.SelectOption(label="100%", value="100", emoji="📢"),
        ],
        row=2,
    )
    async def on_volume(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not await self._check(interaction):
            return
        player = self.cog._player(interaction)
        level = max(1, min(int(select.values[0]), 100))
        await player.set_volume(level)
        await interaction.response.send_message(f"🔊 Volume set to **{level}%**.", ephemeral=True)

    # -- helpers ---------------------------------------------------------
    async def _check(self, interaction: discord.Interaction) -> bool:
        player = self.cog._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
            return False
        if not self.cog._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=True)
            return False
        return True


# ======================================================================
# Paginated Queue View
# ======================================================================
class QueueView(discord.ui.View):
    def __init__(self, cog, guild_id, user_id):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.page = 0

        self._track_select = discord.ui.Select(
            placeholder="Remove a track...",
            min_values=1, max_values=1,
            row=1,
        )
        self._track_select.callback = self._on_select_remove
        self.add_item(self._track_select)

    def _refresh_select(self):
        player = self.cog.players.get(self.guild_id)
        upcoming = list(player.queue) if isinstance(player, wavelink.Player) else []
        start = self.page * QUEUE_PAGE_SIZE
        page_tracks = upcoming[start:start + QUEUE_PAGE_SIZE]
        if not page_tracks:
            self._track_select.options = [
                discord.SelectOption(label="Queue is empty", value="__empty__")
            ]
            self._track_select.disabled = True
        else:
            self._track_select.options = []
            for i, t in enumerate(page_tracks, start + 1):
                label = f"{i}. {t.title[:50]}"
                self._track_select.options.append(
                    discord.SelectOption(label=label, description=t.author[:50], value=str(i))
                )
            self._track_select.disabled = False

    def build_embed(self):
        player = self.cog.players.get(self.guild_id)
        if not isinstance(player, wavelink.Player) or not player.connected:
            return discord.Embed(title="📋 Queue", description="Not connected.", color=VOIDWAVE_COLOR)

        current = player.current
        upcoming = list(player.queue)
        total = len(upcoming)
        total_pages = max(1, (total + QUEUE_PAGE_SIZE - 1) // QUEUE_PAGE_SIZE)
        self.page = max(0, min(self.page, total_pages - 1))

        embed = discord.Embed(title=f"📋 Queue ({total} track{'s' if total != 1 else ''})", color=VOIDWAVE_COLOR)
        if current:
            embed.description = f"**Now playing:** [{current.title}]({current.uri})\n`{fmt(player.position)}` / `{fmt(current.length)}`"
        else:
            embed.description = "**Now playing:** nothing"

        start = self.page * QUEUE_PAGE_SIZE
        page_tracks = upcoming[start:start + QUEUE_PAGE_SIZE]
        if page_tracks:
            lines = [f"`{i}.` **{t.title}** - *{t.author}*  `{fmt(t.length)}`" for i, t in enumerate(page_tracks, start + 1)]
            embed.add_field(name="Up next", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Up next", value="Nothing in the queue.", inline=False)

        remaining = sum(t.length for t in upcoming)
        if current is not None:
            remaining += max(0, current.length - player.position)
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages}  •  {fmt(remaining)} total")
        self._refresh_select()
        return embed

    def _check_user(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def _on_select_remove(self, interaction: discord.Interaction):
        if not self._check_user(interaction):
            return await interaction.response.send_message("This queue isn't for you.", ephemeral=True)
        val = interaction.data["values"][0]
        if val == "__empty__":
            return await interaction.response.defer()
        player = self.cog.players.get(self.guild_id)
        if not isinstance(player, wavelink.Player):
            return await interaction.response.defer()
        idx = int(val) - 1
        upcoming = list(player.queue)
        if idx < 0 or idx >= len(upcoming):
            return await interaction.response.defer()
        removed = player.queue.delete(idx)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary, row=0)
    async def on_prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_user(interaction):
            return await interaction.response.send_message("This queue isn't for you.", ephemeral=True)
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, row=0)
    async def on_next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_user(interaction):
            return await interaction.response.send_message("This queue isn't for you.", ephemeral=True)
        self.page += 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Clear", style=discord.ButtonStyle.danger, row=0)
    async def on_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_user(interaction):
            return await interaction.response.send_message("This queue isn't for you.", ephemeral=True)
        player = self.cog.players.get(self.guild_id)
        if isinstance(player, wavelink.Player):
            player.queue.clear()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(emoji="✖", style=discord.ButtonStyle.secondary, row=0)
    async def on_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_user(interaction):
            return await interaction.response.send_message("This queue isn't for you.", ephemeral=True)
        await interaction.response.edit_message(view=None)
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ======================================================================
# Interactive Search Picker
# ======================================================================
class SearchPickerView(discord.ui.View):
    def __init__(self, cog, tracks, interaction, user_id, query=""):
        super().__init__(timeout=30)
        self.cog = cog
        self.tracks = tracks[:_MAX_SEARCH_RESULTS]
        self.interaction = interaction
        self.user_id = user_id
        self.query = query
        self.picked = False

        options = []
        for i, t in enumerate(self.tracks):
            title = t.title[:95]
            desc = f"{t.author[:45]} • {fmt(t.length)}"
            options.append(discord.SelectOption(
                label=f"{i + 1}. {title}",
                description=desc,
                value=str(i),
                emoji=_source_icon(t.source),
            ))
        self._select = discord.ui.Select(
            placeholder="Pick a track to play...",
            options=options,
            row=0,
        )
        self._select.callback = self._on_select
        self.add_item(self._select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This search isn't for you.", ephemeral=True)
        if self.picked:
            return await interaction.response.send_message("Already picked a track.", ephemeral=True)
        self.picked = True
        for child in self.children:
            child.disabled = True
        idx = int(interaction.data["values"][0])
        track = self.tracks[idx]
        await interaction.response.edit_message(
            embed=discord.Embed(title="🎵 Searching...", description=f"Playing **{track.title}**", color=VOIDWAVE_COLOR),
            view=self,
        )
        await self.cog._play_from_search(self.interaction, track)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def on_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This search isn't for you.", ephemeral=True)
        if self.picked:
            return await interaction.response.send_message("Already picked a track.", ephemeral=True)
        self.picked = True
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(
                embed=discord.Embed(title="❌ Search cancelled", color=VOIDWAVE_COLOR),
                view=self,
            )
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Auto", style=discord.ButtonStyle.success, row=1)
    async def on_auto(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This search isn't for you.", ephemeral=True)
        if self.picked:
            return await interaction.response.send_message("Already picked a track.", ephemeral=True)
        self.picked = True
        for child in self.children:
            child.disabled = True
        track = _best_result(self.query, self.tracks) or self.tracks[0]
        await interaction.response.edit_message(
            embed=discord.Embed(title="🎵 Searching...", description=f"Playing **{track.title}**", color=VOIDWAVE_COLOR),
            view=self,
        )
        await self.cog._play_from_search(self.interaction, track)

    async def on_timeout(self):
        if self.picked:
            return
        self.picked = True
        for child in self.children:
            child.disabled = True
        track = _best_result(self.query, self.tracks) or self.tracks[0]
        try:
            await self.interaction.edit_original_response(
                embed=discord.Embed(title="⏱️ Search timed out", description=f"Auto-playing **{track.title}**", color=VOIDWAVE_COLOR),
                view=self,
            )
        except discord.HTTPException:
            pass
        await self.cog._play_from_search(self.interaction, track)


# ======================================================================
# Lyrics View
# ======================================================================
class LyricsView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, row=0)
    async def on_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't for you.", ephemeral=True)
        await interaction.response.edit_message(view=None)
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ======================================================================
# Music Cog
# ======================================================================
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
        self.player_views: dict[int, MusicPlayerView] = {}
        self.player_messages: dict[int, discord.Message] = {}
        self._update_tasks: dict[int, asyncio.Task] = {}
        self.live_lyrics: dict[int, bool] = {}
        self._lyrics_cache: dict[str, list[tuple[int, str]]] = {}
        self._lyrics_loading: dict[str, asyncio.Task] = {}
        self._search_cache: dict[str, tuple[float, list]] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _deny_if_blocked(self, interaction: discord.Interaction) -> bool:
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

    def _get_cached_search(self, normalized_query: str) -> list | None:
        entry = self._search_cache.get(normalized_query)
        if entry and (time.time() - entry[0]) < _SEARCH_CACHE_TTL:
            return entry[1]
        if entry:
            self._search_cache.pop(normalized_query, None)
        return None

    def _cache_search(self, normalized_query: str, results: list):
        self._search_cache[normalized_query] = (time.time(), results)
        now = time.time()
        stale = [k for k, (ts, _) in self._search_cache.items() if now - ts > _SEARCH_CACHE_TTL]
        for k in stale:
            self._search_cache.pop(k, None)

    async def _search_tracks(self, normalized: str, node: wavelink.Node) -> list | None:
        cached = self._get_cached_search(normalized)
        if cached is not None:
            return cached
        try:
            tracks = await wavelink.Playable.search(normalized, node=node)
        except Exception as e:
            logger.error("Music search failed: %s", e)
            return None
        if not tracks:
            return []
        if isinstance(tracks, wavelink.Playlist):
            return tracks
        if isinstance(tracks, (list, tuple)):
            results = [t for t in list(tracks) if (t.source or "").lower() == "youtube"] or list(tracks)
        else:
            results = [tracks]
        self._cache_search(normalized, results)
        return results

    async def _disconnect(self, player: wavelink.Player):
        guild_id = player.guild.id if player.guild else 0
        self._cancel_update_task(guild_id)
        view = self.player_views.pop(guild_id, None)
        if view:
            for child in view.children:
                child.disabled = True
        player.queue.clear()
        if player.guild:
            self.players.pop(player.guild.id, None)
            self._reset_skip_votes(player.guild.id)
            self.players_owner.pop(player.guild.id, None)
        try:
            await player.disconnect()
        except Exception as e:
            logger.error("Failed to disconnect music player: %s", e)
        self.player_messages.pop(guild_id, None)
        self.live_lyrics.pop(guild_id, None)

    # ------------------------------------------------------------------
    # Player view management
    # ------------------------------------------------------------------
    def _cancel_update_task(self, guild_id: int):
        task = self._update_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _cache_key(self, track) -> str:
        return f"{track.source or ''}|{track.title}|{track.author}"

    def _get_lyrics_lines(self, track) -> list[tuple[int, str]] | None:
        return self._lyrics_cache.get(self._cache_key(track))

    def _ensure_lyrics_loaded(self, track) -> bool:
        """Kick off a background fetch if lyrics for this track aren't cached yet."""
        key = self._cache_key(track)
        if key in self._lyrics_cache or key in self._lyrics_loading:
            return key in self._lyrics_cache
        task = self.bot.loop.create_task(self._load_lyrics(key, track))
        self._lyrics_loading[key] = task
        return False

    async def _load_lyrics(self, key: str, track):
        try:
            data = await _fetch_lyrics(track.title, track.author, track.length // 1000)
            if data and data.get("synced"):
                entries = _parse_lrc(data["synced"])
                if entries:
                    self._lyrics_cache[key] = entries
                    return
            self._lyrics_cache[key] = []
        except Exception as e:
            logger.debug("Background lyric load failed for %s: %s", key, e)
            self._lyrics_cache[key] = []
        finally:
            self._lyrics_loading.pop(key, None)

    async def _live_lyric(self, guild_id: int, player, current):
        """Return (current, next, wait_ms) for live lyrics.

        current may be None during gaps (intro/instrumental) before a line;
        next is then the upcoming line. wait_ms is the time until the next
        lyric change, capped so pauses/seeks stay responsive. Falls back to
        (None, None, 500) when no synced lyrics are available yet.
        """
        if not self.live_lyrics.get(guild_id):
            return None, None, 500
        entries = self._get_lyrics_lines(current)
        if entries is None:
            self._ensure_lyrics_loaded(current)
            return None, None, 500
        if not entries:
            return None, None, 500
        pos = player.position
        idx = _current_line(entries, pos + _LYRIC_OFFSET_MS)
        if idx is None:
            first_ts = entries[0][0]
            first_line = entries[0][1]
            wait = max(200, min(1500, first_ts - pos))
            return None, (first_line or None), wait
        cur = entries[idx][1]
        nxt = entries[idx + 1][1] if idx + 1 < len(entries) else None
        wait = 500
        if idx + 1 < len(entries):
            wait = max(200, min(1500, max(0, entries[idx + 1][0] - pos)))
        return cur or None, (nxt or None), wait

    def _start_update_task(self, guild_id: int, message: discord.Message):
        self._cancel_update_task(guild_id)
        self.player_messages[guild_id] = message
        self._update_tasks[guild_id] = self.bot.loop.create_task(self._player_update_loop(guild_id))

    async def _player_update_loop(self, guild_id: int):
        last_line = last_line_next = None
        last_base = 0.0
        try:
            while True:
                await asyncio.sleep(1.0)
                player = self.players.get(guild_id)
                if self.players.get(guild_id) is not player:
                    break
                if not isinstance(player, wavelink.Player) or not player.connected or not player.playing or not player.current:
                    break
                msg = self.player_messages.get(guild_id)
                view = self.player_views.get(guild_id)
                if not msg or not view:
                    break
                view._update_button_states(player)
                try:
                    if self.live_lyrics.get(guild_id):
                        cur, nxt, _ = await self._live_lyric(guild_id, player, player.current)
                        last_line, last_line_next = cur, nxt
                        await msg.edit(embed=now_playing_embed(player.current, player, live_line=cur, live_next=nxt), view=view)
                    else:
                        now = time.time()
                        if now - last_base >= 5.0 or not last_base:
                            await msg.edit(embed=now_playing_embed(player.current, player), view=view)
                            last_base = now
                except discord.HTTPException:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Player update task error in guild %s: %s", guild_id, e)

    async def _sync_player_view(self, guild_id: int):
        player = self.players.get(guild_id)
        view = self.player_views.get(guild_id)
        msg = self.player_messages.get(guild_id)
        if not (isinstance(player, wavelink.Player) and player.connected and player.current and view and msg):
            return
        view._update_button_states(player)
        cur, nxt, _ = await self._live_lyric(guild_id, player, player.current)
        try:
            await msg.edit(embed=now_playing_embed(player.current, player, live_line=cur, live_next=nxt), view=view)
        except discord.HTTPException:
            pass

    async def _send_player_message(self, interaction: discord.Interaction, track, player, requester=None):
        guild_id = interaction.guild_id
        old_msg = self.player_messages.get(guild_id)
        old_view = self.player_views.get(guild_id)
        self._cancel_update_task(guild_id)

        view = MusicPlayerView(self, guild_id)
        view._update_button_states(player)
        self.player_views[guild_id] = view
        embed = now_playing_embed(track, player, requester or interaction.user)
        msg = await interaction.followup.send(embed=embed, view=view)
        view._message_id = msg.id
        self.player_messages[guild_id] = msg
        self._start_update_task(guild_id, msg)
        if self.live_lyrics.get(guild_id):
            self._ensure_lyrics_loaded(track)

        if old_msg and old_view and old_msg.id != msg.id:
            try:
                for child in old_view.children:
                    child.disabled = True
                await old_msg.delete()
            except discord.HTTPException:
                pass
    async def _repost_player_message(self, interaction: discord.Interaction, player):
        """Repost the controller to the current channel to bring it back into view."""
        guild_id = interaction.guild_id
        old_msg = self.player_messages.get(guild_id)
        old_view = self.player_views.get(guild_id)
        self._cancel_update_task(guild_id)

        current = player.current
        if current is None:
            return
        view = MusicPlayerView(self, guild_id)
        view._update_button_states(player)
        self.player_views[guild_id] = view
        embed = now_playing_embed(current, player)
        try:
            msg = await interaction.channel.send(embed=embed, view=view)
            view._message_id = msg.id
            self.player_messages[guild_id] = msg
            self._start_update_task(guild_id, msg)
        except discord.HTTPException:
            return

        if old_msg and old_view and old_msg.id != msg.id:
            try:
                for child in old_view.children:
                    child.disabled = True
                await old_msg.delete()
            except discord.HTTPException:
                pass

    async def _play_from_search(self, interaction: discord.Interaction, track):
        """Play a track chosen from the search picker. interaction must already be deferred."""
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player):
            return
        if player.playing:
            await player.queue.put_wait(track)
            await self._repost_player_message(interaction, player)
            return
        self._reset_skip_votes(interaction.guild_id)
        await player.play(track)
        await self._send_player_message(interaction, track, player)

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
            logger.error("Failed to connect to Lavalink node at %s: %s", uri, e)

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        logger.info("Lavalink node ready: %s", payload.node.uri)

    @commands.Cog.listener()
    async def on_wavelink_node_closed(self, node, disconnected: bool):
        logger.warning("Lavalink node closed: %s (disconnected=%s)", node.uri, disconnected)

    # ------------------------------------------------------------------
    # Play
    # ------------------------------------------------------------------
    @music.command(name="play", description="Play a song or add it to the queue")
    @app_commands.describe(query='A Youtube URL or a search term', hidden="Hide the command from others")
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
            logger.error("No available Lavalink node: %s", e)
            await interaction.response.send_message("Music server unavailable right now, please try again in a moment.", ephemeral=hidden)
            return
        await interaction.response.defer(ephemeral=hidden)

        player = self._player(interaction)
        if isinstance(player, wavelink.Player):
            if player.channel and player.channel.id != vc.channel.id:
                try:
                    await player.move_to(vc.channel)  # type: ignore
                except Exception as e:
                    logger.error("Failed to move music player: %s", e)
                    await interaction.followup.send("I couldn't move to your voice channel. Please try again.", ephemeral=hidden)
                    return
        else:
            try:
                player = await vc.channel.connect(cls=wavelink.Player, self_deaf=True)  # type: ignore
                self.players[interaction.guild_id] = player  # type: ignore
                self.players_owner[interaction.guild_id] = interaction.user.id
            except Exception as e:
                logger.error("Failed to connect music player to voice: %s", e)
                await interaction.followup.send("I couldn't join your voice channel. Please try again.", ephemeral=hidden)
                return

        normalized = _normalize_query(query)
        if normalized is None:
            await interaction.followup.send("I couldn't find anything for that query. Please try again.", ephemeral=hidden)
            return
        tracks = await self._search_tracks(normalized, node)
        if tracks is None:
            await interaction.followup.send("I couldn't find anything for that query. Please try again.", ephemeral=hidden)
            return

        if not tracks:
            await interaction.followup.send(f"No results found for `{query}`.", ephemeral=hidden)
            return

        if isinstance(tracks, wavelink.Playlist):
            await player.queue.put_wait(tracks.tracks)
            if not player.playing and tracks.tracks:
                self._reset_skip_votes(interaction.guild_id)
                first = player.queue.get()
                await player.play(first)
                await self._send_player_message(interaction, first, player)
            else:
                embed = discord.Embed(
                    title="🎵 Playlist added to queue",
                    description=f"**[{tracks.name}]({query})** · **{len(tracks.tracks)}** songs",
                    color=VOIDWAVE_COLOR,
                )
                if tracks.tracks:
                    embed.add_field(name="First up", value=f"`{tracks.tracks[0].title}`", inline=False)
                    embed.set_thumbnail(url=tracks.tracks[0].artwork or None)
                _footer(embed)
                await interaction.followup.send(embed=embed, ephemeral=hidden)
                await self._repost_player_message(interaction, player)
            return

        results = tracks

        if len(results) > 1:
            view = SearchPickerView(self, results, interaction, interaction.user.id, query=query)
            lines = []
            for i, t in enumerate(results[:_MAX_SEARCH_RESULTS], 1):
                icon = _source_icon(t.source)
                lines.append(f"**{i}.** {icon} [{t.title}]({t.uri}) - *{t.author}* `{fmt(t.length)}`")
            embed = discord.Embed(title="🔍 Search Results", description="\n".join(lines), color=VOIDWAVE_COLOR)
            embed.set_footer(text="Pick a result or wait to auto-play the best match")
            await interaction.followup.send(embed=embed, view=view, ephemeral=hidden)
        else:
            track = results[0]
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
                await self._repost_player_message(interaction, player)
            else:
                self._reset_skip_votes(interaction.guild_id)
                await player.play(track)
                await self._send_player_message(interaction, track, player)

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
        await self._sync_player_view(interaction.guild_id)

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
        await self._sync_player_view(interaction.guild_id)

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
        await self._sync_player_view(interaction.guild_id)

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

        view = QueueView(self, interaction.guild_id, interaction.user.id)
        embed = view.build_embed()
        _footer(embed)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=hidden)

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
        embed = now_playing_embed(track, player, requester=interaction.user)
        _footer(embed)
        await interaction.response.send_message(embed=embed, ephemeral=hidden)

    # ------------------------------------------------------------------
    # Controller
    # ------------------------------------------------------------------
    @music.command(name="controller", description="Bring the interactive player controller back into view")
    @app_commands.describe(hidden="Hide the command from others")
    async def controller(self, interaction: discord.Interaction, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected or player.current is None:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return
        await interaction.response.defer(ephemeral=hidden)
        await self._repost_player_message(interaction, player)
        try:
            await interaction.followup.send("📺 Player controller reposted in this channel.", ephemeral=hidden)
        except discord.HTTPException:
            pass

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
            label = "🔁 Loop mode is off"
        await interaction.response.send_message(f"{label}.", ephemeral=hidden)
        await self._sync_player_view(interaction.guild_id)

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
        await self._sync_player_view(interaction.guild_id)

    # ------------------------------------------------------------------
    # Seek
    # ------------------------------------------------------------------
    @music.command(name="seek", description="Seek to a position in the current track")
    @app_commands.describe(position="Time to seek to (e.g. 1:30, 90, 2h5m)", hidden="Hide the command from others")
    async def seek(self, interaction: discord.Interaction, position: str, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.playing:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return
        ms = _parse_seek(position)
        if ms is None:
            await interaction.response.send_message("Invalid time format. Use `1:30`, `90`, or `2h5m`.", ephemeral=hidden)
            return
        track = player.current
        if ms > track.length:
            await interaction.response.send_message(f"Can't seek past the end of the track ({fmt(track.length)}).", ephemeral=hidden)
            return
        await player.seek(ms)
        await interaction.response.send_message(f"⏩ Seeked to `{fmt(ms)}` in **{track.title}**.", ephemeral=hidden)
        await self._sync_player_view(interaction.guild_id)

    # ------------------------------------------------------------------
    # Lyrics
    # ------------------------------------------------------------------
    @music.command(name="lyrics", description="Show lyrics for the current track")
    @app_commands.describe(hidden="Hide the command from others")
    async def lyrics(self, interaction: discord.Interaction, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.playing or not player.current:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=hidden)
            return
        await interaction.response.defer(ephemeral=hidden)
        track = player.current
        lyrics = await _fetch_lyrics(track.title, track.author, track.length // 1000)
        if not lyrics:
            await interaction.followup.send("No lyrics found for this track.", ephemeral=hidden)
            return
        text = lyrics.get("synced") or lyrics.get("plain") or ""
        if len(text) > 3800:
            text = text[:3800] + "\n\n*...truncated*"
        embed = discord.Embed(title=f"📝 Lyrics for **{track.title}**", description=f"```\n{text}\n```", color=VOIDWAVE_COLOR)
        embed.set_footer(text=f"{track.author}" + (f" • {lyrics['album']}" if lyrics.get("album") else ""))
        view = LyricsView(interaction.user.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=hidden)

    # ------------------------------------------------------------------
    # Lyrics live toggle
    # ------------------------------------------------------------------
    @music.command(name="lyricslive", description="Toggle live synced lyrics on the player embed")
    @app_commands.describe(mode="On or off", hidden="Hide the command from others")
    @app_commands.choices(mode=[
        app_commands.Choice(name="On", value="on"),
        app_commands.Choice(name="Off", value="off"),
    ])
    async def lyricslive(self, interaction: discord.Interaction, mode: str, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            await interaction.response.send_message("I'm not connected to a voice channel.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return
        guild_id = interaction.guild_id
        if mode == "on":
            if not player.current:
                await interaction.response.send_message("Nothing is playing right now.", ephemeral=hidden)
                return
            self.live_lyrics[guild_id] = True
            self._ensure_lyrics_loaded(player.current)
            await interaction.response.send_message("🎤 Live lyrics **on** for the player embed.", ephemeral=hidden)
        else:
            self.live_lyrics.pop(guild_id, None)
            await interaction.response.send_message("🎤 Live lyrics **off**.", ephemeral=hidden)
        await self._sync_player_view(guild_id)

    # ------------------------------------------------------------------
    # Autoplay
    # ------------------------------------------------------------------
    @music.command(name="autoplay", description="Toggle autoplay (plays related tracks when queue empties)")
    @app_commands.describe(mode="On or off", hidden="Hide the command from others")
    @app_commands.choices(mode=[
        app_commands.Choice(name="On", value="on"),
        app_commands.Choice(name="Off", value="off"),
    ])
    async def autoplay(self, interaction: discord.Interaction, mode: str, hidden: bool = False):
        if await self._deny_if_blocked(interaction):
            return
        player = self._player(interaction)
        if not isinstance(player, wavelink.Player) or not player.connected:
            await interaction.response.send_message("I'm not connected to a voice channel.", ephemeral=hidden)
            return
        if not self._same_vc(interaction, player):
            await interaction.response.send_message("You need to be in the same voice channel as me to control music.", ephemeral=hidden)
            return
        if mode == "on":
            player.autoplay = wavelink.AutoPlayMode.enabled
            await interaction.response.send_message("✨ Autoplay **on**. Related tracks will play when the queue empties.", ephemeral=hidden)
        else:
            player.autoplay = wavelink.AutoPlayMode.disabled
            await interaction.response.send_message("✨ Autoplay **off**.", ephemeral=hidden)
        await self._sync_player_view(interaction.guild_id)

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
        view = self.player_views.get(interaction.guild_id)
        msg = self.player_messages.get(interaction.guild_id)
        await self._disconnect(player)
        await interaction.response.send_message("👋 Disconnected and cleared the queue.", ephemeral=hidden)
        if msg and view:
            try:
                embed = discord.Embed(title="👋 Disconnected", description="Left the voice channel and cleared the queue.", color=VOIDWAVE_COLOR)
                await msg.edit(embed=embed, view=view)
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------------
    # Background handling
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild_id = member.guild.id if member.guild else None
        if guild_id is None:
            return
        player = self.players.get(guild_id)
        if not isinstance(player, wavelink.Player) or not player.connected or not player.channel:
            return
        humans = [m for m in player.channel.members if not m.bot]
        if not humans:
            logger.info("Leaving empty voice channel in guild %s", guild_id)
            view = self.player_views.get(guild_id)
            msg = self.player_messages.get(guild_id)
            await self._disconnect(player)
            if msg and view:
                for child in view.children:
                    child.disabled = True
                embed = discord.Embed(title="👋 Disconnected", description="Left the voice channel (empty). Play more with `/music play`.", color=VOIDWAVE_COLOR)
                try:
                    await msg.edit(embed=embed, view=view)
                except discord.HTTPException:
                    pass

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
            guild_id = player.guild.id if player.guild else 0
            if self.live_lyrics.get(guild_id):
                self._ensure_lyrics_loaded(next_track)
            return

        await asyncio.sleep(2)
        if player.guild and player.queue.is_empty and not player.playing:
            await self._disconnect(player)

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player = payload.player
        if not isinstance(player, wavelink.Player):
            return
        guild_id = player.guild.id if player.guild else 0
        track = payload.track
        if not track:
            return
        if self.live_lyrics.get(guild_id):
            self._ensure_lyrics_loaded(track)
        msg = self.player_messages.get(guild_id)
        view = self.player_views.get(guild_id)
        if not msg or not view:
            return
        view._update_button_states(player)
        cur, nxt, _ = await self._live_lyric(guild_id, player, track)
        try:
            await msg.edit(embed=now_playing_embed(track, player, live_line=cur, live_next=nxt), view=view)
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(MusicCog(bot))
