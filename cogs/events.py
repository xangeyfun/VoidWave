from discord.ext import commands, tasks
import discord
import unicodedata
import traceback
import datetime
import aiohttp
import asyncio
import io
import time
import os
import json
from utils import (
    get_db, date, log_stats, add_message_xp, send_qotd, llm_worker,
    LLMRequest, get_command_path, extract_options, startup,
    last_llm, llm_queue, llm_queue_size, LLM_COOLDOWN, TOPGG_TOKEN, DBL_TOKEN,
    http_session as _http_session, log_admin_event, qotd_now, qotd_minutes,
    is_blocked, block_reply,
)
import utils


class EventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.feedback_webhook = None

    @commands.Cog.listener()
    async def on_ready(self):
        utils.http_session = aiohttp.ClientSession()
        print(f"\n{date()} INFO  Logged in as {self.bot.user}")
        try:
            print(f"{date()} DEBUG  Syncing commands...")
            start_sync = time.time()
            synced = await self.bot.tree.sync() # guild=guild)
            done = time.time()
        except Exception as e:
            print(f"{date()} ERROR  Error while syncing commands: {e}")
            exit(1)
        total_guilds = len(self.bot.guilds)
        total_members = sum(guild.member_count or 0 for guild in self.bot.guilds)
        sync_time = f"{done - start_sync:.2f}s"
        print(f"\n{date()} INFO  --- Bot is ready! ---")
        if self.bot.user:
            print(f"{date()} INFO  Invite link: https://discord.com/api/oauth2/authorize?client_id={self.bot.user.id}")
        else:
            exit(1)
        print(f"{date()} DEBUG  Connected to {total_guilds} guilds ({total_members} members)")
        print(f"{date()} DEBUG  Synced {len(synced)} slash commands in {sync_time}")
        print(f"{date()} DEBUG  Startup time: {done - startup:.4f} seconds")
        print(f"{date()} INFO ----------------------\n")
        for guild in self.bot.guilds:
            print(f"{date()} INFO  {''.join(c for c in guild.name if unicodedata.category(c) != 'So')[:49].strip():<50} | {guild.id:<20} | {str(guild.owner)[:19]:<20} [{guild.owner_id:<20}] | {guild.member_count:<5} members")
        print(f"{date()} INFO ----------------------\n")
        self.bot.loop.create_task(llm_worker(self.bot))
        self.qotd_loop.start()
        self.update_stats.start()
        self.stats_log_loop.start()
        leveling_cog = self.bot.get_cog("LevelingCog")
        if leveling_cog:
            leveling_cog.vc_xp_loop.start()
        self.rotate_status.start()
        self.update_topgg.start()
        self.vote_dm_loop.start()

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.application_command:
            guild_name = interaction.guild.name if interaction.guild else "DM"
            channel_name = getattr(interaction.channel, 'name', 'Unknown') if interaction.channel else ""
            if channel_name != "Unknown":
                channel_name = f"/#{channel_name}"
            else:
                channel_name = ""
            user_name = interaction.user.name if interaction.user else "Unknown"
            command_name = get_command_path(interaction)
            command_options = extract_options(interaction.data.get("options", []))
            user_id = interaction.user.id if interaction.user else "Unknown"
            guild_id = interaction.guild.id if interaction.guild else "DM"
            if guild_id != "DM":
                guild_id = f", guild_id: {guild_id}"
            else:
                guild_id = ""

            if os.getenv("DEBUG") != "true" and interaction.command and interaction.command.name == "ai" and "message" in command_options:
                command_options["message"] = "***"
            options_str = " ".join(f"{k}:{v}" for k, v in command_options.items())

            print(f"{date()} COMMAND '{command_name} {options_str}' used by '{user_name}' in '{guild_name}{channel_name}' (user_id: {user_id}{guild_id})")
            with open("command_logs.txt", "a") as f:
                f.write(f"{date()} COMMAND '{command_name} {options_str}' used by '{user_name}' in '{guild_name}{channel_name}' (user_id: {user_id}{guild_id})\n")

            log_admin_event(
                "command",
                f"/{command_name} {options_str} by {user_name} in {guild_name}",
                guild_id=interaction.guild.id if interaction.guild else None,
                user_id=interaction.user.id if interaction.user else None,
            )

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if os.getenv("DEBUG") == "true":
            print(f"{date()} MESSAGE  from {message.author} in {message.guild.name if message.guild else 'DM'}{'/' + message.channel.name if message.guild else ''}: {message.content} [{message.attachments[0].url if message.attachments else ''}] [{message.embeds[0].url if message.embeds else ''}] [{message.stickers[0].url if message.stickers else ''}]")

        if isinstance(message.channel, discord.DMChannel):
            await self.relay_dm_feedback(message)
            return

        message_reference = False

        if message.reference and message.reference.message_id:
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.HTTPException):
                ref_msg = None
            message_reference = ref_msg.author.id == 1442229230384709752 if ref_msg else False

        if f"<@{self.bot.user.id}>" in message.content or message_reference or message.channel.id == 1494361038420709466:
            if is_blocked(message.author.id, "ai"):
                await message.reply(block_reply(message.author.id, "ai", "using VoidWave AI features"))
                return

            if message.author.id in last_llm and time.time() - last_llm[message.author.id] < LLM_COOLDOWN and message.author.id != 996771607630585856:
                await message.reply(f"Slow down! VoidWave needs a breather. Try again in `{LLM_COOLDOWN - (time.time() - last_llm[message.author.id]):.1f} seconds.`")
                return

            if len(llm_queue_size) >= 10:
                await message.reply(f"VoidWave is busy right now. Try again in a bit! (Queue: `{len(llm_queue_size) + 1}`)")
                return

            msg = message.content.replace("<@1442229230384709752>", "").strip()
            msg = msg.replace("--stats", "").strip()

            for mention in message.mentions:
                msg = msg.replace(f"<@{mention.id}>", mention.name)

            for channel in message.channel_mentions:
                msg = msg.replace(f"<#{channel.id}>", channel.name)

            if not msg:
                await message.reply("Please provide a message for VoidWave to respond to.")
                return

            reply_info = None
            if message.reference and message.reference.message_id:
                try:
                    replied_msg = await message.channel.fetch_message(message.reference.message_id)
                except (discord.NotFound, discord.HTTPException):
                    replied_msg = None
                if replied_msg:
                    reply_info = {
                        "author": replied_msg.author.name,
                        "content": replied_msg.content
                    }

            req = LLMRequest(msg, message, reply_info)

            await llm_queue.put(req)
            llm_queue_size.append(message.author.id)

            last_llm[message.author.id] = time.time()

            position = len(llm_queue_size) - 1
            if position > 0:
                await message.reply(f"You are queued! Position in queue: **{position}**", delete_after=3)

        try:
            await add_message_xp(self.bot, message)

        except Exception as e:
            e = str(e)
            trace = traceback.format_exc()
            print(f"{date()} ERROR  Failed to process message for leveling: {e}\n```\n{trace}```")
            await message.reply(f"Something went wrong while processing that message. The developers have been notified.", allowed_mentions=discord.AllowedMentions(users=False))
            return

    async def relay_dm_feedback(self, message):
        if is_blocked(message.author.id, "feedback"):
            print(f"{date()} BLOCKED  Not relaying DM from {message.author} ({message.author.id}), feedback blocked")
            return

        channel = self.bot.get_channel(1540471117557403648)
        if not channel:
            print(f"{date()} ERROR  Feedback channel not found, dropped DM from {message.author} ({message.author.id})")
            return

        try:
            webhook = await self.get_feedback_webhook(channel)
            await self.send_dm_via_webhook(webhook, message)
            print(f"{date()} INFO  Relayed DM from {message.author} ({message.author.id}) to feedback channel")
        except Exception as e:
            print(f"{date()} ERROR  Webhook relay failed for DM from {message.author}: {e}, falling back to embed")
            try:
                await self.send_dm_embed_fallback(channel, message)
                print(f"{date()} INFO  Relayed DM from {message.author} ({message.author.id}) via embed fallback")
            except Exception as e2:
                print(f"{date()} ERROR  Failed to relay DM feedback from {message.author}: {e2}")

    async def get_feedback_webhook(self, channel):
        if self.feedback_webhook:
            return self.feedback_webhook

        for wh in await channel.webhooks():
            if wh.name == "VoidWave DM Relay" and wh.user and self.bot.user and wh.user.id == self.bot.user.id:
                self.feedback_webhook = wh
                return wh

        wh = await channel.create_webhook(name="VoidWave DM Relay", reason="Relaying DMs sent to VoidWave")
        self.feedback_webhook = wh
        return wh

    async def send_dm_via_webhook(self, webhook, message):
        parts = []

        if message.reference and isinstance(message.reference.resolved, discord.Message):
            ref = message.reference.resolved
            preview = (ref.content or "(no text)")[:150]
            parts.append(f"**Replying to {ref.author}:**\n> {preview}")

        text = message.content or "(no text)"
        if len(text) > 1800:
            text = text[:1800] + " ..."
        parts.append(text)

        links = [s.url for s in message.stickers]
        links += [a.url for a in message.attachments if (a.size or 0) > 8 * 1024 * 1024]
        if links:
            parts.append("\n".join(links))

        content = "\n\n".join(parts)
        content += f"\n-# DM from {message.author.name} ({message.author.id})"

        files = []
        for att in message.attachments:
            if len(files) >= 5 or (att.size or 0) > 8 * 1024 * 1024:
                continue
            try:
                data = await att.read()
                files.append(discord.File(io.BytesIO(data), filename=att.filename))
            except Exception as e:
                print(f"{date()} ERROR  Failed to download attachment {att.filename}: {e}")

        display_name = message.author.display_name[:80] or "Unknown User"
        await webhook.send(
            content=content,
            username=display_name,
            avatar_url=message.author.display_avatar.url,
            files=files,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def send_dm_embed_fallback(self, channel, message):
        embed = discord.Embed(
            title="📬 New DM to VoidWave",
            description=message.content or "*no text content*",
            color=0x7128fc,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="From", value=f"{message.author} (`{message.author.id}`)", inline=False)

        if message.reference and isinstance(message.reference.resolved, discord.Message):
            ref = message.reference.resolved
            preview = ref.content[:200] if ref.content else "*no text content*"
            embed.add_field(name="Replying to", value=f"**{ref.author}:** {preview}", inline=False)

        links = [a.url for a in message.attachments]
        links += [s.url for s in message.stickers]
        if links:
            embed.add_field(name="Attachments", value="\n".join(links), inline=False)

        embed.set_thumbnail(url=message.author.display_avatar.url)
        embed.set_footer(text="VoidWave • DM feedback")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        print(f"{date()} GUILD  Joined guild: {guild.name} | {guild.member_count} members | ID: {guild.id}")
        log_admin_event("guild_join", f"Joined {guild.name} ({guild.member_count} members)", guild_id=guild.id)
        log_channel = self.bot.get_channel(1475562384860119196)
        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        total_guilds = len(self.bot.guilds)
        embed = discord.Embed(
            title="🎉 Joined a new guild!",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="Guild Members", value=f"`{guild.member_count or 0}`", inline=True)
        embed.add_field(name="Total Members", value=f"`{total_members}`", inline=True)
        embed.add_field(name="Total Guilds", value=f"`{total_guilds}`", inline=True)
        embed.set_footer(text="VoidWave • Vote for 2x XP! /vote")
        if log_channel:
            await log_channel.send(embed=embed)
        else:
            print(f"{date()} ERROR  Join log channel not found, could not log join for guild {guild.id}")

        welcome_channel = guild.system_channel
        if not welcome_channel or not welcome_channel.permissions_for(guild.me).send_messages:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    welcome_channel = ch
                    break
        if not welcome_channel:
            return

        welcome_embed = discord.Embed(
            title="Hey! Thanks for adding VoidWave!",
            description=(
                "I'm here to make your server more fun with **levels**, **questions of the day**, and more.\n\n"
                "**Love VoidWave? Help it grow!**\n"
                "Voting is free and takes 5 seconds. You'll get **2x XP for 2 hours** (3h on weekends) and it helps VoidWave reach more servers.\n"
                "Run `/vote` in any channel to claim your boost!\n\n"
                "**Leveling works automatically**\n"
                "Members earn XP just by chatting and hanging out in voice channels. No setup needed.\n\n"
                "**Getting started**\n"
                "`/config auto` sets everything up in one command.\n"
                "`/config help` shows all configuration options.\n"
                "`/help` lists all available commands.\n\n"
                "Need help? Visit [voidwave.xangey.dev/setup](https://voidwave.xangey.dev/setup) for the full guide."
            ),
            color=0x7128fc,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        welcome_embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        welcome_embed.set_footer(text="Vote for 2x XP! /vote")
        await welcome_channel.send(embed=welcome_embed)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        print(f"{date()} GUILD  Removed from guild: {guild.name} | {guild.member_count} members | ID: {guild.id}")
        log_admin_event("guild_leave", f"Removed from {guild.name} ({guild.member_count} members)", guild_id=guild.id)
        try:
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM guild_settings WHERE guild_id=?", (guild.id,))
                cur.execute("DELETE FROM level_roles WHERE guild_id=?", (guild.id,))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"{date()} ERROR  Failed to clean up settings for guild {guild.id}: {e}")
        channel = self.bot.get_channel(1475562384860119196)
        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        total_guilds = len(self.bot.guilds)
        embed = discord.Embed(
            title="👋 Removed from a guild!",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="Guild Members", value=f"`{guild.member_count or 0}`", inline=True)
        embed.add_field(name="Total Members", value=f"`{total_members}`", inline=True)
        embed.add_field(name="Total Guilds", value=f"`{total_guilds}`", inline=True)
        embed.set_footer(text="VoidWave • Vote for 2x XP! /vote")
        if channel:
            await channel.send(embed=embed)
        else:
            print(f"{date()} ERROR  Leave log channel not found, could not log removal of guild {guild.id}")

    @tasks.loop(minutes=1)
    async def qotd_loop(self):
        conn = get_db()
        try:
            cur = conn.cursor()

            try:
                guilds = cur.execute("SELECT guild_id, qotd_channel, qotd_role_id, qotd_time, qotd_tz, last_qotd_date FROM guild_settings WHERE qotd_enabled = 1").fetchall()
            except Exception as e:
                print(f"{date()} ERROR  Failed to fetch QOTD guilds: {e}")
                return

            due = []
            for g in guilds:
                now = qotd_now(g["qotd_tz"])
                target = qotd_minutes(g["qotd_time"])
                if target is None:
                    target = qotd_minutes("16:00")
                if now.hour * 60 + now.minute != target:
                    continue
                today = now.strftime("%Y-%m-%d")
                if g["last_qotd_date"] == today:
                    continue
                due.append((g, today))

            if not due:
                return

            for g, today in due:
                cur.execute("UPDATE guild_settings SET last_qotd_date=? WHERE guild_id=?", (today, g["guild_id"]))
            conn.commit()

            guilds = [g for g, _ in due if self.bot.get_guild(g["guild_id"])]
            qotd_tasks = [send_qotd(self.bot, g["qotd_channel"], g["qotd_role_id"], g["guild_id"]) for g in guilds]
            await asyncio.gather(*qotd_tasks, return_exceptions=True)
            print(f"{date()} INFO  Sent QOTD for {len(guilds)} guilds")
        finally:
            conn.close()

    @tasks.loop(minutes=1)
    async def update_stats(self):
        conn = get_db()
        try:
            cur = conn.cursor()

            total_guilds = len(self.bot.guilds)
            total_members = sum(guild.member_count or 0 for guild in self.bot.guilds)

            cur.execute("UPDATE bot_stats SET total_guilds = ?, total_members = ?", (total_guilds, total_members))

            conn.commit()
        finally:
            conn.close()

    @tasks.loop(minutes=10)
    async def stats_log_loop(self):
        try:
            log_stats(self.bot)
        except Exception as e:
            print(f"{date()} ERROR  Failed to log stats: {e}")

    @tasks.loop(seconds=15)
    async def rotate_status(self):
        guilds = len(self.bot.guilds)
        members = sum(g.member_count or 0 for g in self.bot.guilds)

        statuses = [
            f"/help • {guilds} Servers",
            f"/help • {members:,} Members",
            f"/help • voidwave.xangey.dev",
            f"/help • VoidWave",
        ]

        activity = discord.CustomActivity(
            name=statuses[self.rotate_status.current_loop % len(statuses)]
        )

        await self.bot.change_presence(activity=activity)

    @tasks.loop(seconds=30)
    async def vote_dm_loop(self):
        conn = get_db()
        try:
            cur = conn.cursor()
            queued = cur.execute("SELECT id, user_id, payload FROM pending_dms WHERE kind = 'vote_thanks' ORDER BY id LIMIT 10").fetchall()
            for row in queued:
                await self.send_vote_thanks(row["user_id"], row["payload"])
                cur.execute("DELETE FROM pending_dms WHERE id = ?", (row["id"],))
                conn.commit()

            due = cur.execute("SELECT user_id, remind_at FROM vote_reminders WHERE remind_at <= ?", (int(time.time()),)).fetchall()
            for row in due:
                await self.send_vote_reminder(row["user_id"])
                cur.execute("DELETE FROM vote_reminders WHERE user_id = ?", (row["user_id"],))
                conn.commit()
        except Exception as e:
            print(f"{date()} ERROR  Vote DM loop failed: {e}")
        finally:
            conn.close()

    async def send_vote_thanks(self, user_id, payload):
        try:
            hours = json.loads(payload or "{}").get("hours", 2)
        except ValueError:
            hours = 2

        embed = discord.Embed(
            title="🗳️ Thanks for voting!",
            description=(
                f"Hey, thanks for voting for VoidWave on **Top.gg**! 💜\n\n"
                f"Your vote has been successfully registered and you now have **{hours} hours of Double XP**. ⚡"
            ),
            color=0x7128fc,
        )
        embed.add_field(
            name="Want a reminder?",
            value="Run `/vote-remind` and I'll DM you when you can vote again!",
            inline=False,
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url if self.bot.user else None)
        embed.set_footer(text="VoidWave • Vote for 2x XP! /vote")

        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            await user.send(embed=embed)
            print(f"{date()} INFO  Sent vote thanks DM to {user} ({user_id})")
        except discord.Forbidden:
            print(f"{date()} WARN  Could not DM vote thanks to {user_id} (DMs closed)")
        except (discord.NotFound, discord.HTTPException) as e:
            print(f"{date()} ERROR  Failed to send vote thanks DM to {user_id}: {e}")

    async def send_vote_reminder(self, user_id):
        embed = discord.Embed(
            title="⏰ Time to vote again!",
            description=(
                "Hey! You asked me to remind you. Your Top.gg vote cooldown is over, so you can vote for VoidWave again! 🗳️\n\n"
                "Voting gets you **2x XP for 2 hours** (**3h on weekends**). Thanks for supporting VoidWave! 💜"
            ),
            color=0x7128fc,
        )
        embed.add_field(
            name="Vote Link",
            value="<https://top.gg/bot/1442229230384709752/vote>",
            inline=False,
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url if self.bot.user else None)
        embed.set_footer(text="Don't want these? Run /vote-remind again to turn them off.")

        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            await user.send(embed=embed)
            print(f"{date()} INFO  Sent vote reminder DM to {user} ({user_id})")
        except discord.Forbidden:
            print(f"{date()} WARN  Could not DM vote reminder to {user_id} (DMs closed)")
        except (discord.NotFound, discord.HTTPException) as e:
            print(f"{date()} ERROR  Failed to send vote reminder DM to {user_id}: {e}")

    @tasks.loop(minutes=30)
    async def update_topgg(self):
        async with aiohttp.ClientSession() as session:
            if not TOPGG_TOKEN and not DBL_TOKEN:
                return

            if TOPGG_TOKEN:
                topgg_headers = {"Authorization": f"Bearer {TOPGG_TOKEN}"}
                await session.patch(
                    "https://top.gg/api/v1/projects/@me/metrics",
                    headers=topgg_headers,
                    json={
                        "server_count": len(self.bot.guilds),
                        "shard_count": self.bot.shard_count or 1,
                    },
                )

            if self.bot.user:
                try:
                    commands = await self.bot.tree.fetch_commands()
                    cmd_dicts = [c.to_dict() for c in commands]

                    if TOPGG_TOKEN:
                        await session.put(
                            "https://top.gg/api/v1/projects/@me/commands",
                            headers={**topgg_headers, "Content-Type": "application/json"},
                            json=cmd_dicts,
                        )

                    if DBL_TOKEN:
                        bot_id = str(self.bot.user.id)
                        dbl_headers = {"Authorization": DBL_TOKEN, "Content-Type": "application/json"}

                        await session.post(
                            f"https://discordbotlist.com/api/v1/bots/{bot_id}/stats",
                            headers=dbl_headers,
                            json={
                                "guilds": len(self.bot.guilds),
                                "users": sum(g.member_count or 0 for g in self.bot.guilds),
                            },
                        )

                        await session.post(
                            f"https://discordbotlist.com/api/v1/bots/{bot_id}/commands",
                            headers=dbl_headers,
                            json=cmd_dicts,
                        )
                except Exception as e:
                    print(f"{date()} ERROR  Failed to post to bot lists: {e}")


async def setup(bot):
    await bot.add_cog(EventsCog(bot))
