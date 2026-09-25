# AGENTS.md

VoidWave: Discord bot (discord.py 2.x, `cogs/`) + Flask web dashboard (`app.py`, `templates/`, `static/`) that share a single SQLite DB as separate processes. Ruff config lives in `pyproject.toml` (rules `E4`,`E7`,`E9`,`F`,`I`); Python 3.11+ is targeted (local `.venv/` is 3.14, production `venv/` is 3.13; docs reference `venv/` on prod hosts). Tests are a small network-free pytest suite in `tests/`, run in CI (`.github/workflows/tests.yml`); verify other changes by running the scripts.

## Run commands

```bash
.venv/bin/python bot.py             # bot (applies/create_schema patch DB schema, then bot.run)
.venv/bin/python app.py             # web dashboard, 127.0.0.1:8002 (admin blueprint included)
.venv/bin/python generate_graphs.py # rebuild Graphs/*.png + README banner from stats_history.json
.venv/bin/python -m pytest -q       # run tests (needs ./.venv/bin/pip install -r requirements-dev.txt; no Ollama/Lavalink/token needed)
.venv/bin/python -m ruff check .    # lint, also enforced in CI
```

- The local venv is `.venv/`; this repo's copy of it is gitignored. Production hosts use `venv/` (see `DEPLOYMENT.md`).
- Copy `.env.example` → `.env`. `ADMIN_PASSWORD` is required or /admin returns 503.
- AI chat needs Ollama at `localhost:11434`; `PROMPT_NAME` selects `prompts/<name>.txt`. The model is `MODEL` (default `llama3.2:3b`), so don't hardcode a model name in user-facing text.
- `/kirkify` (face swap) shells out via `sys.executable` to the **gitignored** clone at `third_party/kirkify.py/kirkify.py` (see `cogs/ai.py`; serialized through a FIFO `kirkify_queue` of maxsize 5, drained by `AICog._kirkify_worker`). Its extra pip deps (`insightface`, `onnxruntime`, `opencv-python`) must live in the same venv the bot runs in, and its `inswapper_128.onnx` model must be downloaded + `kirkify.py init` run once (setup in `DEPLOYMENT.md`). Don't import it directly; it only works as a subprocess against a local file tree. Uploads are re-encoded to PNG via cv2 before the subprocess so unsupported formats (e.g. AVIF/HEIC) fail with a clean message instead of a cryptic subprocess error.
- Music cog needs a Lavalink 4.x server (`LAVALINK_URI`/`LAVALINK_PASSWORD`); wavelink pinned `>=3.5,<4`. Native Spotify/SoundCloud come from the **LavaSrc** plugin on the Lavalink side (setup in `DEPLOYMENT.md`).
- Slash commands are synced globally from `cogs/events.py` `on_ready` (`tree.sync()`). `GUILD_ID`/`APPLICATION_ID` are currently **unused**; `ALLOWED_USER_ID` is only used to ping on critical alerts (`notify.py`).
- `bot.py` runs with `chunk_guilds_at_startup=False` (chunking on many guilds trips Discord's gateway rate limit), so the member cache is empty at startup; use `guild.fetch_member()` for authoritative membership, don't assume cache.
- `bot.py` exits non-zero via a startup timeout (60s to `on_ready`) and a connection watchdog (~90s closed gateway) so systemd `Restart=always` retries instead of hanging. A local run needs a real token + Discord reachability; without them the process quits with code 1 rather than idling.

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
- The `/help` menu is data-driven: `DOCUMENTED_COMMANDS`/`DOCUMENTED_ALIASES` in `cogs/general.py` drive the help topics and autocomplete, and `_check_help_docs` runs on startup warning about any registered command missing from it (or any documented one that no longer exists). The website `/docs` pages (`templates/docs_*.html`, mapped in `app.py::_DOCS_PAGES`) are a hand-maintained mirror of that same user-facing content; keep all three in sync.
- Embed footers: the `_footer()` helper (cogs/music.py:48) sets the "Vote for 2x XP" footer, but `now_playing_embed()`, `QueueView.build_embed()`, and `PlaylistView.build_embed()` set their own footers; calling `_footer()` on top of those silently overwrites them (the live offender is `playlist_list`, which stacks `_footer()` on a `PlaylistView.build_embed()`). Don't stack `set_footer` calls.
- Music tracks carry who added them in `track.extras.requester_name` (set via `_tag_requester`, default `Autoplay`); the skip-instant owner is the user who started playback (`MusicCog.players_owner`).
- Music search: `/music play` defaults to searching **all** sources in the order Spotify → SoundCloud → YouTube (`_search_text`); the `source` option (`all`/`youtube`/`soundcloud`/`spotify`) or the `spsearch:`/`ytsearch:`/`scsearch:` prefixes pin one source. `_track_source` resolves a track's source from `extras.requested_source`, falling back to `track.source`.
- There is a test for the pure music helpers in `tests/test_music.py`; keep it network free (no wavelink/Lavalink) by only exercising module-level helpers.

## Adding a command

Add a new cog file to `cogs/` and load it in `bot.py::setup_hook` (the list is explicit, not auto-discovered). Cogs are mostly slash-command `@app_commands` groups; interaction handlers and background loops (e.g. QOTD, giveaways) are started from `cogs/events.py::on_ready`. Register every new slash command (subcommands too, as `group name`) in `DOCUMENTED_COMMANDS` in `cogs/general.py` so `/help` and its autocomplete list it.