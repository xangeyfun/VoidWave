import asyncio
import json
import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.reminders import parse_reminder_time
from utils import get_db, log_admin_event

logger = logging.getLogger("cogs.giveaways")


def _truncate(text, limit=80):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _giveaway_choice_label(gw):
    return _truncate(f"#{gw['id']} - {gw['prize']}", 100)


def _giveaway_embed(gw, entry_count, winner_ids=None, ended=False, rerolled=False):
    gw = dict(gw)
    winner_ids = winner_ids or []
    embed = discord.Embed(
        title=f"🎉 {gw['prize']}",
        color=discord.Color(0x7128fc),
    )

    if ended:
        if winner_ids:
            header = "🔄 **Giveaway rerolled!**" if rerolled else "🎊 **Giveaway ended!**"
            embed.description = header + "\n\n" + "\n".join(f"🏆 <@{w}>" for w in winner_ids)
        else:
            embed.description = "🚫 **Giveaway ended with no eligible entries.**"
        embed.add_field(name="🏆 Winners", value=f"`{len(winner_ids)}`", inline=True)
        embed.add_field(name="👥 Entries", value=f"`{entry_count:,}`", inline=True)
        embed.add_field(name="🎁 Hosted by", value=f"<@{gw['host_id']}>", inline=True)
    else:
        embed.description = "Click the **Enter** button below for your chance to win! 🍀"
        embed.add_field(name="🏆 Winners", value=f"`{gw['winners_count']}`", inline=True)
        embed.add_field(name="👥 Entries", value=f"`{entry_count:,}`", inline=True)
        embed.add_field(name="⏳ Ends", value=f"<t:{gw['ends_at']}:R>", inline=True)
        if gw.get("required_role_id"):
            embed.add_field(name="🔒 Requirement", value=f"<@&{gw['required_role_id']}>", inline=False)
        embed.add_field(name="🎁 Hosted by", value=f"<@{gw['host_id']}>", inline=False)

    embed.set_footer(text=f"Giveaway #{gw['id']} • Vote for 2x XP with /vote")
    return embed


class GiveawayEnterView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Enter", emoji="🎉", style=discord.ButtonStyle.success, custom_id="giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_enter(interaction)


