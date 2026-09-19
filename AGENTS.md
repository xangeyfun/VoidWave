# AGENTS.md

VoidWave: Discord bot (discord.py 2.x, `cogs/`) + Flask web dashboard (`app.py`, `templates/`, `static/`) that share a single SQLite DB as separate processes. No lint config, no pyproject; Python 3.11+ (local `venv/` is 3.13). Tests are a small network-free pytest suite in `tests/`, run in CI (`.github/workflows/tests.yml`); verify other changes by running the scripts.

## Run commands

```bash
venv/bin/python bot.py             # bot (applies/create_schema patch DB schema, then bot.run)
venv/bin/python app.py             # web dashboard, 127.0.0.1:8002 (admin blueprint included)
venv/bin/python generate_graphs.py # rebuild Graphs/*.png + README banner from stats_history.json
venv/bin/python -m pytest -q       # run tests (needs ./venv/bin/pip install -r requirements-dev.txt; no Ollama/Lavalink/token needed)
```

- Copy `.env.example` → `.env`. `ADMIN_PASSWORD` is required or /admin returns 503.
- AI chat needs Ollama at `localhost:11434`; `PROMPT_NAME` selects `prompts/<name>.txt`.
- Music cog needs a Lavalink 4.x server (`LAVALINK_URI`/`LAVALINK_PASSWORD`); wavelink pinned `>=3.5,<4`.
- Slash commands are synced globally in `cogs/events.py:96` (`tree.sync()`). `GUILD_ID`/`APPLICATION_ID` are currently **unused**; `ALLOWED_USER_ID` is only used to ping on critical alerts (`notify.py`).

## Architecture & gotchas

- DB schema is maintained in **three places**; add/alter columns in all that apply:
  1. `schema.py::create_schema(conn)`: main tables, called from `bot.py` `__main__` (and reused by tests); uses `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN` wrapped in `try/except sqlite3.OperationalError`.
  2. `admin/helpers.py::_ensure_admin_tables()`: admin tables (`admin_events`, `admin_login_codes`, `admin_rate_limits`), runs on every /admin request.
  3. `app.py`: top.gg webhook route creates vote tables inline.
- SQLite WAL: connect via `utils.get_db()` / `app.get_db()` (`PRAGMA journal_mode=WAL`, `busy_timeout=5000`). Never open the DB without these PRAGMAs. `database.db*`, `stats_history.json`, `Graphs/`, log files are gitignored runtime artifacts.
- Blocking IO (DB writes, `ask_llm`) must be wrapped in `asyncio.to_thread` (see `utils._do_message_xp`). LLM replies funnel through one worker (`llm_worker`, queue `maxsize=10`); don't call Ollama directly from an event loop handler.
- Leveling cooldowns live in `utils.py`: XP 30s, VC 10min, LLM 15s.
- Logging uses custom levels in `logconf.py` (`logger.command/message/guild/blocked/webhook`). Every `ERROR+` is auto-posted to a Discord webhook (`notify.DiscordAlertHandler`, rate-limited + deduped); keep error paths quiet to avoid alert spam.
- Blocked users are gated globally by `bot.tree.interaction_check` (`bot.py::_command_gate`); new commands don't need their own block checks. Ephemeral user-facing errors only; central handler is `bot.py::on_app_command_error`.
- `prompts/` is gitignored except `prompts/default.txt`; new persona files won't be committed by default.
- QOTD runs on a 1-minute loop (`cogs/events.py`); per-guild time is `HH:MM` + IANA tz stored in `guild_settings` (`qotd_time`, `qotd_tz`).
- The admin panel controls the bot through systemd unit `voidwave.service` (`admin/helpers.py` `_service_*`); start/stop/restart workflow assumes a production host with systemctl. See `DEPLOYMENT.md` for full production setup (units `voidwave.service` + `voidwave_website.service`, reverse proxy, graphs cron).
- Working tree currently has uncommitted changes in `cogs/music.py`; check `git status` before editing.

## Adding a command

Add a new cog file to `cogs/` and load it in `bot.py::setup_hook` (the list is explicit, not auto-discovered). Cogs are mostly slash-command `@app_commands` groups; interaction handlers and background loops (e.g. QOTD, giveaways) are started from `cogs/events.py::on_ready`.