# Voidwave

A Discord leveling bot with a sleek web interface. Made to learn, built to use.

## What's this?

Voidwave is a Discord bot that tracks user activity and XP. Simple, fast, and does one thing well. It started as a learning project but turned into something I actually use in my servers.

## Features

- **XP & Leveling** - Users earn XP by chatting, level up over time
- **Leaderboards** - Server and global rankings
- **Slash Commands** - Modern Discord UX
- **Web Stats** - Share your profile link: `voidwave.xangey.dev/stats/guild_id/user_id`
- **Role Rewards** - Auto-role at certain levels (configurable)
- **Fun Commands** - Calculator, quotes, memes, random stuff

## Setup

1. Clone:
```bash
git clone https://github.com/xangeyfun/discord-bot.git
cd discord-bot
```

2. Install:
```bash
pip install -r requirements.txt
```

3. Create `.env`:
```
TOKEN=your_bot_token
APPLICATION_ID=your_bot_user_id
GUILD_ID=your_server_id
ALLOWED_USER_ID=your_user_id
SECRET_KEY=random_string
```

4. Run the bot:
```bash
python3 bot.py
```

5. Run the web server (separate process):
```bash
python3 app.py
```

The bot and web server run independently. The web server reads from the same database.

## Commands

Type `/help` when the bot's online to see all commands. Here's the basics:

- `/ping` - Check latency
- `/level` - Your stats
- `/leaderboard` - Top users
- `/calc` - Math calculator
- `/flip` - Coin flip
- `/quote` - Get a quote
- `/meme` - Random meme

## Tech

- Python + discord.py (bot)
- Flask (web)
- SQLite (database)
- Vanilla CSS + Jinja templates

## License

MIT - do whatever, just don't be a jerk.

## Contact

- Discord: [xangey's server](https://discord.gg/tyQksBReAS)
- GitHub: [xangeyfun/discord-bot](https://github.com/xangeyfun/discord-bot)

Made by xangey (: