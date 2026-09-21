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
![Tests](https://img.shields.io/github/actions/workflow/status/xangeyfun/VoidWave/tests.yml?branch=main)
![GitHub issues](https://img.shields.io/github/issues/xangeyfun/VoidWave)
![Code size](https://img.shields.io/github/languages/code-size/xangeyfun/VoidWave)

[![Invite](https://img.shields.io/badge/Invite-VoidWave-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/api/oauth2/authorize?client_id=1442229230384709752&scope=bot%20applications.commands)
[![Top.gg](https://img.shields.io/badge/Top.gg-VoidWave-FF7A00?style=for-the-badge&logo=topdotgg&logoColor=white)](https://top.gg/bot/1442229230384709752)

</div>

## Features

* XP & leveling from messages and voice chat, works instantly
* Cross-server global profiles and leaderboards
* AI chat powered by a self hosted LLM (Ollama), free and unlimited
* Kirkify any image with a self hosted AI face swap (`/kirkify`), same privacy guarantee
* Shareable web profiles with OpenGraph embeds
* Auto role rewards at level milestones
* Daily Question of the Day with auto-threads
* Moderation commands (kick, ban, timeout, slowmode, lock, role management)
* Vote for 2x XP boosts, 4 hours on weekdays and 6 on weekends
* DM or channel reminders with human-friendly times (`10m`, `tomorrow 16:00`, `friday 18:30`) and recurring options (`daily`, `weekly`, `every 2h`)
* Fun commands (animal pics, quotes, facts, calculator)
* Games (8-ball, rock-paper-scissors, tic-tac-toe, connect four, hangman, blackjack, trivia, wordle, minesweeper, battleship, 15-puzzle)
* Music playback (YouTube, Spotify, SoundCloud, playlists) via Lavalink, with source + requester shown on each track
* All slash commands, no prefix needed

## Tech Stack

| Part     | Tech                |
| -------- | ------------------- |
| Bot      | Python + discord.py |
| Website  | Flask               |
| Database | SQLite              |
| Frontend | Jinja + vanilla CSS |
| AI       | Ollama (self hosted LLM) |
| Music    | Lavalink + wavelink |

The bot and website share the same SQLite database but run as separate processes.

---

## Why?

started this to learn python and discord bots,
but got tired of leveling bots being bloated, ugly, or locked behind paywalls.

so i built one that's clean, private, and actually free.

---

## Self-hosting

you need python 3.11+, ollama with a model pulled, and a discord bot token.

running this in production (systemd units, reverse proxy, graphs cron, backups)?
see [DEPLOYMENT.md](DEPLOYMENT.md).

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

### Music (Lavalink)

Music playback needs a **Lavalink 4.x** server running. Set up your own any way you
like (systemd service, Docker, a script), then point the bot at it in `.env`:

```env
LAVALINK_URI=http://localhost:2333
LAVALINK_PASSWORD=youshallnotpass
```

- The `LAVALINK_PASSWORD` here must match the password in your Lavalink config.
- wavelink (the Python client) requires **Lavalink 4**, not 3.
- Example systemd unit: download the `Lavalink.jar` release, place an
  `application.yml` next to it, and run
  `ExecStart=/usr/bin/java -jar /path/to/Lavalink.jar` with `Restart=on-failure`.
- Java 17+ is required.

### Music idle behavior

When the queue finishes, VoidWave waits **3 minutes** before leaving the voice
channel. If the voice channel becomes empty while music is still playing,
playback **pauses** and resumes automatically when someone joins; if nobody
joins within 3 minutes, VoidWave leaves.

---

## Contributing

contributions are welcome. open an issue or submit a pull request on github.

please read [CONTRIBUTING.md](CONTRIBUTING.md) first. this project is governed by
a [Code of Conduct](CODE_OF_CONDUCT.md); please report security issues privately
per [SECURITY.md](SECURITY.md).

---

## Links

<div align="center">

[![Invite](https://img.shields.io/badge/Invite-VoidWave-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/api/oauth2/authorize?client_id=1442229230384709752&scope=bot%20applications.commands)
[![Support Server](https://img.shields.io/badge/Support_Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/tyQksBReAS)
[![Top.gg](https://img.shields.io/badge/Top.gg-VoidWave-FF7A00?style=for-the-badge&logo=topdotgg&logoColor=white)](https://top.gg/bot/1442229230384709752)
[![Website](https://img.shields.io/badge/Website-voidwave.xangey.dev-blue?style=for-the-badge&logo=googlechrome&logoColor=white)](https://voidwave.xangey.dev/)
[![GitHub](https://img.shields.io/badge/GitHub-xangeyfun-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/xangeyfun/VoidWave)

</div>
