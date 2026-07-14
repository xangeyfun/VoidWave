<div align="center">

# VoidWave

**AI chat, leveling, QOTD - all in one bot.**

![Python](https://img.shields.io/badge/python-3.11+-blue)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2)
![Flask](https://img.shields.io/badge/flask-web-black)
![SQLite](https://img.shields.io/badge/database-sqlite-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

[![Invite](https://img.shields.io/badge/Invite-VoidWave-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/api/oauth2/authorize?client_id=1442229230384709752&scope=bot%20applications.commands)
[![Top.gg](https://img.shields.io/badge/Top.gg-VoidWave-FF7A00?style=for-the-badge&logo=topdotgg&logoColor=white)](https://top.gg/bot/1442229230384709752)

</div>

## Features

* XP & leveling system
* Global + server leaderboards
* AI chat powered by Llama 3.2
* Fast slash commands
* Shareable web profiles
* Auto role rewards
* Random utilities & fun commands
* Daily Question of the Day with threaded discussions
* Lightweight SQLite setup

## Tech Stack

| Part     | Tech                |
| -------- | ------------------- |
| Bot      | Python + discord.py |
| Website  | Flask               |
| Database | SQLite              |
| Frontend | Jinja + vanilla CSS |
| AI       | Ollama + Llama 3.2  |

bot and website share the same database but run separately.

---

## Why?

originally made this to learn python + discord bots,
but got tired of most leveling bots feeling bloated or ugly.

so i made my own.

---

## Self-hosting

you need python 3.11+, ollama with a model pulled, and a discord bot token.

```bash
git clone https://github.com/xangeyfun/VoidWave
cd VoidWave
pip install -r requirements.txt
```

copy `.env.example` to `.env` and fill in your stuff:

```env
TOKEN=your_bot_token
APPLICATION_ID=your_app_id
GUILD_ID=your_guild_id
ALLOWED_USER_ID=your_discord_id
SECRET_KEY=something_random
MODEL=llama3.2:3b
```

then just run both:

```bash
python3 bot.py     # the bot
python3 app.py     # web dashboard (optional)
```

---

## Links

* [Invite VoidWave](https://discord.com/api/oauth2/authorize?client_id=1442229230384709752)
* [Discord Server](https://discord.gg/tyQksBReAS)
* [Top.gg](https://top.gg/bot/1442229230384709752)
* [Website](https://voidwave.xangey.dev/)
* [GitHub](https://github.com/xangeyfun/VoidWave)
