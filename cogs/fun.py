from discord import app_commands, Interaction
from discord.ext import commands
from simpleeval import simple_eval
import discord
import random
from utils import http_session, date


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
    ])
    async def animal(self, interaction: discord.Interaction, animal: str, hidden: bool = False):
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
        }

        url, key, title = animal_handlers[animal]
        try:
            async with http_session.get(url) as r:
                if r.status != 200:
                    await interaction.followup.send(f"> Could not fetch {animal} picture. Please try again later.", ephemeral=hidden)
                    return
                data = await r.json()
        except Exception as e:
            await interaction.followup.send(f"> Could not fetch {animal} picture. Please try again later.\n> {e}", ephemeral=hidden)
            return

        image_url = data[key]
        embed = discord.Embed(title=title, color=discord.Color.orange())
        embed.set_image(url=image_url)
        embed.set_footer(text="Vote for the bot! /vote")
        await interaction.followup.send(embed=embed, ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="calc", description="Simple calculator")
    @app_commands.describe(expression="an expression like 5*2+3", hidden="Hide the command from others")
    async def calc(self, interaction: Interaction, expression: str, hidden: bool = False):
        allowed = "0123456789+-*/(). "
        if any(c not in allowed for c in expression):
            await interaction.response.send_message("> invalid expression", ephemeral=hidden)
            return
        try:
            result = simple_eval(expression)
            await interaction.response.send_message(f"`{expression}` = {result}", ephemeral=hidden)
        except Exception as e:
            await interaction.response.send_message(f"Error evaluating expression: {e}", ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="flip", description="Flip a coin.")
    @app_commands.describe(hidden="Hide the command from others")
    async def flip(self, interaction: Interaction, hidden: bool = False):
        await interaction.response.send_message(random.choice(["Heads!", "Tails!"]), ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="random", description="Random number generator")
    @app_commands.describe(a="Lowest number", b="Highest number", hidden="Hide the command from others")
    async def random_number(self, interaction: Interaction, a: int, b: int, hidden: bool = False):
        if a >= b:
            await interaction.response.send_message("> First number must be less than the second", ephemeral=True)
            return
        result = random.randint(a, b)
        await interaction.response.send_message(f"Result: {result}", ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="userinfo", description="Get info about a user")
    @app_commands.describe(user="The user you want info about", hidden="Hide the command from others")
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member | discord.User, hidden: bool = False):
        roles = []
        joined_server = "Unknown"

        if isinstance(user, discord.Member):
            roles = [role.name for role in user.roles if role.name != "@everyone"]
            joined_server = user.joined_at.strftime("%Y-%m-%d") if user.joined_at else "Unknown"

        embed = discord.Embed(
            title=user.name,
            color=discord.Color.blue()
        )

        embed.add_field(name="ID", value=user.id)
        embed.add_field(
            name="Account created",
            value=user.created_at.strftime("%Y-%m-%d") if user.created_at else "Unknown"
        )

        if isinstance(user, discord.Member):
            embed.add_field(name="Joined server", value=joined_server)
            embed.add_field(name="Roles", value=", ".join(roles) or "None")

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"Requested by {interaction.user.name} • Vote for the bot! /vote")

        await interaction.response.send_message(embed=embed, ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="quote", description="Get a quote")
    @app_commands.describe(choice='"Today" or "Random"', hidden="Hide the command from others")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Today", value="Today"),
        app_commands.Choice(name="Random", value="Random")
    ])
    async def quote(self, interaction: discord.Interaction, choice: str, hidden: bool = False):
        await interaction.response.defer(ephemeral=hidden)
        if choice.lower() != "today" and choice.lower() != "random":
            await interaction.followup.send(f"Invalid input: {choice}", ephemeral=True)
            return
        try:
            async with http_session.get(f"https://zenquotes.io/api/{choice.lower()}") as r:
                print(f"{date()} INFO  Quote API response status: {r.status}")
                data = await r.json()
        except Exception as e:
            await interaction.followup.send(f"Could not fetch quote. Please try again later.\nDetails: {e}", ephemeral=True)
            return
        await interaction.followup.send(f"\"{data[0]['q']}\" - {data[0]['a']}", ephemeral=hidden)

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name="fact", description="Get a daily fact.")
    @app_commands.describe(hidden="Hide the command from others", choice='"Today" or "Random"')
    @app_commands.choices(choice=[
        app_commands.Choice(name="Today", value="Today"),
        app_commands.Choice(name="Random", value="Random")
    ])
    async def get_fact(self, interaction: discord.Interaction, choice: str, hidden: bool = False):
        await interaction.response.defer(ephemeral=hidden)
        if choice.lower() != "today" and choice.lower() != "random":
            await interaction.followup.send(f"Invalid input: {choice}", ephemeral=True)
            return
        try:
            async with http_session.get(f"https://uselessfacts.jsph.pl/{'today' if choice.lower() == 'today' else 'random'}.json?language=en") as r:
                print(f"{date()} INFO  Fact API response status: {r.status}")
                data = await r.json()
        except Exception as e:
            await interaction.followup.send(f"Could not fetch fact. Please try again later.\nDetails: {e}", ephemeral=True)
            return
        await interaction.followup.send(f"{data['text']}", ephemeral=hidden)


async def setup(bot):
    await bot.add_cog(FunCog(bot))
