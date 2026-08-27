<div align="center">

# VoidWave

**Leveling, AI chat, Question of the Day, and moderation. No data collection, no paywalls, just works.**

![VoidWave Stats](https://voidwave.xangey.dev/static/images/stats.png)

![Python](https://img.shields.io/badge/python-3.11+-blue)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2)
![Flask](https://img.shields.io/badge/flask-web-black)
![SQLite](https://img.shields.io/badge/database-sqlite-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

![GitHub stars](https://img.shields.io/github/stars/xangeyfun/VoidWave?style=social)
![GitHub last commit](https://img.shields.io/github/last-commit/xangeyfun/VoidWave)
![GitHub issues](https://img.shields.io/github/issues/xangeyfun/VoidWave)
![Code size](https://img.shields.io/github/languages/code-size/xangeyfun/VoidWave)

[![Invite](https://img.shields.io/badge/Invite-VoidWave-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/api/oauth2/authorize?client_id=1442229230384709752&scope=bot%20applications.commands)
[![Top.gg](https://img.shields.io/badge/Top.gg-VoidWave-FF7A00?style=for-the-badge&logo=topdotgg&logoColor=white)](https://top.gg/bot/1442229230384709752)

</div>

## Features

* XP & leveling from messages and voice chat, works instantly
* Cross-server global profiles and leaderboards
* AI chat powered by Llama 3.2, free and unlimited
* Shareable web profiles with OpenGraph embeds
* Auto role rewards at level milestones
* Daily Question of the Day with auto-threads
* Moderation commands (kick, ban, timeout, slowmode, lock, role management)
* Vote for 2x XP boosts, 3 hours on weekends
* Fun commands (animal pics, quotes, facts, calculator)
* Games (8-ball, rock-paper-scissors, tic-tac-toe, connect four, hangman, blackjack, trivia, wordle, minesweeper, battleship, 15-puzzle)
* All slash commands, no prefix needed

## Tech Stack

| Part     | Tech                |
| -------- | ------------------- |
| Bot      | Python + discord.py |
| Website  | Flask               |
| Database | SQLite              |
| Frontend | Jinja + vanilla CSS |
| AI       | Ollama + Llama 3.2  |

The bot and website share the same SQLite database but run as separate processes.

---

## Why?

started this to learn python and discord bots,
but got tired of leveling bots being bloated, ugly, or locked behind paywalls.

so i built one that's clean, private, and actually free.

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

## Contributing

contributions are welcome. open an issue or submit a pull request on github.

---

## Links

<div align="center">

[![Invite](https://img.shields.io/badge/Invite-VoidWave-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/api/oauth2/authorize?client_id=1442229230384709752&scope=bot%20applications.commands)
[![Support Server](https://img.shields.io/badge/Support_Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/tyQksBReAS)
[![Top.gg](https://img.shields.io/badge/Top.gg-VoidWave-FF7A00?style=for-the-badge&logo=topdotgg&logoColor=white)](https://top.gg/bot/1442229230384709752)
[![Website](https://img.shields.io/badge/Website-voidwave.xangey.dev-blue?style=for-the-badge&logo=googlechrome&logoColor=white)](https://voidwave.xangey.dev/)
[![GitHub](https://img.shields.io/badge/GitHub-xangeyfun-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/xangeyfun/VoidWave)

</div>
