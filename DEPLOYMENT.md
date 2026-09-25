# Deploying VoidWave in production

This is a reference for running VoidWave in production, wired together the same
way as the live instance. It is a reference, not a requirement: the
code only hard-depends on **systemd** because the admin panel / health page talk
to the `systemctl` binary (unit names `voidwave.service` /
`voidwave_website.service` are checked directly by `admin/constants.py`,
`admin/health.py`, `admin/helpers.py`).

> The values below are a **portable example** (host nicknamed `production-host`,
> user `your-user`, repo cloned to `~/VoidWave`, venv `venv/` with Python 3.11+,
> website served by gunicorn). Adjust paths, users and the domain to your own
> box.

## What runs where

Three things keep the service alive, all sharing the same `database.db` in the
repo root:

| Piece | Command (example values) | Managed by |
| ----- | ------- | ---------- |
| Discord bot | `~/VoidWave/venv/bin/python3 -u bot.py` | `voidwave.service` |
| Web dashboard + admin | `gunicorn -w 4 -b 127.0.0.1:8002 app:app --access-logfile - --error-logfile -` | `voidwave_website.service` |
| Stats graphs | `./venv/bin/python generate_graphs.py` | cron |

`app.py` only runs as a WSGI target under gunicorn in production; running
`python app.py` gives you the same dashboard on `127.0.0.1:8002` for local
development.

## Prerequisites

- Python 3.11+ and a `venv/` with `requirements.txt` installed.
- `.env` in the **repo root**. Scripts use `load_dotenv()` and relative paths
  (`database.db`, `questions.json`, `prompts/`, `templates/`, `stats_history.json`),
  so every service must run with the repo root as its working directory.
