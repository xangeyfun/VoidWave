import sqlite3
import time
import os
import hmac
import hashlib
import secrets
import json
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import request, session, abort

from .constants import (
    ADMIN_LOG_FILE, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW, TWOFA_TTL,
    BACKUP_DIR, KEEP_BACKUPS, BOT_SERVICE,
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_admin_tables():
    conn = _db()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_login_codes (
            token TEXT PRIMARY KEY,
            code_hash TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            ip TEXT,
            created_at INTEGER
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_rate_limits (
            ip TEXT PRIMARY KEY,
            attempts INTEGER DEFAULT 0,
            window_start INTEGER
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            detail TEXT DEFAULT '',
            guild_id INTEGER,
            user_id INTEGER
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_events_ts ON admin_events(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_events_type ON admin_events(event_type)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS user_blocks (
            user_id INTEGER,
            feature TEXT,
            blocked_at INTEGER,
            PRIMARY KEY (user_id, feature)
        )
        """)
        conn.commit()
    finally:
        conn.close()


def _clear_cache():
    try:
        from app import cache
        cache.clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Config / identity
# ---------------------------------------------------------------------------

def _admin_password():
    return os.getenv("ADMIN_PASSWORD") or ""


def _webhook_url():
    return os.getenv("ADMIN_WEBHOOK_URL") or ""


def _twofa_enabled():
    return os.getenv("ADMIN_REQUIRE_2FA", "true").lower() not in ("0", "false", "no", "off")


def _client_ip():
    cf = request.headers.get("CF-Connecting-IP")
    if cf and cf.strip():
        return cf.strip()
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(action, details="", ip=None):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} {action} {ip or _client_ip()} {details}".rstrip()
    try:
        with open(ADMIN_LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _read_log_lines():
    if not os.path.exists(ADMIN_LOG_FILE):
        return []
    try:
        with open(ADMIN_LOG_FILE, "r") as f:
            return [ln.rstrip("\n") for ln in f if ln.strip()]
    except OSError:
        return []


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

def _csrf_token():
    tok = session.get("_csrf")
    if not tok:
        tok = secrets.token_hex(16)
        session["_csrf"] = tok
    return tok


def _csrf_ok():
    form_tok = request.form.get("csrf_token")
    sess_tok = session.get("_csrf")
    return bool(form_tok and sess_tok and hmac.compare_digest(form_tok, sess_tok))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _parse_int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError):
        abort(400, description=f"Invalid value for {name}: {value!r}")


def _normalize_progress(level, progress, out_of):
    while progress >= out_of and out_of > 0:
        progress -= out_of
        level += 1
        out_of = 100 + level * 20
    return level, progress, out_of


# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------

def _service_active(unit):
    try:
        r = subprocess.run(
            ["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0 and r.stdout.strip() == "active"
    except Exception:
        return None


def _service_stop(unit):
    for cmd in (["systemctl", "stop", unit],
                ["sudo", "-n", "systemctl", "stop", unit]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                return True, f"Stopped {unit}"
            if "denied" in r.stderr.lower() or "not authorized" in r.stderr.lower():
                continue
            return False, f"Could not stop {unit}: {r.stderr.strip() or r.returncode}"
        except Exception as e:
            return False, str(e)
    return False, f"No permission to stop {unit}. Stop it manually and use the other option."


def _service_start(unit):
    for cmd in (["systemctl", "start", unit],
                ["sudo", "-n", "systemctl", "start", unit]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                return True, f"Started {unit}"
            if "denied" in r.stderr.lower() or "not authorized" in r.stderr.lower():
                continue
            return False, f"Could not start {unit}: {r.stderr.strip() or r.returncode}"
        except Exception as e:
            return False, str(e)
    return False, f"Start {unit} manually: sudo systemctl start {unit}"


def _service_status(unit):
    try:
        r = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=5,
        )
        active = r.stdout.strip()
        r2 = subprocess.run(
            ["systemctl", "show", unit, "--property=ActiveEnterTimestamp,MainPID,MemoryCurrent,NRestarts"],
            capture_output=True, text=True, timeout=5,
        )
        props = {}
        for line in r2.stdout.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v
        return {
            "active": active == "active",
            "state": active,
            "pid": props.get("MainPID", "?"),
            "uptime": props.get("ActiveEnterTimestamp", ""),
            "memory": props.get("MemoryCurrent", "?"),
            "restarts": props.get("NRestarts", "?"),
        }
    except Exception:
        return {"active": False, "state": "unknown", "pid": "?", "uptime": "", "memory": "?", "restarts": "?"}


def _service_logs(unit, lines=100):
    try:
        r = subprocess.run(
            ["journalctl", "-u", unit, "--no-pager", "-n", str(lines), "--output=short-iso"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip().splitlines() if r.returncode == 0 else [f"Error: {r.stderr.strip()}"]
    except Exception as e:
        return [f"Error fetching logs: {e}"]


def _bot_status():
    try:
        r = subprocess.run(["systemctl", "is-active", "voidwave.service"], capture_output=True, text=True, timeout=2)
        return r.stdout.strip() == "active"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def _rate_limit_attempts(ip):
    conn = _db()
    try:
        row = conn.execute(
            "SELECT attempts, window_start FROM admin_rate_limits WHERE ip=?",
            (ip,)
        ).fetchone()
        if not row:
            return 0
        if int(time.time()) - row["window_start"] >= RATE_LIMIT_WINDOW:
            conn.execute("DELETE FROM admin_rate_limits WHERE ip=?", (ip,))
            conn.commit()
            return 0
        return row["attempts"]
    finally:
        conn.close()


def _rate_limit_fail(ip):
    conn = _db()
    try:
        now = int(time.time())
        row = conn.execute(
            "SELECT attempts, window_start FROM admin_rate_limits WHERE ip=?",
            (ip,)
        ).fetchone()
        if not row or now - row["window_start"] >= RATE_LIMIT_WINDOW:
            conn.execute(
                "INSERT INTO admin_rate_limits (ip, attempts, window_start) VALUES (?, 1, ?) "
                "ON CONFLICT(ip) DO UPDATE SET attempts=1, window_start=excluded.window_start",
                (ip, now)
            )
        else:
            conn.execute("UPDATE admin_rate_limits SET attempts = attempts + 1 WHERE ip=?", (ip,))
        conn.commit()
    finally:
        conn.close()


def _rate_limit_reset(ip):
    conn = _db()
    try:
        conn.execute("DELETE FROM admin_rate_limits WHERE ip=?", (ip,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2FA
# ---------------------------------------------------------------------------

def _issue_2fa(ip):
    code = f"{secrets.randbelow(10 ** 8):08d}"
    token = secrets.token_hex(32)
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO admin_login_codes (token, code_hash, expires_at, ip, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, hashlib.sha256(code.encode()).hexdigest(),
             int(time.time()) + TWOFA_TTL, ip, int(time.time()))
        )
        conn.commit()
    finally:
        conn.close()
    return token, code


def _consume_2fa(token, code):
    conn = _db()
    try:
        row = conn.execute(
            "SELECT code_hash, expires_at FROM admin_login_codes WHERE token=?",
            (token,)
        ).fetchone()
        if not row:
            return False
        if int(time.time()) > row["expires_at"]:
            conn.execute("DELETE FROM admin_login_codes WHERE token=?", (token,))
            conn.commit()
            return False
        ok = hmac.compare_digest(row["code_hash"], hashlib.sha256(code.encode()).hexdigest())
        conn.execute("DELETE FROM admin_login_codes WHERE token=?", (token,))
        conn.commit()
        return ok
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Webhook / session
# ---------------------------------------------------------------------------

def _send_webhook(payload):
    url = _webhook_url()
    if not url:
        raise RuntimeError("no webhook configured")
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com/xangey/VoidWave, 1.0) Python/3.11",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def _complete_login(ip):
    session.clear()
    session["admin"] = True
    session["admin_nonce"] = secrets.token_hex(16)
    session["login_ip"] = ip
    session["login_time"] = datetime.now(timezone.utc).isoformat()
    session.permanent = True


# ---------------------------------------------------------------------------
# Backup helpers
# ---------------------------------------------------------------------------

def _backup_current(suffix=""):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    src = Path("database.db")
    if not src.exists():
        return None, "database.db not found"
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    name = f"database_{ts}{suffix}.db"
    dst = BACKUP_DIR / name
    shutil.copy2(src, dst)
    return dst, None


def _prune_backups():
    files = sorted(BACKUP_DIR.glob("database_*.db"), reverse=True)
    removed = 0
    for f in files[KEEP_BACKUPS:]:
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _list_backups():
    out = []
    for f in sorted(BACKUP_DIR.glob("database_*.db"), reverse=True):
        st = f.stat()
        out.append({
            "name": f.name,
            "path": f,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime),
        })
    return out


# ---------------------------------------------------------------------------
# Events helpers
# ---------------------------------------------------------------------------

def _log_event(event_type, detail="", guild_id=None, user_id=None):
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO admin_events (ts, event_type, detail, guild_id, user_id) VALUES (?, ?, ?, ?, ?)",
            (int(time.time()), event_type, detail, guild_id, user_id)
        )
        conn.commit()
    finally:
        conn.close()


def _recent_events(limit=50, since_id=0):
    conn = _db()
    try:
        if since_id:
            rows = conn.execute(
                "SELECT id, ts, event_type, detail, guild_id, user_id "
                "FROM admin_events WHERE id > ? ORDER BY id DESC LIMIT ?",
                (since_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, ts, event_type, detail, guild_id, user_id "
                "FROM admin_events ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command logs helpers
# ---------------------------------------------------------------------------

COMMAND_LOG_FILE = "command_logs.txt"


def _parse_command_logs():
    if not os.path.exists(COMMAND_LOG_FILE):
        return []
    entries = []
    try:
        with open(COMMAND_LOG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(" ", 3)
                ts = f"{parts[0]} {parts[1]}" if len(parts) > 1 else ""
                rest = parts[3] if len(parts) > 3 else ""
                cmd_part = rest.split("'", 2)
                cmd_name = cmd_part[1] if len(cmd_part) > 1 else ""
                after_cmd = cmd_part[2] if len(cmd_part) > 2 else ""
                user_part = after_cmd.split("used by '")
                username = user_part[1].split("'")[0] if len(user_part) > 1 else ""
                guild_full = ""
                guild_name = ""
                guild_id = ""
                if len(user_part) > 1 and "in '" in user_part[1]:
                    after_user = user_part[1].split("in '", 1)[1]
                    guild_full = after_user.split("' (", 1)[0] if "' (" in after_user else after_user.split("'")[0]
                    guild_name = guild_full.split("/")[0] if "/" in guild_full else guild_full
                uid_part = after_cmd.split("user_id: ")
                user_id = uid_part[1].split(",")[0].split(")")[0] if len(uid_part) > 1 else ""
                gid_part = after_cmd.split("guild_id: ")
                guild_id = gid_part[1].split(")")[0] if len(gid_part) > 1 else ""
                clean_cmd = cmd_name.lstrip("/")
                entries.append({
                    "ts": ts,
                    "command": clean_cmd.split(" ")[0] if clean_cmd else "",
                    "options": " ".join(clean_cmd.split(" ")[1:]) if clean_cmd else "",
                    "username": username,
                    "guild_name": guild_name,
                    "user_id": user_id,
                    "guild_id": guild_id,
                })
    except OSError:
        pass
    return entries


def _command_stats():
    entries = _parse_command_logs()
    cmd_counts = {}
    user_counts = {}
    guild_counts = {}
    for e in entries:
        cmd = e["command"]
        if cmd:
            cmd_counts[cmd] = cmd_counts.get(cmd, 0) + 1
        user = e["username"]
        if user:
            user_counts[user] = user_counts.get(user, 0) + 1
        guild = e["guild_name"]
        if guild:
            guild_counts[guild] = guild_counts.get(guild, 0) + 1
    return {
        "total": len(entries),
        "by_command": sorted(cmd_counts.items(), key=lambda x: -x[1]),
        "by_user": sorted(user_counts.items(), key=lambda x: -x[1])[:20],
        "by_guild": sorted(guild_counts.items(), key=lambda x: -x[1])[:20],
        "recent": entries[-50:][::-1],
    }


# ---------------------------------------------------------------------------
# Stale data helpers
# ---------------------------------------------------------------------------

def _stale_users(days=30):
    conn = _db()
    try:
        cutoff = int(time.time()) - (days * 86400)
        rows = conn.execute(
            "SELECT guild_id, user_id, display_name, username, level, total_xp, last_message "
            "FROM users WHERE last_message = '' OR last_message IS NULL "
            "OR datetime(last_message) < datetime(?, 'unixepoch') "
            "ORDER BY last_message ASC LIMIT 50",
            (cutoff,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
