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