- Full AI chat: Ollama on `localhost:11434` with the `MODEL` pulled.
- Kirkify (`/kirkify`): the face-swap tool lives in `third_party/kirkify.py`
  (gitignored) with its `inswapper_128.onnx` model and the extra pip deps from
  `requirements.txt` (`opencv-python`, `insightface`, `onnxruntime`). Clone the
  repo there and run its `python3 kirkify.py init` once to pre-warm the model
  (see [Kirkify](#kirkify) below).
- Music: a Lavalink 4.x server reachable at `LAVALINK_URI` / `LAVALINK_PASSWORD`
  running the **LavaSrc plugin** (4.8.x) for native Spotify, plus a
  **Spotify Tokener** service for anonymous tokens (see below).

## Music: Lavalink + LavaSrc + Spotify Tokener

Spotify playback lives entirely on the Lavalink side (`cogs/music.py` hands
Spotify URLs/queries straight to Lavalink; no scraping).

1. Install the LavaSrc plugin under `lavalink.plugins`:
   ```yaml
   lavalink:
     plugins:
       - dependency: "com.github.topi314.lavasrc:lavasrc-plugin:4.8.3"
         snapshot: false
         repository: "https://maven.lavalink.dev/releases"
   ```
2. Register a Spotify API app at <https://developer.spotify.com/dashboard>, then
   enable LavaSrc with your credentials. Only Spotify is enabled here:
   ```yaml
   plugins:
     lavasrc:
       sources:
         spotify: true
         applemusic: false
         deezer: false
         yandexmusic: false
         flowerytts: false
         youtube: false
         vkmusic: false
       spotify:
         clientId: "SPOTIFY_CLIENT_ID"
         clientSecret: "SPOTIFY_CLIENT_SECRET"
         customTokenEndpoint: "http://127.0.0.1:8080/api/token"
         preferPartnerApi: true
   ```
   Keep the credentials in `application.yml` only (never put them in `.env` or git).
3. Recommended: enable **Extended Quota Mode** for the Spotify app (dashboard
   &rarr; app &rarr; "Extended quota mode"). Fresh apps in default *limited quota*
   mode cannot use API batch endpoints and newer playlist endpoints.
4. Newly created Spotify apps must also use *anonymous token* auth for
   playlists/generated playlists and recommendations. Run
   [topi314/spotify-tokener](https://github.com/topi314/spotify-tokener) as a
   container (valid anonymous token JSON is served at `/api/token`):
   ```bash
   docker run -d --name spotify-tokener --restart unless-stopped \
     -p 127.0.0.1:8080:8080 ghcr.io/topi314/spotify-tokener:master
   ```
   LavaSrc fetches it via `customTokenEndpoint`, so the cron/systemd restart
   flow must bring up the tokener before Lavalink needs it.
5. The bot uses a `VoidWavePlayer` subclass whose autoplay emits LavaSrc's
   `sprec:<trackIds>` format (wavelink's default `sprec:seed_tracks=...` form is
   incompatible with LavaSrc 4.x). If you bump `wavelink`, re-check
   `_do_recommendation` in `cogs/music.py`.

## Kirkify

The `/kirkify` slash command runs `kirkify.py` from the gitignored
`third_party/` directory (clone of https://github.com/dylanoonk/kirkify.py) as a
subprocess, so the bot process must be able to reach it:

1. Clone the tool so it ends up at
   `<repo root>/third_party/kirkify.py/kirkify.py`.
2. Download the face-swap model into that same directory using the `curl`
   command from the tool's own README (saves as `inswapper_128.onnx`, ~528 MB),
   then run `venv/bin/python kirkify.py init` once from the repo root.
3. `requirements.txt` already lists the extra deps (`opencv-python`,
   `insightface`, `onnxruntime`, `tqdm`), so a fresh `pip install -r
   requirements.txt` in the production `venv/` covers them.

The tool needs the **same Python that the bot runs with**; the command spawns it
via `sys.executable`, so it uses whichever venv the bot itself runs in; just
make sure that venv has the extra deps installed.

## systemd units

The example units use `User=your-user`, `WorkingDirectory=/home/your-user/VoidWave`
and `venv/bin/python3 -u` (the `-u` keeps the bot's stdout unbuffered so
`journalctl` shows logs promptly).

### Bot: `voidwave.service`

```ini
[Unit]
Description=VoidWave discord bot
After=network-online.target tailscaled.service voidwave-lavalink.service
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=10

[Service]
User=your-user
WorkingDirectory=/home/your-user/VoidWave
ExecStart=/home/your-user/VoidWave/venv/bin/python3 -u bot.py
Restart=always
RestartSec=5
# bot.py reads .env itself, so no EnvironmentFile is needed

[Install]
WantedBy=multi-user.target
```

The bot creates/patches the DB schema on startup and **re-syncs all slash
commands globally** (`cogs/events.py` `tree.sync()`), so a restart takes a few
extra seconds before commands appear; that's expected.

The bot installs SIGTERM/SIGINT handlers that close the gateway and other
connections cleanly before exiting.

If the bot cannot come online within 60s of boot (e.g. DNS isn't up yet because
name resolution goes through Tailscale, which starts just after this unit), it
exits non-zero so `Restart=always` retries instead of hanging idly. A runtime
watchdog also exits (non-zero) if the gateway stays disconnected for ~3 minutes,
covering silent reconnect hangs.

On startup the bot does **not** chunk members across all guilds
(`chunk_guilds_at_startup=False`). Chunking sends one `REQUEST_MEMBERS` per
guild at connect time, and with 100+ guilds that burst blows through Discord's
110-messages-per-60-seconds gateway limit, stalling the connect with
"WebSocket in shard ID None is ratelimited, waiting ~59 seconds" on every
startup. Members are still cached as they interact; any code that needs an
authoritative membership check can use `guild.fetch_member()`.

### Website + admin: `voidwave_website.service`

The dashboard runs under gunicorn (installed system wide, `/usr/bin/gunicorn`),
so `python app.py` inside the venv is only for local dev:

```ini
[Unit]
Description=VoidWave Flask App
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=10

[Service]
User=your-user
WorkingDirectory=/home/your-user/VoidWave
ExecStart=/usr/bin/gunicorn -w 4 -b 127.0.0.1:8002 app:app \
          --access-logfile - \
          --error-logfile -
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The app listens on `127.0.0.1:8002` only; put a reverse proxy in front of it
(see below).

## Reverse proxy (HTTPS required)

`app.py` sets `SESSION_COOKIE_SECURE = True`, so **it must be served over HTTPS**
or admin login sessions won't stick. Example nginx block:

```nginx
server {
    listen 443 ssl http2;
    server_name yourbot.example.com;

    ssl_certificate     /etc/letsencrypt/live/yourbot.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourbot.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # optional: upgrade HTTP -> HTTPS
    listen 80;
    server_name yourbot.example.com;
    return 301 https://$host$request_uri;
}
```

The admin panel lives at `/admin`. It needs `ADMIN_PASSWORD` set (otherwise it
returns 503) and sends a 2FA code to `ADMIN_WEBHOOK_URL` on every login.
`ERROR_WEBHOOK_URL` receives every `ERROR+` log from bot and dashboard
(falls back to `ADMIN_WEBHOOK_URL`).

If the site is behind Cloudflare, the admin panel uses `CF-Connecting-IP`
for the client's real IP (login rate limiting / audit log). Cloudflare
rewrites that header on every hop, so it can't be spoofed *through* CF.
Make sure the origin (this nginx box) is not directly reachable: restrict
it to Cloudflare's published IP ranges (firewall rules or a tunnel), or
someone can hit the origin directly and send a fake `CF-Connecting-IP`
header to bypass the login lockout and fake the audit trail.

## Stats graphs

The bot writes one snapshot per hour to `stats_history.json`
(`cogs/events.py` `stats_log_loop`). Regenerate the graphs regularly with cron,
e.g. hourly:

```
15 * * * *  cd /home/your-user/VoidWave && ./venv/bin/python generate_graphs.py >> graphs.log 2>&1
```

This rebuilds `Graphs/*.png` and `static/images/stats.png` (the README banner).
All of these are gitignored runtime artifacts.

## Backups

Use the admin panel's **Backups** page (`/admin/backups`); it exports `database.db`
to `~/Backups/VoidWave` (`Path.home()`, the unit's service user) and keeps the 48
newest; it can also restore. The health page flags a backup as stale when the
newest is older than 7 days.

## Logs

- `journalctl -u voidwave.service --no-pager -n 100`
- `journalctl -u voidwave_website.service --no-pager -n 100` (also shown in the
  admin panel's bot page)
- Repo-root file logs: `admin.log`, `command_logs.txt`, `graphs.log` (gitignored).

## Updating

```bash
cd ~/VoidWave
git pull
sudo systemctl restart voidwave.service voidwave_website.service
```

The admin panel can also stop/restart the bot via **Bot** → **Stop/Restart**
(this requires the shell user to have passwordless `sudo systemctl ...` rights;
`admin/helpers.py` tries `systemctl` and then `sudo -n systemctl`).