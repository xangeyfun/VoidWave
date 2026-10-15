import asyncio
import logging
import math
import random
import re

import discord
from discord import Interaction, app_commands
from discord.ext import commands
from simpleeval import simple_eval

import utils

logger = logging.getLogger("cogs.fun")


class FunCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="animal", description="Get a random animal picture")
    @app_commands.describe(animal="The type of animal", hidden="Hide the command from others")
    @app_commands.choices(animal=[
        app_commands.Choice(name="🐕 Dog", value="dog"),
        app_commands.Choice(name="🐱 Cat", value="cat"),
        app_commands.Choice(name="🦆 Duck", value="duck"),
        app_commands.Choice(name="🦊 Fox", value="fox"),
        app_commands.Choice(name="🐼 Panda", value="panda"),
        app_commands.Choice(name="🐨 Koala", value="koala"),
        app_commands.Choice(name="🦘 Kangaroo", value="kangaroo"),
        app_commands.Choice(name="🐋 Whale", value="whale"),
        app_commands.Choice(name="🐦 Bird", value="bird"),
        app_commands.Choice(name="🐹 Capybara", value="capybara"),
        app_commands.Choice(name="🦔 Hedgehog", value="hedgehog"),
        app_commands.Choice(name="🐧 Penguin", value="penguin"),
        app_commands.Choice(name="🐢 Turtle", value="turtle"),
        app_commands.Choice(name="🦁 Lion", value="lion"),
        app_commands.Choice(name="🐻 Bear", value="bear"),
        app_commands.Choice(name="🐸 Frog", value="frog"),
        app_commands.Choice(name="🐴 Horse", value="horse"),
        app_commands.Choice(name="🐰 Rabbit", value="rabbit"),
        app_commands.Choice(name="🐿️ Squirrel", value="squirrel"),
        app_commands.Choice(name="🐬 Dolphin", value="dolphin"),
        app_commands.Choice(name="🐾 Red Panda", value="red_panda"),
        app_commands.Choice(name="🦎 Axolotl", value="axolotl"),
        app_commands.Choice(name="🦆 Goose", value="goose"),
        app_commands.Choice(name="🦎 Lizard", value="lizard"),
        app_commands.Choice(name="🐰 Bunny", value="bunny"),
    ])
    @app_commands.checks.cooldown(1, 5.0)
    async def animal(self, interaction: discord.Interaction, animal: str, hidden: bool | None = None):
        hidden = await utils.resolve_hidden(interaction.user.id, hidden)
        await interaction.response.defer(ephemeral=hidden)

        animal_handlers = {
            "dog": ("https://random.dog/woof.json", "url", "🐶 Woof!"),
            "cat": ("https://cataas.com/cat?json=True", "url", "🐱 Meow!"),
            "duck": ("https://random-d.uk/api/v2/quack", "url", "🦆 Quack!"),
            "fox": ("https://randomfox.ca/floof/", "image", "🦊 Floof!"),
            "panda": ("https://api.animality.xyz/img/panda", "image", "🐼 Bamboo crunch!"),
            "koala": ("https://api.animality.xyz/img/koala", "image", "🐨 Eucalyptus nap!"),
            "kangaroo": ("https://api.animality.xyz/img/kangaroo", "image", "🦘 Boing!"),
            "whale": ("https://api.animality.xyz/img/whale", "image", "🐋 Sploosh!"),
            "bird": ("https://api.animality.xyz/img/bird", "image", "🐦 Tweet!"),
            "capybara": ("https://api.animality.xyz/img/capybara", "image", "🐹 Chill vibes!"),
            "hedgehog": ("https://api.animality.xyz/img/hedgehog", "image", "🦔 Prickly!"),
            "penguin": ("https://api.animality.xyz/img/penguin", "image", "🐧 Waddle!"),
            "turtle": ("https://api.animality.xyz/img/turtle", "image", "🐢 Slow and steady!"),
            "lion": ("https://api.animality.xyz/img/lion", "image", "🦁 Roar!"),
            "bear": ("https://api.animality.xyz/img/bear", "image", "🐻 Rawr!"),
            "frog": ("https://api.animality.xyz/img/frog", "image", "🐸 Ribbit!"),
            "horse": ("https://api.animality.xyz/img/horse", "image", "🐴 Neigh!"),
            "rabbit": ("https://api.animality.xyz/img/rabbit", "image", "🐰 Bunny hop!"),
            "squirrel": ("https://api.animality.xyz/img/squirrel", "image", "🐿️ Nut collector!"),
            "dolphin": ("https://api.animality.xyz/img/dolphin", "image", "🐬 Ocean acrobat!"),
            "red_panda": ("https://api.animality.xyz/img/redpanda", "image", "🐾 Bamboo bandit!"),
            "axolotl": ("https://api.animality.xyz/img/axolotl", "image", "🦎 Always smiling!"),
            "goose": ("https://nekos.life/api/v2/img/goose", "url", "🦆 Honk!"),
            "lizard": ("https://nekos.life/api/v2/img/lizard", "url", "🦎 Sunbather!"),
            "bunny": ("https://api.bunnies.io/v2/loop/random/?media=gif", "media", "🐰 Bun! 🥕"),
        }

        url, key, title = animal_handlers[animal]
        try:
            async with utils.http_session.get(url) as r:
                if r.status != 200:
                    await interaction.followup.send(f"> Could not fetch the {animal} picture. Please try again later.", ephemeral=True)
                    return
                data = await r.json()
            image_url = data[key]["gif"] if key == "media" else data[key]
        except (KeyError, IndexError, TypeError):
            await interaction.followup.send(f"> Could not fetch the {animal} picture. Please try again later.", ephemeral=True)
            return
        except Exception as e:
            logger.error("Failed to fetch %s picture: %s", animal, e)
            await interaction.followup.send(f"> Could not fetch the {animal} picture. Please try again later.", ephemeral=True)
            return

        embed = discord.Embed(title=title, color=discord.Color(0x7128fc), timestamp=discord.utils.utcnow())
        embed.set_image(url=image_url)
        embed.set_footer(text="Vote for 2x XP! /vote")
        await interaction.followup.send(embed=embed, ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="calc", description="Simple calculator")
    @app_commands.describe(expression="an expression like 5×2+3, 2^10 or sqrt(64)", hidden="Hide the command from others")
    async def calc(self, interaction: Interaction, expression: str, hidden: bool | None = None):
        hidden = await utils.resolve_hidden(interaction.user.id, hidden)
        normalized = (expression
                      .replace("×", "*").replace("✕", "*").replace("✖", "*")
                      .replace("·", "*").replace("•", "*")
                      .replace("÷", "/")
                      .replace("²", "**2").replace("³", "**3")
                      .replace("^", "**"))
        normalized = re.sub(r"(?<=[\d)])\s*[xX]\s*(?=[\d(])", "*", normalized)
        normalized = re.sub(r"√\(([^()]*)\)", r"sqrt(\1)", normalized)
        normalized = re.sub(r"√(\d+(?:\.\d+)?)", r"sqrt(\1)", normalized)

        if len(normalized) > 100:
            await interaction.response.send_message("> expression too long", ephemeral=hidden)
            return

        functions = {
            "sqrt": math.sqrt, "isqrt": math.isqrt, "cbrt": math.cbrt,
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
            "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
            "log": math.log, "log10": math.log10, "log2": math.log2,
            "exp": math.exp, "pow": math.pow, "hypot": math.hypot,
            "floor": math.floor, "ceil": math.ceil, "trunc": math.trunc,
            "degrees": math.degrees, "radians": math.radians,
            "gcd": math.gcd, "lcm": math.lcm,
            "abs": abs, "round": round, "min": min, "max": max,
            "int": int, "float": float, "str": str,
        }
        names = {
            "pi": math.pi, "e": math.e, "tau": math.tau,
            "inf": math.inf, "nan": math.nan,
            "True": True, "False": False, "None": None,
        }

        allowed = "0123456789+-*%/(). ,_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if any(c not in allowed for c in normalized):
            await interaction.response.send_message("> invalid expression", ephemeral=hidden)
            return
        if any(word in normalized.lstrip() for word in ("__", "lambda", "import", "exec", "eval", "open", "input", "globals", "locals", "getattr", "setattr", "delattr")):
            await interaction.response.send_message("> invalid expression", ephemeral=hidden)
            return
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(simple_eval, normalized, functions=functions, names=names),
                timeout=0.5,
            )
            out = f"{result:.10g}" if isinstance(result, float) else str(result)
            if len(out) > 40:
                await interaction.response.send_message("> result too large to display", ephemeral=True)
            else:
                await interaction.response.send_message(f"`{expression}` = {out}", ephemeral=hidden)
        except asyncio.TimeoutError:
            await interaction.response.send_message("> calculation too complex, try something simpler", ephemeral=True)
        except (OverflowError, MemoryError, ValueError):
            await interaction.response.send_message("> that number is too big to compute", ephemeral=True)
        except Exception as e:
            logger.error("Failed to evaluate %r: %s", expression, e)
            await interaction.response.send_message("> I couldn't work that one out. Try a simpler expression.", ephemeral=True)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="flip", description="Flip a coin.")
    @app_commands.describe(hidden="Hide the command from others")
    async def flip(self, interaction: Interaction, hidden: bool | None = None):
        hidden = await utils.resolve_hidden(interaction.user.id, hidden)
        await interaction.response.send_message(random.choice(["Heads!", "Tails!"]), ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="random", description="Random number generator")
    @app_commands.describe(a="Lowest number", b="Highest number", hidden="Hide the command from others")
    async def random_number(self, interaction: Interaction, a: int, b: int, hidden: bool | None = None):
        hidden = await utils.resolve_hidden(interaction.user.id, hidden)
        if a >= b:
            await interaction.response.send_message("> First number must be less than the second", ephemeral=True)
            return
        result = random.randint(a, b)
        await interaction.response.send_message(f"Result: {result}", ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="userinfo", description="Get info about a user")
    @app_commands.describe(
        user="The user you want info about",
        account="Show account details (ID, name, creation date, type, badges)",
        roles="Show the user's roles and top role (server members only)",
        server="Show server details (join date, nickname, avatar, boosting, flags)",
        permissions="Show the user's server permissions (server members only)",
        profile="Show profile details (accent color, banner, guild tag, nameplate)",
        hidden="Hide the command from others",
    )
    async def userinfo(
        self,
        interaction: discord.Interaction,
        user: discord.Member | discord.User,
        account: bool = True,
        roles: bool = True,
        server: bool = True,
        permissions: bool = True,
        profile: bool = True,
        hidden: bool | None = None,
    ):
        hidden = await utils.resolve_hidden(interaction.user.id, hidden)
        is_member = isinstance(user, discord.Member)

        embed = discord.Embed(
            title=user.name,
            color=discord.Color(0x7128fc),
            timestamp=discord.utils.utcnow()
        )

        if account:
            embed.add_field(name="ID", value=user.id)
            embed.add_field(name="Username", value=user.name)
            if user.global_name and user.global_name != user.name:
                embed.add_field(name="Display name", value=user.global_name)
            if user.discriminator != "0":
                embed.add_field(name="Discriminator", value=f"#{user.discriminator}")
            if user.created_at:
                created = f"{user.created_at.strftime('%Y-%m-%d')} ({discord.utils.format_dt(user.created_at, 'R')})"
            else:
                created = "Unknown"
            embed.add_field(name="Account created", value=created)
            kind = "Bot" if user.bot else "User"
            if user.system:
                kind += " (system)"
            embed.add_field(name="Type", value=kind)
            badges = [flag.name.replace("_", " ").title() for flag in user.public_flags.all()]
            if badges:
                embed.add_field(name="Badges", value=", ".join(badges))

        if is_member and roles:
            role_names = [role.name for role in user.roles if role.name != "@everyone"]
            value = ", ".join(role_names) or "None"
            if len(value) > 1024:
                value = value[:1021] + "..."
            embed.add_field(name=f"Roles ({len(role_names)})", value=value)
            if user.top_role.name != "@everyone":
                embed.add_field(name="Top role", value=user.top_role.mention)

        if is_member and server:
            if user.joined_at:
                joined = f"{user.joined_at.strftime('%Y-%m-%d')} ({discord.utils.format_dt(user.joined_at, 'R')})"
            else:
                joined = "Unknown"
            embed.add_field(name="Joined server", value=joined)
            if user.nick:
                embed.add_field(name="Nickname", value=user.nick)
            if user.premium_since:
                embed.add_field(name="Boosting since", value=user.premium_since.strftime("%Y-%m-%d"))
            else:
                embed.add_field(name="Boosting", value="No")
            if user.is_timed_out():
                embed.add_field(name="Timed out until", value=discord.utils.format_dt(user.timed_out_until, 'f'))
            if user.pending:
                embed.add_field(name="Membership", value="Pending screening")
            ignored_flags = {"dm_settings_upsell_acknowledged"}
            member_flags = [
                name.replace("_", " ").title()
                for name, enabled in user.flags
                if enabled and name not in ignored_flags
            ]
            if member_flags:
                embed.add_field(name="Member flags", value=", ".join(member_flags))

        if is_member and permissions:
            if user.guild_permissions.administrator:
                value = "Administrator (all permissions)"
            else:
                names = [name.replace("_", " ").title() for name, enabled in user.guild_permissions if enabled]
                value = ", ".join(names) or "None"
                if len(value) > 1024:
                    value = value[:1021] + "..."
            embed.add_field(name="Permissions", value=value)

        if profile:
            try:
                fetched = await interaction.client.fetch_user(user.id)
            except discord.HTTPException:
                fetched = None
            source = fetched or user
            accent = source.accent_color or user.accent_color
            banner = getattr(user, "guild_banner", None) or source.banner or user.banner
            tag = source.primary_guild or user.primary_guild
            decoration = source.avatar_decoration or user.avatar_decoration
            collectibles = source.collectibles or user.collectibles
            if accent:
                embed.add_field(name="Accent color", value=f"#{accent.value:06X}")
            if tag:
                embed.add_field(name="Guild tag", value=tag.tag)
            if decoration:
                embed.add_field(name="Avatar decoration", value=f"[View]({decoration.url})")
            for collectible in collectibles:
                if collectible.type is discord.CollectibleType.nameplate:
                    label = collectible.label or ""
                    if label.startswith("COLLECTIBLES_"):
                        label = label.removeprefix("COLLECTIBLES_").removesuffix("_A11Y")
                        tokens = [t for t in label.split("_") if t not in {"NAMEPLATES", "NAMEPLATE", "V1", "V2"}]
                        label = " ".join(tokens).title()
                    embed.add_field(name="Nameplate", value=label or "Yes")
                    break
            if banner:
                embed.set_image(url=banner.url)

        if is_member and user.guild_avatar:
            embed.set_thumbnail(url=user.guild_avatar.url)
        else:
            embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"Requested by {interaction.user.name} • Vote for 2x XP! /vote")

        await interaction.response.send_message(embed=embed, ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="quote", description="Get a quote")
    @app_commands.describe(choice='"Today" or "Random"', hidden="Hide the command from others")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Today", value="Today"),
        app_commands.Choice(name="Random", value="Random")
    ])
    @app_commands.checks.cooldown(1, 5.0)
    async def quote(self, interaction: discord.Interaction, choice: str, hidden: bool | None = None):
        hidden = await utils.resolve_hidden(interaction.user.id, hidden)
        await interaction.response.defer(ephemeral=hidden)
        if choice.lower() != "today" and choice.lower() != "random":
            await interaction.followup.send(f"Invalid input: {choice}", ephemeral=True)
            return
        try:
            async with utils.http_session.get(f"https://zenquotes.io/api/{choice.lower()}") as r:
                logger.info("Quote API response status: %s", r.status)
                data = await r.json()
            quote_text = data[0]['q']
            author = data[0]['a']
        except (KeyError, IndexError, TypeError):
            logger.error("Quote API returned unexpected data")
            await interaction.followup.send("Could not fetch quote. Please try again later.", ephemeral=True)
            return
        except Exception as e:
            logger.error("Failed to fetch quote: %s", e)
            await interaction.followup.send("Could not fetch quote. Please try again later.", ephemeral=True)
            return
        await interaction.followup.send(f"\"{quote_text}\" - {author}", ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="fact", description="Get a daily fact.")
    @app_commands.describe(hidden="Hide the command from others", choice='"Today" or "Random"')
    @app_commands.choices(choice=[
        app_commands.Choice(name="Today", value="Today"),
        app_commands.Choice(name="Random", value="Random")
    ])
    @app_commands.checks.cooldown(1, 5.0)
    async def get_fact(self, interaction: discord.Interaction, choice: str, hidden: bool | None = None):
        hidden = await utils.resolve_hidden(interaction.user.id, hidden)
        await interaction.response.defer(ephemeral=hidden)
        if choice.lower() != "today" and choice.lower() != "random":
            await interaction.followup.send(f"Invalid input: {choice}", ephemeral=True)
            return
        try:
            async with utils.http_session.get(
                f"https://uselessfacts.jsph.pl/api/v2/facts/{'today' if choice.lower() == 'today' else 'random'}?language=en",
                headers={"Accept": "application/json"},
            ) as r:
                logger.info("Fact API response status: %s", r.status)
                r.raise_for_status()
                data = await r.json()
            fact = data.get("text")
            if not fact:
                raise ValueError("API returned no fact text")
        except Exception as e:
            logger.error("Failed to fetch fact: %s", e)
            await interaction.followup.send("Could not fetch fact. Please try again later.", ephemeral=True)
            return
        await interaction.followup.send(fact, ephemeral=hidden)


async def setup(bot):
    await bot.add_cog(FunCog(bot))
