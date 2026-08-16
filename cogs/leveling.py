from discord import app_commands
from discord.ext import commands, tasks
import discord
import random
import time
from utils import get_db, date, format_minutes, last_vc, VC_COOLDOWN, get_vote_boost, build_level_up_embed


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

        except Exception as e:
            print(f"{date()} ERROR  Failed to fetch level data for {user} in guild {interaction.guild.id}: {e}")
            await interaction.followup.send("Something went wrong while fetching your level data. Please try again later.", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
            return
        finally:
            conn.close()

        progress = data["progress"]
        out_of = data["out_of"]
        percent = (progress / out_of) * 100 if out_of else 0
        global_rank = f" (`#{global_rank}` Global)"

        filled_blocks = round(percent / 100 * 10)
        bar = f"{'▰'*filled_blocks}{'▱'*(10-filled_blocks)}"

        if boost:
            minutes = int((boost["expires_at"] - time.time()) // 60)
            boost_line = f"\n⚡ **{boost['multiplier']:.1f}x XP boost** active for **{minutes} min**!"
        else:
            boost_line = "\n⚡ Vote for **2x XP** for **2 hours**! `/vote`"

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
                f"**Messages (XP):** `{data['total_messages_xp']:,}`\n"
                f"**Total Messages:** `{data['total_messages']:,}`"
            ),
            inline=True
        )

        embed.add_field(
            name="🎤 Voice Stats",
            value=(
                f"**Voice (XP):** `{format_minutes(data['vc_xp_minutes'])}`\n"
                f"**Total Voice:** `{format_minutes(data['vc_minutes'])}`"
            ),
            inline=True
        )

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
            app_commands.Choice(name="Total Voice", value="Total Voice")
        ]
    )
    async def leaderboard(self, interaction: discord.Interaction, sort: str, global_lb: bool = False, hidden: bool = False):
        await interaction.response.defer(ephemeral=hidden)
        if not interaction.guild:
            await interaction.followup.send("This command only works in servers.", ephemeral=True)
            return

        conn = get_db()
        cur = conn.cursor()

        try:
            if not global_lb:
                if sort == "Level":
                    leaderboard_data = cur.execute("SELECT username, level, guild_id FROM users WHERE guild_id=? ORDER BY level DESC LIMIT 10", (interaction.guild.id,)).fetchall()
                elif sort == "Total XP":
                    leaderboard_data = cur.execute("SELECT username, total_xp, guild_id FROM users WHERE guild_id=? ORDER BY total_xp DESC LIMIT 10", (interaction.guild.id,)).fetchall()
                elif sort == "Total Messages":
                    leaderboard_data = cur.execute("SELECT username, total_messages, guild_id FROM users WHERE guild_id=? ORDER BY total_messages DESC LIMIT 10", (interaction.guild.id,)).fetchall()
                elif sort == "Total Voice":
                    leaderboard_data = cur.execute("SELECT username, vc_minutes, guild_id FROM users WHERE guild_id=? ORDER BY vc_minutes DESC LIMIT 10", (interaction.guild.id,)).fetchall()
            else:
                if sort == "Level":
                    leaderboard_data = cur.execute("SELECT username, level, guild_id FROM users ORDER BY level DESC LIMIT 10").fetchall()
                elif sort == "Total XP":
                    leaderboard_data = cur.execute("SELECT username, total_xp, guild_id FROM users ORDER BY total_xp DESC LIMIT 10").fetchall()
                elif sort == "Total Messages":
                    leaderboard_data = cur.execute("SELECT username, total_messages, guild_id FROM users ORDER BY total_messages DESC LIMIT 10").fetchall()
                elif sort == "Total Voice":
                    leaderboard_data = cur.execute("SELECT username, vc_minutes, guild_id FROM users ORDER BY vc_minutes DESC LIMIT 10").fetchall()

        except Exception as e:
            print(f"{date()} ERROR  Failed to fetch leaderboard for guild {interaction.guild.id}: {e}")
            await interaction.followup.send("Something went wrong while fetching the leaderboard. Please try again later.", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
            return
        finally:
            conn.close()

        embed = discord.Embed(
            title=f"🏆 {'Global' if global_lb else 'Server'} {sort} Leaderboard",
            color=discord.Color(0x7128fc),
            timestamp=discord.utils.utcnow()
        )

        lines = []

        for i, row in enumerate(leaderboard_data):
            username, level = row[0], row[1]

            if i == 0:
                rank = "🥇"
            elif i == 1:
                rank = "🥈"
            elif i == 2:
                rank = "🥉"
            else:
                rank = f"`#{i+1}`"

            line = f"{rank} **{username}** | `{format_minutes(level) if sort == 'Total Voice' else f'{level:,}'}`"
            lines.append(line)

        link = f"https://voidwave.xangey.dev/leaderboard?guild={interaction.guild.id}" if not global_lb else "https://voidwave.xangey.dev/leaderboard"

        embed.description = "\n".join(lines) + f"\n\n**View online:** [Leaderboard]({link})" if lines else "no data yet :("

        embed.set_thumbnail(
            url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon and not global_lb else self.bot.user.display_avatar.url
        )

        embed.set_footer(
            text=f"{interaction.guild.name if interaction.guild and not global_lb else 'Global'} Leaderboard • Vote for 2x XP! /vote",
            icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon and not global_lb else None
        )

        await interaction.followup.send(embed=embed, ephemeral=hidden)

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
            print(f"{date()} ERROR  Failed to fetch profile for {user} (ID: {user.id}): {e}")
            await interaction.followup.send("Something went wrong while fetching your profile. Please try again later.", ephemeral=hidden, allowed_mentions=discord.AllowedMentions(users=False))
            return

        finally:
            conn.close()

        embed = discord.Embed(
            title=f"{user.display_name}'s Profile",
            description=(
                f"> {user.mention} • your global profile, combining stats across all servers.\n"
                f"> Keep chatting and hanging out in voice channels to earn XP!"
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
        conn = get_db()
        try:
            cur = conn.cursor()
            for guild in self.bot.guilds:
                for channel in guild.voice_channels:
                    members = [m for m in channel.members if not m.bot]

                    for member in members:
                        user = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild.id, member.id)).fetchone()
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
                                guild.id, member.id, member.display_name, member.name,
                                0, 0, 100,
                                "", 0, 0, 0,
                                0, 0,
                                member.avatar.key if member.avatar else None
                            ))
                            conn.commit()

                        if len(members) < 2:
                            cur.execute("UPDATE users SET vc_minutes = vc_minutes + 1, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?", (member.display_name, member.name, member.avatar.key if member.avatar else None, guild.id, member.id))
                            conn.commit()
                            continue

                        if member.id in last_vc and time.time() - last_vc[member.id] < VC_COOLDOWN:
                            cur.execute("UPDATE users SET vc_minutes = vc_minutes + 1, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?", (member.display_name, member.name, member.avatar.key if member.avatar else None, guild.id, member.id))
                            conn.commit()
                            continue

                        if member.voice.self_deaf:
                            cur.execute("UPDATE users SET vc_minutes = vc_minutes + 1, display_name=?, username=?, avatar_hash=? WHERE guild_id=? AND user_id=?", (member.display_name, member.name, member.avatar.key if member.avatar else None, guild.id, member.id))
                            conn.commit()
                            continue

                        try:
                            xp = random.randint(1, 8)
                            multiplier = get_vote_boost(member.id)
                            if multiplier > 1:
                                xp = int(xp * multiplier)
                            last_vc[member.id] = time.time()
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
                            """, (1, xp, xp, member.avatar.key if member.avatar else None, member.name, member.display_name, guild.id, member.id))
                            conn.commit()
                            user = cur.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild.id, member.id)).fetchone()
                            progress = user["progress"]
                            out_of = user["out_of"]
                            level = user["level"]
                            if progress >= out_of:
                                progress -= out_of
                                level += 1
                                out_of = int(100 + level * 20)

                                level_channel = (cur.execute("SELECT level_channel_id, level_channel_enabled FROM guild_settings WHERE guild_id = ?", (guild.id,)).fetchone())
                                level_channel = dict(level_channel) if level_channel else None

                                channel = self.bot.get_channel(level_channel["level_channel_id"]) if level_channel and level_channel["level_channel_id"] and level_channel["level_channel_enabled"] else None
                                has_channel = bool(channel and isinstance(channel, discord.TextChannel))

                                boost = cur.execute("SELECT multiplier, expires_at FROM vote_boosts WHERE user_id=? AND expires_at > ?", (member.id, int(time.time()))).fetchone()

                                level_roles = (cur.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ?", (guild.id,)).fetchall())
                                level_roles = dict(level_roles) if level_roles else None

                                new_roles = []
                                if level_roles:
                                    for req_level, role_id in level_roles.items():
                                        if level >= req_level:
                                            role = guild.get_role(role_id)

                                            if role and role not in member.roles:
                                                try:
                                                    await member.add_roles(role)
                                                    new_roles.append(role)
                                                except discord.Forbidden:
                                                    print(f"{date()} WARN  Missing permissions to assign role {role_id} in guild {guild.id}")
                                                except Exception as e:
                                                    print(f"{date()} ERROR  Failed to assign role: {e}")

                                if has_channel:
                                    embed = build_level_up_embed(
                                        member=member,
                                        level=level,
                                        progress=progress,
                                        out_of=out_of,
                                        boost=dict(boost) if boost else None,
                                        new_roles=new_roles or None,
                                    )
                                    try:
                                        await channel.send(embed=embed)
                                    except discord.Forbidden:
                                        print(f"{date()} WARN  Missing permissions to send level-up message in {channel.id} for guild {guild.id}")
                                    except Exception as e:
                                        print(f"{date()} ERROR  Failed to send level-up message: {e}")
                                cur.execute("UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?", (level, progress, out_of, guild.id, member.id))
                                conn.commit()
                        except Exception as e:
                            print(f"{date()} ERROR  Failed to update VC XP for {member} in {guild}: {e}")
        finally:
            conn.close()


async def setup(bot):
    await bot.add_cog(LevelingCog(bot))