class GiveawayCog(commands.Cog):
    giveaway = discord.app_commands.Group(
        name="giveaway",
        description="Host and manage giveaways",
        default_permissions=discord.Permissions(manage_guild=True),
        allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=False),
        allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False),
    )

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        try:
            self.bot.add_view(GiveawayEnterView(self))
        except Exception as e:
            logger.error("Failed to register persistent giveaway view: %s", e)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        if isinstance(error, discord.app_commands.BotMissingPermissions):
            perms = ", ".join(f"**{p.replace('_', ' ').title()}**" for p in error.missing_permissions)
            msg = f"> I need {perms} permission to do that. Ask a server admin to grant it to me."
        elif isinstance(error, discord.app_commands.MissingPermissions):
            msg = "> You need **Manage Server** permissions to use this command."
        else:
            return

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    def _resolve(self, cur, guild_id, ref):
        try:
            number = int(ref.strip())
        except (ValueError, AttributeError):
            return None
        return cur.execute(
            "SELECT * FROM giveaways WHERE guild_id=? AND (message_id=? OR id=?) ORDER BY id DESC LIMIT 1",
            (guild_id, number, number)
        ).fetchone()

    def _autocomplete_giveaways(self, guild_id, current, ended):
        current = (current or "").strip().lstrip("#").lower()
        conn = get_db()
        try:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT id, message_id, prize FROM giveaways WHERE guild_id=? AND ended=? ORDER BY id DESC LIMIT 50",
                (guild_id or 0, 1 if ended else 0)
            ).fetchall()
        except Exception as e:
            logger.error("Giveaway autocomplete query failed: %s", e)
            return []
        finally:
            conn.close()

        choices = []
        for gw in rows:
            label = _giveaway_choice_label(gw)
            if current and current not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label, value=str(gw["message_id"] or gw["id"])))
        return choices[:25]

    async def _fetch_channel(self, channel_id):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None
        return channel

    async def handle_enter(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Giveaways only run in servers.", ephemeral=True)
            return

        conn = get_db()
        try:
            cur = conn.cursor()
            gw = cur.execute(
                "SELECT * FROM giveaways WHERE message_id=? AND guild_id=?",
                (interaction.message.id, interaction.guild.id)
            ).fetchone()
            if gw is None or gw["ended"]:
                await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
                return
            if gw["ends_at"] <= int(time.time()):
                await interaction.response.send_message("This giveaway is ending right now, hang tight for the results!", ephemeral=True)
                return

            if gw["required_role_id"]:
                member = interaction.user
                has_role = isinstance(member, discord.Member) and any(r.id == gw["required_role_id"] for r in member.roles)
                if not has_role:
                    await interaction.response.send_message(f"You need the <@&{gw['required_role_id']}> role to enter this giveaway.", ephemeral=True)
                    return

            existing = cur.execute(
                "SELECT 1 FROM giveaway_entries WHERE giveaway_id=? AND user_id=?",
                (gw["id"], interaction.user.id)
            ).fetchone()
            if existing:
                await interaction.response.send_message("You're already entered. Good luck! 🍀", ephemeral=True)
                return

            cur.execute(
                "INSERT INTO giveaway_entries (giveaway_id, user_id, entered_at) VALUES (?, ?, ?)",
                (gw["id"], interaction.user.id, int(time.time()))
            )
            conn.commit()
            entry_count = cur.execute(
                "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id=?", (gw["id"],)
            ).fetchone()[0]
        except Exception as e:
            logger.error("Failed to register giveaway entry: %s", e)
            await interaction.response.send_message("Something went wrong while entering. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        await interaction.response.send_message("You're in! Good luck! 🍀", ephemeral=True)
        try:
            await interaction.message.edit(embed=_giveaway_embed(gw, entry_count))
        except discord.HTTPException:
            pass

    @discord.app_commands.checks.has_permissions(manage_guild=True)
    @giveaway.command(name="start", description="Start a new giveaway")
    @app_commands.describe(
        prize="What the winner(s) receive",
        duration="How long it runs, e.g. 1h, 2d, or tomorrow 18:00",
        winners="How many winners to pick",
        channel="Channel to post in (defaults to here)",
        required_role="Role members must have to enter (optional)",
    )
    async def start(self, interaction: discord.Interaction, prize: str, duration: str, winners: app_commands.Range[int, 1, 50] = 1, channel: discord.TextChannel = None, required_role: discord.Role = None):
        await interaction.response.defer(ephemeral=True)
        prize = prize.strip()
        if not prize:
            await interaction.followup.send("Give the giveaway a prize.", ephemeral=True)
            return

        try:
            ends_at = int(parse_reminder_time(duration, "UTC").timestamp())
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        target = channel or interaction.channel
        if target is None:
            await interaction.followup.send("I couldn't work out where to post that.", ephemeral=True)
            return

        me = interaction.guild.me if interaction.guild else None
        if me and not target.permissions_for(me).send_messages:
            await interaction.followup.send(f"I can't post in {target.mention}. Pick another channel or grant me **Send Messages** there.", ephemeral=True)
            return

        now = int(time.time())
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO giveaways (guild_id, channel_id, host_id, prize, winners_count, required_role_id, ends_at, created_at, ended, winner_ids) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)",
                (interaction.guild_id, target.id, interaction.user.id, prize, winners, required_role.id if required_role else None, ends_at, now)
            )
            conn.commit()
            gw_id = cur.lastrowid
        except Exception as e:
            logger.error("Failed to create giveaway in guild %s: %s", interaction.guild_id, e)
            await interaction.followup.send("Something went wrong while creating the giveaway. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        gw = {
            "id": gw_id,
            "host_id": interaction.user.id,
            "prize": prize,
            "winners_count": winners,
            "required_role_id": required_role.id if required_role else None,
            "ends_at": ends_at,
        }
        embed = _giveaway_embed(gw, 0)
        try:
            message = await target.send(embed=embed, view=GiveawayEnterView(self))
        except discord.HTTPException as e:
            logger.error("Failed to send giveaway message: %s", e)
            await interaction.followup.send("I couldn't post the giveaway message.", ephemeral=True)
            return

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE giveaways SET message_id=? WHERE id=?", (message.id, gw_id))
            conn.commit()
        finally:
            conn.close()

        log_admin_event("giveaway_start", f"#{gw_id} '{prize}' in #{target.name} ({winners} winner(s))", interaction.guild_id, interaction.user.id)
        logger.info("Giveaway #%s started in guild %s by %s", gw_id, interaction.guild_id, interaction.user)
        await interaction.followup.send(
            f"🎉 **Giveaway #{gw_id}** for **{prize}** is live in {message.jump_url}",
            ephemeral=True,
        )

    @discord.app_commands.checks.has_permissions(manage_guild=True)
    @giveaway.command(name="end", description="End a giveaway early and pick winners")
    @app_commands.describe(giveaway="Start typing to pick a giveaway, or paste its message ID")
    async def end(self, interaction: discord.Interaction, giveaway: str):
        await interaction.response.defer(ephemeral=True)
        conn = get_db()
        try:
            cur = conn.cursor()
            gw = self._resolve(cur, interaction.guild_id, giveaway)
        finally:
            conn.close()

        if gw is None:
            await interaction.followup.send("I couldn't find that giveaway here.", ephemeral=True)
            return
        if gw["ended"]:
            await interaction.followup.send("That giveaway has already ended.", ephemeral=True)
            return

        winners = await self._finish(gw["id"])
        if winners:
            mentions = " ".join(f"<@{w}>" for w in winners)
            await interaction.followup.send(
                f"🎉 Ended **Giveaway #{gw['id']}** for **{gw['prize']}** • winner(s): {mentions}",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"🎉 Ended **Giveaway #{gw['id']}** for **{gw['prize']}**, but there were no entries.",
                ephemeral=True,
            )

    @discord.app_commands.checks.has_permissions(manage_guild=True)
    @giveaway.command(name="reroll", description="Pick new winners for an ended giveaway")
    @app_commands.describe(giveaway="Start typing to pick a giveaway, or paste its message ID", winners="How many winners to reroll")
    async def reroll(self, interaction: discord.Interaction, giveaway: str, winners: app_commands.Range[int, 1, 50] = 1):
        await interaction.response.defer(ephemeral=True)
        conn = get_db()
        try:
            cur = conn.cursor()
            gw = self._resolve(cur, interaction.guild_id, giveaway)
            if gw is None:
                await interaction.followup.send("I couldn't find that giveaway here.", ephemeral=True)
                return
            if not gw["ended"]:
                await interaction.followup.send("End the giveaway before rerolling winners.", ephemeral=True)
                return

            previous = set(json.loads(gw["winner_ids"] or "[]"))
            entries = [
                r["user_id"] for r in cur.execute(
                    "SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", (gw["id"],)
                ).fetchall()
            ]
            pool = [u for u in entries if u not in previous]
            if not pool:
                await interaction.followup.send("There is nobody left to reroll to.", ephemeral=True)
                return

            new_winners = random.sample(pool, min(winners, len(pool)))
            cur.execute("UPDATE giveaways SET winner_ids=? WHERE id=?", (json.dumps(new_winners), gw["id"]))
            conn.commit()
            entry_count = len(entries)
        except Exception as e:
            logger.error("Failed to reroll giveaway #%s: %s", giveaway, e)
            await interaction.followup.send("Something went wrong while rerolling. Please try again later.", ephemeral=True)
            return
        finally:
            conn.close()

        gw = dict(gw)
        gw["winner_ids"] = json.dumps(new_winners)
        await self._announce_finish(gw, new_winners, entry_count, rerolled=True)
        log_admin_event("giveaway_reroll", f"#{gw['id']} '{gw['prize']}' -> {len(new_winners)} winner(s)", interaction.guild_id, interaction.user.id)
        mentions = " ".join(f"<@{w}>" for w in new_winners)
        await interaction.followup.send(f"🔄 Rerolled **Giveaway #{gw['id']}** • new winner(s): {mentions}", ephemeral=True)

    @discord.app_commands.checks.has_permissions(manage_guild=True)
    @giveaway.command(name="cancel", description="Cancel a giveaway without picking winners")
    @app_commands.describe(giveaway="Start typing to pick a giveaway, or paste its message ID")
    async def cancel(self, interaction: discord.Interaction, giveaway: str):
        await interaction.response.defer(ephemeral=True)
        conn = get_db()
        try:
            cur = conn.cursor()
            gw = self._resolve(cur, interaction.guild_id, giveaway)
            if gw is None:
                await interaction.followup.send("I couldn't find that giveaway here.", ephemeral=True)
                return
            if gw["ended"]:
                await interaction.followup.send("That giveaway has already ended.", ephemeral=True)
                return
            cur.execute("UPDATE giveaways SET ended=1 WHERE id=?", (gw["id"],))
            conn.commit()
            entry_count = cur.execute(
                "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id=?", (gw["id"],)
            ).fetchone()[0]
        finally:
            conn.close()

        channel = await self._fetch_channel(gw["channel_id"])
        if channel is not None and gw["message_id"]:
            try:
                message = await channel.fetch_message(gw["message_id"])
                embed = _giveaway_embed(gw, entry_count, winner_ids=None, ended=True)
                embed.description = "🚫 **This giveaway was cancelled.**"
                await message.edit(embed=embed, view=None)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                logger.warning("Couldn't update cancelled giveaway #%s message: %s", gw["id"], e)

        log_admin_event("giveaway_cancel", f"#{gw['id']} '{gw['prize']}'", interaction.guild_id, interaction.user.id)
        await interaction.followup.send(f"🚫 Cancelled **Giveaway #{gw['id']}** for **{gw['prize']}**.", ephemeral=True)

    @discord.app_commands.checks.has_permissions(manage_guild=True)
    @giveaway.command(name="list", description="List active giveaways in this server")
    async def list_giveaways(self, interaction: discord.Interaction):
        conn = get_db()
        try:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT g.*, (SELECT COUNT(*) FROM giveaway_entries e WHERE e.giveaway_id = g.id) AS entries "
                "FROM giveaways g WHERE g.guild_id=? AND g.ended=0 ORDER BY g.ends_at ASC",
                (interaction.guild_id,)
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            await interaction.response.send_message("There are no active giveaways right now. Start one with `/giveaway start`.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎉 Active Giveaways",
            description="Start typing an ID in `/giveaway end`, `/giveaway reroll`, or `/giveaway cancel` and autocomplete will find it for you.",
            color=discord.Color(0x7128fc),
            timestamp=discord.utils.utcnow(),
        )
        for gw in rows[:25]:
            embed.add_field(
                name=_truncate(f"#{gw['id']} • {gw['prize']}", 256),
                value=f"<#{gw['channel_id']}> • `{gw['entries']}` entries • ends <t:{gw['ends_at']}:R>",
                inline=False,
            )
        if len(rows) > 25:
            embed.add_field(name="…", value=f"and {len(rows) - 25} more", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @end.autocomplete("giveaway")
    async def end_autocomplete(self, interaction: discord.Interaction, current: str):
        return self._autocomplete_giveaways(interaction.guild_id, current, ended=False)

    @reroll.autocomplete("giveaway")
    async def reroll_autocomplete(self, interaction: discord.Interaction, current: str):
        return self._autocomplete_giveaways(interaction.guild_id, current, ended=True)

    @cancel.autocomplete("giveaway")
    async def cancel_autocomplete(self, interaction: discord.Interaction, current: str):
        return self._autocomplete_giveaways(interaction.guild_id, current, ended=False)

    async def _finish(self, giveaway_id):
        def prep():
            conn = get_db()
            try:
                cur = conn.cursor()
                gw = cur.execute("SELECT * FROM giveaways WHERE id=?", (giveaway_id,)).fetchone()
                if gw is None or gw["ended"]:
                    return None, [], 0
                entries = [
                    r["user_id"] for r in cur.execute(
                        "SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", (giveaway_id,)
                    ).fetchall()
                ]
                winners = random.sample(entries, min(gw["winners_count"], len(entries))) if entries else []
                cur.execute("UPDATE giveaways SET ended=1, winner_ids=? WHERE id=?", (json.dumps(winners), giveaway_id))
                conn.commit()
                return dict(gw), winners, len(entries)
            except Exception as e:
                logger.error("Failed to finish giveaway #%s: %s", giveaway_id, e)
                return None, [], 0
            finally:
                conn.close()

        gw, winners, entry_count = await asyncio.to_thread(prep)
        if gw is None:
            return []
        await self._announce_finish(gw, winners, entry_count)
        log_admin_event("giveaway_end", f"#{gw['id']} '{gw['prize']}' -> {len(winners)} winner(s)", gw["guild_id"], gw["host_id"])
        return winners

    async def _announce_finish(self, gw, winners, entry_count, rerolled=False):
        channel = await self._fetch_channel(gw["channel_id"])
        if channel is None:
            logger.warning("Giveaway #%s channel %s unreachable", gw["id"], gw["channel_id"])
            return

        message = None
        if gw.get("message_id"):
            try:
                message = await channel.fetch_message(gw["message_id"])
                await message.edit(
                    embed=_giveaway_embed(gw, entry_count, winner_ids=winners, ended=True, rerolled=rerolled),
                    view=None,
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                message = None
                logger.warning("Couldn't update giveaway #%s message: %s", gw["id"], e)

        if winners:
            mentions = " ".join(f"<@{w}>" for w in winners)
            embed = discord.Embed(
                title="🔄 Giveaway Rerolled!" if rerolled else "🎉 Giveaway Ended!",
                description=f"Congratulations {mentions}!\nYou won **{gw['prize']}**! 🎁",
                color=discord.Color(0x7128fc),
            )
            if message is not None:
                embed.add_field(name="🎉 Giveaway", value=f"[Jump to message]({message.jump_url})", inline=False)
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True))
            except discord.HTTPException:
                pass
            for user_id in winners:
                try:
                    user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                except (discord.NotFound, discord.HTTPException):
                    user = None
                if user is None:
                    continue
                dm = discord.Embed(
                    title="🎉 You won a giveaway!",
                    description=f"You won **{gw['prize']}** in {channel.mention}! Congratulations! 🎁",
                    color=discord.Color(0x7128fc),
                )
                if message is not None:
                    dm.add_field(name="🎉 Giveaway", value=f"[Jump to message]({message.jump_url})", inline=False)
                try:
                    await user.send(embed=dm)
                except (discord.Forbidden, discord.HTTPException):
                    pass
        else:
            embed = discord.Embed(
                title="🎊 Giveaway Ended",
                description=f"No eligible entries for **{gw['prize']}**, so there are no winners.",
                color=discord.Color(0x7128fc),
            )
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    @tasks.loop(seconds=15)
    async def giveaway_loop(self):
        def fetch_due():
            conn = get_db()
            try:
                cur = conn.cursor()
                return [r["id"] for r in cur.execute(
                    "SELECT id FROM giveaways WHERE ended=0 AND ends_at <= ? ORDER BY ends_at",
                    (int(time.time()),)
                ).fetchall()]
            finally:
                conn.close()

        try:
            due = await asyncio.to_thread(fetch_due)
        except Exception as e:
            logger.error("Failed to fetch due giveaways: %s", e)
            return

        for giveaway_id in due:
            await self._finish(giveaway_id)


async def setup(bot):
    await bot.add_cog(GiveawayCog(bot))
