from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import discord
import random
import time
import logging
from utils import get_db, format_minutes, last_vc, VC_COOLDOWN, last_xp, XP_COOLDOWN, get_vote_boost, build_level_up_embed, log_admin_event

logger = logging.getLogger("cogs.leveling")


PER_PAGE = 10

SORT_COLUMNS = {
    "Level": "level",
    "Total XP": "total_xp",
    "Total Messages": "total_messages",
    "Total Voice": "vc_minutes",
}


def _fetch_leaderboard(guild_id, sort, global_lb, page, per_page=PER_PAGE):
    """Fetch one page of leaderboard rows. Runs inside a thread."""
    conn = get_db()
    try:
        cur = conn.cursor()
        guild_scope = bool(guild_id) and not global_lb

        if sort == "Voters":
            if guild_scope:
                total = cur.execute(
                    "SELECT COUNT(*) FROM users u JOIN vote_boosts v ON v.user_id = u.user_id "
                    "WHERE u.guild_id=? AND v.last_vote_at IS NOT NULL",
                    (guild_id,)
                ).fetchone()[0]
                rows = cur.execute(
                    "SELECT u.user_id, u.username, v.last_vote_at AS value FROM users u "
                    "JOIN vote_boosts v ON v.user_id = u.user_id "
                    "WHERE u.guild_id=? AND v.last_vote_at IS NOT NULL "
                    "ORDER BY v.last_vote_at DESC, u.user_id ASC LIMIT ? OFFSET ?",
                    (guild_id, per_page, (page - 1) * per_page)
                ).fetchall()
            else:
                total = cur.execute(
                    "SELECT COUNT(*) FROM vote_boosts WHERE last_vote_at IS NOT NULL"
                ).fetchone()[0]
                rows = cur.execute(
                    "SELECT u.user_id, u.username, v.last_vote_at AS value FROM vote_boosts v "
                    "LEFT JOIN (SELECT user_id, MAX(total_xp) AS total_xp, username FROM users GROUP BY user_id) u "
                    "ON u.user_id = v.user_id "
                    "WHERE v.last_vote_at IS NOT NULL "
                    "ORDER BY v.last_vote_at DESC, v.user_id ASC LIMIT ? OFFSET ?",
                    (per_page, (page - 1) * per_page)
                ).fetchall()
            return rows, total

        column = SORT_COLUMNS[sort]
        where_sql = "WHERE guild_id=?" if guild_scope else ""
        params = (guild_id,) if guild_scope else ()
        total = cur.execute(f"SELECT COUNT(*) FROM users {where_sql}", params).fetchone()[0]
        rows = cur.execute(
            f"SELECT user_id, username, {column} AS value FROM users {where_sql} "
            f"ORDER BY {column} DESC, total_xp DESC, user_id ASC LIMIT ? OFFSET ?",
            params + (per_page, (page - 1) * per_page)
        ).fetchall()
        return rows, total
    finally:
        conn.close()


