# Contributing to VoidWave

Thanks for wanting to help! VoidWave is a small project, so keep changes focused
and match the surrounding code style. Before opening a PR, read `AGENTS.md`.
It documents the architecture and gotchas that bite new contributors (schema in
three places, WAL-mode SQLite, the LLM worker, the error webhook, etc).

## Getting started

```bash
git clone https://github.com/xangeyfun/VoidWave
cd VoidWave
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in TOKEN and ADMIN_PASSWORD at minimum
```

- Requires Python 3.11+.
- AI chat needs Ollama running on `localhost:11434` with the `MODEL` pulled.
- Music needs a Lavalink 4.x server; leave `LAVALINK_URI`/`LAVALINK_PASSWORD`
  empty if you're not testing music.

## Running your changes

Tests live in `tests/` (pytest). CI runs them on push/PR, but run them locally
first (`./venv/bin/pip install -r requirements-dev.txt` once):

```bash
./venv/bin/python -m pytest -q
```

The suite is network-free: no Ollama, Lavalink, or Discord token needed, and
tests build their own throwaway DB in a temp dir, so `database.db` is untouched.

For manual checks beyond the suite:

Check that:

- `./venv/bin/python -m pytest -q` passes.
- The bot connects and slash commands sync (they sync globally on startup).
- The dashboard renders the pages you touched.
- DB schema changes work against an **existing** `database.db` (create the table
  with `CREATE TABLE IF NOT EXISTS` and add new columns with
  `ALTER TABLE ... ADD COLUMN` wrapped in `try/except sqlite3.OperationalError`,
  in every place described in `AGENTS.md`).

## Conventions

- Match the style of the file you're editing; keep commands as `@app_commands`
  in a cog.
- New cogs must be added to the explicit list in `bot.py::setup_hook`.
- Background loops/tasks are started from `cogs/events.py::on_ready`, not inline.
- Blocking IO goes through `asyncio.to_thread`; never call Ollama directly from
  an event-loop handler (use the `llm_worker` queue in `utils.py`).
- Don't add new `ERROR`/`CRITICAL` log paths lightly; every error is pushed to
  a Discord webhook (rate-limited, but still noisy).
- `prompts/` is gitignored except `prompts/default.txt`; new persona files won't
  be committed by default. Tell us in the PR if you intend to add one.

## Pull requests

- Create a branch off `main`, one logical change per PR.
- Don't commit secrets, `.env`, `database.db*`, log files, or `stats_history.json`
  (all gitignored already).
- In the PR description, note what you ran to verify and whether new `.env` vars
  were needed (also update `.env.example` if so).

## License

By contributing you agree that your changes are licensed under the
[MIT License](LICENSE).