def _fetch_rank(guild_id, user_id, sort, global_lb):
    """Return (rank, total_users) for a user under the given sort scope."""
    if sort == "Voters":
        return None, None
    conn = get_db()
    try:
        cur = conn.cursor()
        column = SORT_COLUMNS[sort]
        guild_scope = bool(guild_id) and not global_lb

        if guild_scope:
            mine = cur.execute(
                f"SELECT {column} FROM users WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            ).fetchone()
        else:
            mine = cur.execute(
                f"SELECT {column} FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
        if not mine:
            return None, None

        if guild_scope:
            rank = cur.execute(f"SELECT COUNT(*) + 1 FROM users WHERE guild_id=? AND {column} > ?", (guild_id, mine[0])).fetchone()[0]
            total = cur.execute("SELECT COUNT(*) FROM users WHERE guild_id=?", (guild_id,)).fetchone()[0]
        else:
            rank = cur.execute(f"SELECT COUNT(*) + 1 FROM users WHERE {column} > ?", (mine[0],)).fetchone()[0]
            total = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return rank, total
    finally:
        conn.close()


def _build_leaderboard_embed(bot, guild, sort, global_lb, rows, page, total_pages, highlight_user_id=None, rank_info=None):
    guild_scope = bool(guild) and not global_lb
    mode = "Server" if guild_scope else "Global"

    embed = discord.Embed(
        title=f"🏆 {mode} {sort} Leaderboard",
        color=discord.Color(0x7128fc),
        timestamp=discord.utils.utcnow()
    )

    lines = []
    top_avatar = None
    for i, row in enumerate(rows):
        user_id = row["user_id"]
        value = row["value"] or 0
        name = discord.utils.escape_markdown(str(row["username"] or "Unknown"))

        member = guild.get_member(user_id) if guild else None
        if member:
            name = discord.utils.escape_markdown(member.display_name)
            if top_avatar is None:
                top_avatar = member.display_avatar.url

        position = (page - 1) * PER_PAGE + i + 1
        if position == 1:
            rank = "🥇"
        elif position == 2:
            rank = "🥈"
        elif position == 3:
            rank = "🥉"
        else:
            rank = f"`#{position}`"

        marker = "➤ " if highlight_user_id and user_id == highlight_user_id else ""
        if sort == "Voters":
            lines.append(f"{marker}{rank} **{name}** | <t:{int(value)}:R>")
        else:
            label = format_minutes(value) if sort == "Total Voice" else f"{value:,}"
            lines.append(f"{marker}{rank} **{name}** | `{label}`")

    if lines:
        chunks = ["\n".join(lines)]
        if rank_info:
            chunks.append(f"📍 You are **#{rank_info['rank']}** of **{rank_info['total']:,}**")
        link = f"https://voidwave.xangey.dev/leaderboard?guild={guild.id}" if guild_scope else "https://voidwave.xangey.dev/leaderboard"
        chunks.append(f"**View online:** [Leaderboard]({link})")
        embed.description = "\n\n".join(chunks)
    else:
        embed.description = "no data yet :("

    if top_avatar:
        embed.set_thumbnail(url=top_avatar)
    elif not guild_scope:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    elif guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.set_footer(
        text=f"{guild.name if guild and guild_scope else 'Global'} Leaderboard • Page {page}/{total_pages} • Vote for 2x XP! /vote",
        icon_url=guild.icon.url if guild and guild_scope and guild.icon else None
    )

    return embed


class LeaderboardView(discord.ui.View):
    def __init__(self, bot, guild, sort, global_lb, page, total_pages, rank_info, invoker_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild = guild
        self.sort = sort
        self.global_lb = global_lb
        self.page = page
        self.total_pages = total_pages
        self.rank_info = rank_info
        self.invoker_id = invoker_id
        self.message = None
        self.highlight = False
        self._refresh_page_counter()

    def _refresh_page_counter(self):
        self.page_counter.label = f"Page {self.page} / {self.total_pages}"
        self.page_counter.disabled = True
        self.first_page.disabled = self.page <= 1
        self.prev_page.disabled = self.page <= 1
        self.next_page.disabled = self.page >= self.total_pages
        self.last_page.disabled = self.page >= self.total_pages

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(
            "Only the user who ran this command can browse the leaderboard.", ephemeral=True
        )
        return False

    async def _rebuild(self, interaction):
        rows, _ = await asyncio.to_thread(
            _fetch_leaderboard, self.guild.id if self.guild else 0, self.sort, self.global_lb, self.page
        )
        embed = _build_leaderboard_embed(
            self.bot, self.guild, self.sort, self.global_lb,
            rows, self.page, self.total_pages,
            highlight_user_id=self.invoker_id if self.highlight else None, rank_info=self.rank_info,
        )
        self._refresh_page_counter()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _goto(self, interaction, page):
        page = max(1, min(page, self.total_pages))
        if page == self.page:
            await interaction.response.defer()
            return
        self.page = page
        await self._rebuild(interaction)

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.secondary)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._goto(interaction, 1)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.primary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._goto(interaction, self.page - 1)

    @discord.ui.button(label="Page 1 / 1", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_counter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._goto(interaction, self.page + 1)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._goto(interaction, self.total_pages)

    @discord.ui.button(label="📍 My Rank", style=discord.ButtonStyle.secondary, row=1)
    async def my_rank(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.sort == "Voters":
            await interaction.response.send_message("My Rank is not available for the voters list.", ephemeral=True)
            return
        rank, total = await asyncio.to_thread(
            _fetch_rank, self.guild.id if self.guild else 0, self.invoker_id, self.sort, self.global_lb
        )
        if not rank:
            await interaction.response.send_message(
                "Your data file was not found! Try sending a message to create one.", ephemeral=True
            )
            return
        self.rank_info = {"rank": rank, "total": total}
        self.page = min((rank - 1) // PER_PAGE + 1, self.total_pages)
        self.highlight = True
        await self._rebuild(interaction)

    async def on_timeout(self):
        self.first_page.disabled = True
        self.prev_page.disabled = True
        self.page_counter.disabled = True
        self.next_page.disabled = True
        self.last_page.disabled = True
        self.my_rank.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


def _process_vc_ticks(records):
    conn = get_db()
    level_ups = []
    try:
        cur = conn.cursor()
        for guild_id, members_in_channel, self_deaf, member_id, display_name, username, avatar_key in records:
            now = time.time()
            blocked = cur.execute(
                "SELECT 1 FROM user_blocks WHERE user_id=? AND feature=? "
                "AND (expires_at IS NULL OR expires_at > ?)",
                (member_id, "leveling", int(now))
            ).fetchone()
            if blocked:
                continue

            user = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild_id, member_id)).fetchone()
            if not user:
                cur.execute("""
                    INSERT INTO users (
                        guild_id, user_id, display_name, username,
                        level, progress, out_of,
                        last_message, total_messages, total_messages_xp, total_xp,
                        vc_minutes, vc_xp_minutes,
                        avatar_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    guild_id, member_id, display_name, username,
                    0, 0, 100,
                    "", 0, 0, 0,
                    0, 0,
                    avatar_key
                ))

            last_vc_ts = last_vc.get((guild_id, member_id))
            if members_in_channel < 2 or self_deaf or (last_vc_ts is not None and now - last_vc_ts < VC_COOLDOWN):
                cur.execute(
                    "UPDATE users SET vc_minutes = vc_minutes + 1, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?",
                    (display_name, username, avatar_key, guild_id, member_id)
                )
                continue

            xp = random.randint(1, 8)
            boost_row = cur.execute(
                "SELECT multiplier FROM vote_boosts WHERE user_id=? AND expires_at > ?",
                (member_id, int(now))
            ).fetchone()
            multiplier = boost_row["multiplier"] if boost_row else 1.0
            if multiplier > 1:
                xp = int(xp * multiplier)
            last_vc[(guild_id, member_id)] = now

            cur.execute("""
                UPDATE users
                SET vc_minutes = vc_minutes + 1,
                    vc_xp_minutes = vc_xp_minutes + ?,
                    progress = progress + ?,
                    total_xp = total_xp + ?,
                    avatar_hash = ?,
                    username = ?,
                    display_name = ?
                WHERE guild_id=? AND user_id=?
            """, (1, xp, xp, avatar_key, username, display_name, guild_id, member_id))

            user = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild_id, member_id)).fetchone()
            progress = user["progress"]
            out_of = user["out_of"]
            level = user["level"]
            if progress >= out_of:
                progress -= out_of
                level += 1
                out_of = int(100 + level * 20)

                level_channel = cur.execute(
                    "SELECT level_channel_id, level_channel_enabled FROM guild_settings WHERE guild_id = ?",
                    (guild_id,)
                ).fetchone()
                level_channel = dict(level_channel) if level_channel else None

                boost = cur.execute(
                    "SELECT multiplier, expires_at FROM vote_boosts WHERE user_id=? AND expires_at > ?",
                    (member_id, int(time.time()))
                ).fetchone()

                level_roles = cur.execute(
                    "SELECT level, role_id FROM level_roles WHERE guild_id = ?",
                    (guild_id,)
                ).fetchall()
                new_role_ids = []
                if level_roles:
                    for req_level, role_id in level_roles:
                        if level >= req_level:
                            new_role_ids.append(role_id)

                cur.execute(
                    "UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?",
                    (level, progress, out_of, guild_id, member_id)
                )
                level_ups.append({
                    "guild_id": guild_id,
                    "member_id": member_id,
                    "display_name": display_name,
                    "level": level,
                    "progress": progress,
                    "out_of": out_of,
                    "boost": dict(boost) if boost else None,
                    "new_role_ids": new_role_ids,
                    "level_channel_id": level_channel["level_channel_id"] if level_channel else None,
                    "level_channel_enabled": bool(level_channel and level_channel["level_channel_enabled"]),
                })
        conn.commit()
    except Exception as e:
        logger.error("Failed to process VC XP: %s", e)
    finally:
        conn.close()
    return level_ups


class LevelingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.command(name="level", description="Check your server level")
    @app_commands.describe(hidden="Hide the command from others", user='Select a user to view their level')
    async def level(self, interaction: discord.Interaction, hidden: bool = False, user: discord.Member | None = None):
        await interaction.response.defer(ephemeral=hidden)
        if not interaction.guild:
            await interaction.followup.send("This command only works in servers.", ephemeral=True)
            return

        user = user or interaction.user # type: ignore

        conn = get_db()
        try:
            cur = conn.cursor()

            data = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (interaction.guild.id, user.id)).fetchone() # type: ignore

            if not data:
                await interaction.followup.send(f"{user.display_name}'s data file was not found! Try sending a message to create one.", ephemeral=hidden)
                return

            rank = cur.execute("SELECT COUNT(*) + 1 FROM users WHERE guild_id=? AND total_xp > ?", (interaction.guild.id, data["total_xp"])).fetchone()[0]

            global_rank = cur.execute("SELECT COUNT(*) + 1 FROM users WHERE total_xp > ?", (data["total_xp"],)).fetchone()[0]

            boost = cur.execute("SELECT multiplier, expires_at FROM vote_boosts WHERE user_id=? AND expires_at > ?", (user.id, int(time.time()))).fetchone()

            level_roles = cur.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ?", (interaction.guild.id,)).fetchall()
            level_roles = dict(level_roles) if level_roles else None

        except Exception as e:
            logger.error("Failed to fetch level data for %s in guild %s: %s", user, interaction.guild.id, e)
            await interaction.followup.send("Something went wrong while fetching your level data. Please try again later.", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
            return
        finally:
            conn.close()

        progress = data["progress"] or 0
        out_of = data["out_of"] or 0
        percent = (progress / out_of) * 100 if out_of else 0
        global_rank = f" (`#{global_rank}` Global)"

        filled_blocks = round(percent / 100 * 10)
        bar = f"{'▰'*filled_blocks}{'▱'*(10-filled_blocks)}"

        if boost:
            minutes = int((boost["expires_at"] - time.time()) // 60)
            boost_line = f"\n⚡ **{boost['multiplier']:.1f}x XP boost** active for **{minutes} min**!"
        else:
            boost_line = "\n⚡ Vote for **2x XP** for **4 hours**! `/vote`"

        embed = discord.Embed(
            title=f"{user.display_name}'s Level", # type: ignore
            color=discord.Color(0x7128fc)
        )

        embed.description = (
            f"**Level {data['level']}** • `#{rank}`{global_rank}\n"
            f"`{progress:,} / {out_of:,} XP` • {percent:.1f}%\n"
            f"[{bar}]{boost_line}"
        )

        embed.add_field(
            name="💬 Message Stats",
            value=(
                f"**Messages (XP):** `{(data['total_messages_xp'] or 0):,}`\n"
                f"**Total Messages:** `{(data['total_messages'] or 0):,}`"
            ),
            inline=True
        )

        embed.add_field(
            name="🎤 Voice Stats",
            value=(
                f"**Voice (XP):** `{format_minutes(data['vc_xp_minutes'] or 0)}`\n"
                f"**Total Voice:** `{format_minutes(data['vc_minutes'] or 0)}`"
            ),
            inline=True
        )

        if level_roles and interaction.guild:
            for req_level, role_id in sorted(level_roles.items()):
                if req_level > data["level"]:
                    role = interaction.guild.get_role(role_id)
                    if role:
                        levels_left = req_level - data["level"]
                        embed.add_field(
                            name="🏅 Next Level Reward",
                            value=f"Reach **Level {req_level}** to earn {role.mention} ({levels_left} level{'s' if levels_left != 1 else ''} away)!",
                            inline=False
                        )
                    break

        embed.add_field(
            name="🔗 Website",
            value=f"**View online:** [Dashboard](https://voidwave.xangey.dev/stats/{interaction.guild.id}/{user.id})", # type: ignore
            inline=False
        )

        embed.set_thumbnail(url=user.display_avatar.url) # type: ignore

        embed.set_footer(
            text=f"{interaction.guild.name} • Vote for 2x XP! /vote",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=hidden,
            allowed_mentions=discord.AllowedMentions(users=False)
        )

    @discord.app_commands.allowed_installs(guilds=True, users=False)
    @discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @discord.app_commands.command(name="leaderboard", description="Check the server level leaderboard")
    @app_commands.describe(hidden="Hide the command from others", sort='What to sort by', global_lb='Show global leaderboard')
    @app_commands.choices(
        sort=[
            app_commands.Choice(name="Level", value="Level"),
            app_commands.Choice(name="Total XP", value="Total XP"),
            app_commands.Choice(name="Total Messages", value="Total Messages"),
            app_commands.Choice(name="Total Voice", value="Total Voice"),
            app_commands.Choice(name="Voters", value="Voters")
        ]
    )
    async def leaderboard(self, interaction: discord.Interaction, sort: str = "Level", global_lb: bool = False, hidden: bool = False):
        await interaction.response.defer(ephemeral=hidden)
        if not interaction.guild:
            await interaction.followup.send("This command only works in servers.", ephemeral=True)
            return

        guild = interaction.guild
        try:
            rows, total = await asyncio.to_thread(_fetch_leaderboard, guild.id, sort, global_lb, 1)
            rank_info = None
            if sort != "Voters":
                rank, total_users = await asyncio.to_thread(_fetch_rank, guild.id, interaction.user.id, sort, global_lb)
                if rank:
                    rank_info = {"rank": rank, "total": total_users}
        except Exception as e:
            logger.error("Failed to fetch leaderboard for guild %s: %s", guild.id, e)
            await interaction.followup.send("Something went wrong while fetching the leaderboard. Please try again later.", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
            return

        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

        embed = _build_leaderboard_embed(
            self.bot, guild, sort, global_lb, rows, 1, total_pages,
            highlight_user_id=None, rank_info=rank_info
        )

        view = LeaderboardView(self.bot, guild, sort, global_lb, 1, total_pages, rank_info, interaction.user.id)
        view._refresh_page_counter()
        message = await interaction.followup.send(
            embed=embed,
            view=view,
            ephemeral=hidden,
            allowed_mentions=discord.AllowedMentions(users=False)
        )
        view.message = message

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="profile", description="Check your profile")
    @app_commands.describe(hidden="Hide the command from others", user='Select a user to view their profile')
    async def profile(self, interaction: discord.Interaction, hidden: bool = False, user: discord.User | discord.Member | None = None):
        await interaction.response.defer(ephemeral=hidden)
        user = user if user else interaction.user

        conn = get_db()
        try:
            cur = conn.cursor()

            total_xp = cur.execute("SELECT SUM(total_xp) FROM users WHERE user_id=?", (user.id,)).fetchone()[0] or 0
            total_messages = cur.execute("SELECT SUM(total_messages) FROM users WHERE user_id=?", (user.id,)).fetchone()[0] or 0
            total_vc_minutes = cur.execute("SELECT SUM(vc_minutes) FROM users WHERE user_id=?", (user.id,)).fetchone()[0] or 0

        except Exception as e:
            logger.error("Failed to fetch profile for %s (ID: %s): %s", user, user.id, e)
            await interaction.followup.send("Something went wrong while fetching your profile. Please try again later.", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
            return

        finally:
            conn.close()

        embed = discord.Embed(
            title=f"{user.display_name}'s Profile",
            description=(
                f"{user.mention} this is your global profile, combining stats across all servers.\n"
                f"Keep chatting and hanging out in voice channels to earn XP!"
            ),
            color=discord.Color(0x7128fc),
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="⭐ Leveling",
            value=(
                f"**Total XP:** `{total_xp:,}`"
            ),
            inline=True
        )

        embed.add_field(
            name="💬 Messages",
            value=(
                f"**Messages:** `{total_messages:,}`\n"
            ),
            inline=True
        )

        embed.add_field(
            name="🎤 Voice",
            value=(
                f"**Time:** `{format_minutes(total_vc_minutes)}`\n"
            ),
            inline=True
        )

        embed.set_thumbnail(url=user.display_avatar.url)

        embed.set_footer(
            text=f"user id: {user.id} • Vote for 2x XP! /vote",
            icon_url=user.display_avatar.url
        )

        await interaction.followup.send(embed=embed, ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))

    @tasks.loop(minutes=1)
    async def vc_xp_loop(self):
        records = []
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                members = [m for m in channel.members if not m.bot]
                for member in members:
                    records.append((
                        guild.id,
                        len(members),
                        bool(member.voice and member.voice.self_deaf),
                        member.id,
                        member.display_name,
                        member.name,
                        member.avatar.key if member.avatar else None,
                    ))

        now = time.time()
        for k in [k for k in last_vc if now - last_vc[k] > VC_COOLDOWN]:
            del last_vc[k]
        for k in [k for k in last_xp if now - last_xp[k] > XP_COOLDOWN]:
            del last_xp[k]

        level_ups = await asyncio.to_thread(_process_vc_ticks, records)

        for ev in level_ups:
            member = None
            for guild in self.bot.guilds:
                if guild.id == ev["guild_id"]:
                    member = guild.get_member(ev["member_id"])
                    break
            if not member:
                continue

            new_roles = []
            for role_id in ev["new_role_ids"]:
                role = member.guild.get_role(role_id)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role)
                        new_roles.append(role)
                    except discord.Forbidden:
                        logger.warning("Missing permissions to assign role %s in guild %s", role_id, ev["guild_id"])
                    except Exception as e:
                        logger.error("Failed to assign role: %s", e)

            channel = self.bot.get_channel(ev["level_channel_id"]) if ev["level_channel_id"] and ev["level_channel_enabled"] else None
            if channel and isinstance(channel, discord.TextChannel):
                embed = build_level_up_embed(
                    member=member,
                    level=ev["level"],
                    progress=ev["progress"],
                    out_of=ev["out_of"],
                    boost=ev["boost"],
                    new_roles=new_roles or None,
                )
                try:
                    await channel.send(content=f"{member.mention} reached Level {ev['level']}!", embed=embed)
                except discord.Forbidden:
                    logger.warning("Missing permissions to send level-up message in %s for guild %s", channel.id, ev["guild_id"])
                except Exception as e:
                    logger.error("Failed to send level-up message: %s", e)
                log_admin_event(
                    "level_up",
                    f"{ev['display_name']} reached level {ev['level']}",
                    guild_id=ev["guild_id"],
                    user_id=ev["member_id"],
                )


async def setup(bot):
    await bot.add_cog(LevelingCog(bot))
