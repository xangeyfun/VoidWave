import sqlite3
import time
import os
import json
import hmac
import hashlib
import secrets
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, abort, jsonify,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

BACKUP_DIR = Path.home() / "Backups" / "VoidWave"
ADMIN_LOG_FILE = "admin.log"
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 900
TWOFA_TTL = 120
KEEP_BACKUPS = 48
TABLES = {
    "users", "bot_stats", "guild_settings", "level_roles", "vote_boosts",
}
REQUIRED_USERS_COLUMNS = {
    "guild_id", "user_id", "display_name", "username", "level",
    "progress", "out_of", "last_message", "total_messages",
    "total_messages_xp", "total_xp", "vc_minutes", "vc_xp_minutes",
    "avatar_hash",
}
USER_FIELDS = {
    "display_name": "text",
    "username": "text",
    "avatar_hash": "text",
    "level": "int",
    "progress": "int",
    "out_of": "int",
    "total_xp": "int",
    "total_messages": "int",
    "total_messages_xp": "int",
    "vc_minutes": "int",
    "vc_xp_minutes": "int",
    "last_message": "text",
}


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
# Auth
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


@admin_bp.before_request
def _guard():
    _ensure_admin_tables()

    if not _admin_password():
        return render_template(
            "admin_login.html", config_error="ADMIN_PASSWORD is not set in .env", password_only=True
        ), 503

    if request.method == "POST" and not _csrf_ok():
        abort(400)

    endpoint = request.endpoint or ""
    open_routes = {"admin.login", "admin.verify_2fa"}

    if endpoint in open_routes:
        if endpoint == "admin.login" and session.get("admin"):
            return redirect(url_for("admin.dashboard"))
        return None

    if not session.get("admin"):
        return redirect(url_for("admin.login"))
    return None


@admin_bp.context_processor
def _inject():
    return {
        "csrf_token": _csrf_token,
        "client_ip": _client_ip,
        "now": datetime.now(),
    }


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    ip = _client_ip()

    if request.method == "POST":
        if _rate_limit_attempts(ip) >= RATE_LIMIT_MAX:
            _log("LOGIN BLOCKED", "rate limited", ip)
            return render_template(
                "admin_login.html",
                error="Too many failed attempts. Try again in 15 minutes.",
                password_only=not _twofa_enabled(),
            ), 429

        password = request.form.get("password", "")
        if not hmac.compare_digest(password, _admin_password()):
            _rate_limit_fail(ip)
            _log("LOGIN FAIL", "wrong password", ip)
            return render_template(
                "admin_login.html",
                error="Incorrect password.",
                password_only=not _twofa_enabled(),
            ), 401

        _rate_limit_reset(ip)
        _log("PASSWORD OK", "issuing 2FA code", ip)

        if _twofa_enabled():
            if not _webhook_url():
                _log("LOGIN FAIL", "2FA enabled but ADMIN_WEBHOOK_URL missing", ip)
                return render_template(
                    "admin_login.html",
                    error="2FA is enabled but ADMIN_WEBHOOK_URL is not set in .env.",
                    password_only=False,
                ), 503
            token, code = _issue_2fa(ip)
            try:
                _send_webhook({
                    "username": "VoidWave Admin",
                    "embeds": [{
                        "title": "Admin login 2FA code",
                        "description": f"Your 8-digit code is **`{code}`**",
                        "color": 0x8438fc,
                        "fields": [
                            {"name": "Expires", "value": "in 2 minutes", "inline": True},
                            {"name": "Requested from", "value": f"`{ip}`", "inline": True},
                        ],
                        "footer": {"text": "Don't share this code. It is one-time use."},
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }],
                })
            except Exception as e:
                _log("2FA SEND FAIL", str(e), ip)
                return render_template(
                    "admin_login.html",
                    error="Could not deliver the 2FA code to Discord. Try again.",
                    password_only=False,
                ), 500
            session["pending_2fa"] = token
            session["pending_2fa_ip"] = ip
            return render_template("admin_login.html", twofa=True)

        _complete_login(ip)
        _log("LOGIN OK", "password-only login", ip)
        return redirect(url_for("admin.dashboard"))

    return render_template("admin_login.html", password_only=not _twofa_enabled())


@admin_bp.route("/login/2fa", methods=["POST"])
def verify_2fa():
    ip = _client_ip()

    if _rate_limit_attempts(ip) >= RATE_LIMIT_MAX:
        _log("2FA BLOCKED", "rate limited", ip)
        return render_template(
            "admin_login.html", error="Too many failed attempts. Try again in 15 minutes.", password_only=False
        ), 429

    token = session.get("pending_2fa")
    code = (request.form.get("code") or "").strip()

    if not token or not code.isdigit() or len(code) != 8:
        _rate_limit_fail(ip)
        _log("2FA FAIL", "malformed code", ip)
        return render_template(
            "admin_login.html", twofa=True, error="Invalid code.", password_only=False
        ), 401

    if not _consume_2fa(token, code):
        _rate_limit_fail(ip)
        _log("2FA FAIL", "wrong or expired code", ip)
        return render_template(
            "admin_login.html", twofa=True, error="Wrong or expired code.", password_only=False
        ), 401

    _rate_limit_reset(ip)
    _log("LOGIN OK", "authenticated with 2FA", ip)
    _complete_login(ip)
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/logout")
def logout():
    _log("LOGOUT", "")
    session.clear()
    return redirect(url_for("admin.login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def _bot_status():
    """Check if the bot process is running."""
    try:
        import subprocess
        r = subprocess.run(["systemctl", "is-active", "voidwave.service"], capture_output=True, text=True, timeout=2)
        return r.stdout.strip() == "active"
    except Exception:
        return None


def _growth_stats(conn):
    """Calculate growth metrics from last_message timestamps."""
    now = int(time.time())
    day = now - 86400
    week = now - 604800
    month = now - 2592000

    def count_after(ts):
        r = conn.execute(
            "SELECT COUNT(*) FROM users WHERE last_message != '' AND datetime(last_message) > datetime(?, 'unixepoch')",
            (ts,)
        ).fetchone()
        return r[0] if r else 0

    def count_before(ts):
        r = conn.execute(
            "SELECT COUNT(*) FROM users WHERE last_message != '' AND datetime(last_message) <= datetime(?, 'unixepoch')",
            (ts,)
        ).fetchone()
        return r[0] if r else 0

    # Users with activity in windows
    active_24h = count_after(day)
    active_7d = count_after(week)
    active_30d = count_after(month)

    # New users in windows (approximate: first message in window)
    new_24h = conn.execute("""
        SELECT COUNT(*) FROM users
        WHERE last_message != '' AND datetime(last_message) > datetime(?, 'unixepoch')
        AND user_id NOT IN (
            SELECT user_id FROM users WHERE last_message != '' AND datetime(last_message) <= datetime(?, 'unixepoch')
        )
    """, (day, day)).fetchone()[0]

    new_7d = conn.execute("""
        SELECT COUNT(*) FROM users
        WHERE last_message != '' AND datetime(last_message) > datetime(?, 'unixepoch')
        AND user_id NOT IN (
            SELECT user_id FROM users WHERE last_message != '' AND datetime(last_message) <= datetime(?, 'unixepoch')
        )
    """, (week, week)).fetchone()[0]

    # Rates per day
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_msgs = conn.execute("SELECT COALESCE(SUM(total_messages),0) FROM users").fetchone()[0]
    total_xp = conn.execute("SELECT COALESCE(SUM(total_xp),0) FROM users").fetchone()[0]
    total_vc = conn.execute("SELECT COALESCE(SUM(vc_minutes),0) FROM users").fetchone()[0]

    # Estimate daily rates from last 7 days active users
    msgs_7d = conn.execute("""
        SELECT COALESCE(SUM(total_messages),0) FROM users
        WHERE last_message != '' AND datetime(last_message) > datetime(?, 'unixepoch')
    """, (week,)).fetchone()[0] or 0

    xp_7d = conn.execute("""
        SELECT COALESCE(SUM(total_xp),0) FROM users
        WHERE last_message != '' AND datetime(last_message) > datetime(?, 'unixepoch')
    """, (week,)).fetchone()[0] or 0

    vc_7d = conn.execute("""
        SELECT COALESCE(SUM(vc_minutes),0) FROM users
        WHERE last_message != '' AND datetime(last_message) > datetime(?, 'unixepoch')
    """, (week,)).fetchone()[0] or 0

    return {
        "active_24h": active_24h,
        "active_7d": active_7d,
        "active_30d": active_30d,
        "new_24h": new_24h,
        "new_7d": new_7d,
        "msgs_per_day": round(msgs_7d / 7, 1) if msgs_7d else 0,
        "xp_per_day": round(xp_7d / 7, 1) if xp_7d else 0,
        "vc_per_day": round(vc_7d / 7, 1) if vc_7d else 0,
        "msgs_per_user": round(total_msgs / total_users, 1) if total_users else 0,
        "xp_per_user": round(total_xp / total_users, 1) if total_users else 0,
        "vc_per_user": round(total_vc / total_users, 1) if total_users else 0,
    }


def _top_guilds(conn, limit=5):
    """Get top guilds by user count."""
    rows = conn.execute("""
        SELECT guild_id, COUNT(*) as users,
               COALESCE(SUM(total_xp),0) as xp,
               COALESCE(SUM(total_messages),0) as msgs,
               COALESCE(SUM(vc_minutes),0) as vc,
               ROUND(COALESCE(AVG(level),0),1) as avg_level,
               COALESCE(MAX(level),0) as max_level
        FROM users
        GROUP BY guild_id
        ORDER BY users DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def _recent_activity(conn, limit=10):
    """Get recent admin actions with more detail."""
    logs = _read_log_lines()[-limit:][::-1]
    return logs


@admin_bp.route("/")
def dashboard():
    conn = _db()
    try:
        def scalar(sql, params=()):
            r = conn.execute(sql, params).fetchone()
            return r[0] if r else 0

        now_ts = int(time.time())
        day = now_ts - 86400
        week = now_ts - 604800

        data = {
            "users": scalar("SELECT COUNT(*) FROM users"),
            "guilds": scalar("SELECT COUNT(DISTINCT guild_id) FROM users"),
            "total_xp": scalar("SELECT COALESCE(SUM(total_xp),0) FROM users"),
            "total_messages": scalar("SELECT COALESCE(SUM(total_messages),0) FROM users"),
            "vc_minutes": scalar("SELECT COALESCE(SUM(vc_minutes),0) FROM users"),
            "avg_level": scalar("SELECT COALESCE(AVG(level),0) FROM users"),
            "max_level": scalar("SELECT COALESCE(MAX(level),0) FROM users"),
            "level_100": scalar("SELECT COUNT(*) FROM users WHERE level >= 100"),
            "active_boosts": scalar("SELECT COUNT(*) FROM vote_boosts WHERE expires_at > ?", (now_ts,)),
            "settings": scalar("SELECT COUNT(*) FROM guild_settings"),
            "level_roles": scalar("SELECT COUNT(*) FROM level_roles"),
            "qotd_enabled": scalar("SELECT COUNT(*) FROM guild_settings WHERE qotd_enabled=1"),
            "active_24h": scalar(
                "SELECT COUNT(*) FROM users WHERE last_message != '' AND datetime(last_message) > datetime(?, 'unixepoch')",
                (day,)
            ),
            "active_7d": scalar(
                "SELECT COUNT(*) FROM users WHERE last_message != '' AND datetime(last_message) > datetime(?, 'unixepoch')",
                (week,)
            ),
            "total_vc_hours": round(scalar("SELECT COALESCE(SUM(vc_minutes),0) FROM users") / 60, 1),
        }
        data["avg_level"] = round(data["avg_level"], 2)

        recent_logs = _read_log_lines()[-8:][::-1]
        recent_actions = []
        for line in recent_logs:
            parts = line.split(" ", 3)
            ts = f"{parts[0]} {parts[1]}" if len(parts) > 1 else ""
            rest = parts[2] if len(parts) > 2 else ""
            action = rest.split(" ")[0] if rest else ""
            detail = rest.split(" ", 1)[1] if rest.split(" ", 1)[1:] else ""
            recent_actions.append({"ts": ts, "action": action, "detail": detail[:60]})
    finally:
        conn.close()

    checks = _run_checks()
    fail_count = sum(1 for c in checks if not c["ok"])
    warn_count = sum(1 for c in checks if c["category"] == "Info" and not c["ok"])

    backups = _list_backups()
    latest_backup = backups[0] if backups else None

    db_size = Path("database.db").stat().st_size if Path("database.db").exists() else 0
    wal_size = 0
    wal = Path("database.db-wal")
    if wal.exists():
        wal_size = wal.stat().st_size

    bot_alive = _bot_status()

    return render_template(
        "admin_dashboard.html",
        data=data,
        fail_count=fail_count,
        warn_count=warn_count,
        check_count=len(checks),
        checks_ok=sum(1 for c in checks if c["ok"]),
        latest_backup=latest_backup,
        backup_count=len(backups),
        db_size=db_size,
        wal_size=wal_size,
        bot_alive=bot_alive,
        recent_actions=recent_actions,
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def _parse_int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError):
        abort(400, description=f"Invalid value for {name}: {value!r}")


@admin_bp.route("/users")
def users():
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "total_xp")
    order = request.args.get("order", "desc")
    page = max(1, request.args.get("page", 1, type=int))
    per = 25

    valid_sorts = {"level", "total_xp", "total_messages", "vc_minutes", "username", "user_id", "guild_id"}
    if sort not in valid_sorts:
        sort = "total_xp"
    dir_sql = "ASC" if order == "asc" else "DESC"

    conn = _db()
    try:
        where = []
        params = []
        if q.isdigit() and len(q) >= 8:
            where.append("(user_id=? OR guild_id=?)")
            params += [int(q), int(q)]
        elif q:
            like = f"%{q}%"
            where.append("(username LIKE ? OR display_name LIKE ?)")
            params += [like, like]

        wsql = ("WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(f"SELECT COUNT(*) c FROM users {wsql}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM users {wsql} ORDER BY {sort} {dir_sql}, user_id LIMIT ? OFFSET ?",
            params + [per, (page - 1) * per]
        ).fetchall()

        boost_map = {
            r["user_id"]: r
            for r in conn.execute("SELECT * FROM vote_boosts").fetchall()
        }
    finally:
        conn.close()

    total_pages = max(1, (total + per - 1) // per)

    return render_template(
        "admin_users.html",
        rows=rows,
        total=total,
        q=q,
        sort=sort,
        order=order,
        page=page,
        total_pages=total_pages,
        boost_map=boost_map,
        now=int(time.time()),
    )


@admin_bp.route("/users/add", methods=["POST"])
def user_add():
    guild_id = _parse_int(request.form.get("guild_id"), "guild_id")
    user_id = _parse_int(request.form.get("user_id"), "user_id")
    username = (request.form.get("username") or "unknown").strip() or "unknown"

    if guild_id < 1000000000000 or user_id < 1000000000000:
        _log("USER ADD FAIL", f"invalid ids guild={guild_id} user={user_id}")
        return redirect(url_for("admin.users", err="Invalid Discord IDs (must be 13+ digits)"))

    conn = _db()
    try:
        conn.execute("""
            INSERT INTO users (
                guild_id, user_id, display_name, username,
                level, progress, out_of,
                last_message, total_messages, total_messages_xp, total_xp,
                vc_minutes, vc_xp_minutes, avatar_hash
            ) VALUES (?, ?, ?, ?, 0, 0, 100, '', 0, 0, 0, 0, 0, NULL)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET username = excluded.username
        """, (guild_id, user_id, username, username))
        conn.commit()
        _clear_cache()
    finally:
        conn.close()

    _log("USER ADD", f"guild={guild_id} user={user_id}")
    return redirect(url_for("admin.user_edit", guild_id=guild_id, user_id=user_id))


def _normalize_progress(level, progress, out_of):
    while progress >= out_of and out_of > 0:
        progress -= out_of
        level += 1
        out_of = 100 + level * 20
    return level, progress, out_of


@admin_bp.route("/users/<int:guild_id>/<int:user_id>", methods=["GET", "POST"])
def user_edit(guild_id, user_id):
    conn = _db()
    try:
        user = conn.execute(
            "SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        ).fetchone()
        if not user:
            abort(404)

        if request.method == "POST":
            data = {}
            for field, ftype in USER_FIELDS.items():
                raw = request.form.get(field, "")
                if ftype == "int":
                    if raw == "":
                        abort(400)
                    val = int(raw)
                    data[field] = val
                else:
                    data[field] = raw.strip()

            if any(data[f] < 0 for f in ("level", "progress", "out_of", "total_xp",
                                         "total_messages", "total_messages_xp",
                                         "vc_minutes", "vc_xp_minutes")):
                _log("USER EDIT FAIL", f"negative value guild={guild_id} user={user_id}")
                return render_template(
                    "admin_user_edit.html", user=user, error="Values cannot be negative."
                )

            auto_fix = request.form.get("auto_fix") == "on"

            if auto_fix:
                level, progress, out_of = _normalize_progress(
                    data["level"], data["progress"], data["out_of"]
                )
                data["level"], data["progress"], data["out_of"] = level, progress, out_of
            elif data["progress"] >= data["out_of"] and data["out_of"] > 0:
                _log("USER EDIT WARN", f"progress>=out_of after edit guild={guild_id} user={user_id}")
            elif data["out_of"] <= 0:
                return render_template(
                    "admin_user_edit.html", user=user,
                    error="out_of must be positive (or enable auto-fix)."
                )

            sets = ", ".join(f"{f}=?" for f in data)
            conn.execute(
                f"UPDATE users SET {sets} WHERE guild_id=? AND user_id=?",
                list(data.values()) + [guild_id, user_id]
            )
            conn.commit()
            _clear_cache()
            _log("USER EDIT", f"guild={guild_id} user={user_id} {json.dumps(data)}")

            user = conn.execute(
                "SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)
            ).fetchone()
            flash_msg = "User updated."

        else:
            flash_msg = None

        rank = conn.execute(
            "SELECT COUNT(*) + 1 r FROM users WHERE guild_id=? AND total_xp > ?",
            (guild_id, user["total_xp"])
        ).fetchone()["r"]
        global_rank = conn.execute(
            "SELECT COUNT(*) + 1 r FROM users WHERE total_xp > ?",
            (user["total_xp"],)
        ).fetchone()["r"]
        boost = conn.execute(
            "SELECT * FROM vote_boosts WHERE user_id=?", (user_id,)
        ).fetchone()
        guild_rows = conn.execute(
            "SELECT guild_id FROM users WHERE user_id=?", (user_id,)
        ).fetchall()
    finally:
        conn.close()

    return render_template(
        "admin_user_edit.html",
        user=user,
        rank=rank,
        global_rank=global_rank,
        boost=boost,
        guild_rows=guild_rows,
        flash_msg=flash_msg,
        now=int(time.time()),
    )


@admin_bp.route("/users/<int:guild_id>/<int:user_id>/delete", methods=["POST"])
def user_delete(guild_id, user_id):
    confirm = (request.form.get("confirm") or "").strip()
    if confirm != "DELETE":
        return redirect(url_for("admin.user_edit", guild_id=guild_id, user_id=user_id,
                                err="Confirmation must be DELETE"))

    conn = _db()
    try:
        cur = conn.execute(
            "DELETE FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        removed = cur.rowcount
        conn.commit()
        _clear_cache()
    finally:
        conn.close()

    _log("USER DELETE", f"guild={guild_id} user={user_id} rows={removed}")
    return redirect(url_for("admin.users", msg=f"Deleted {removed} row(s)."))


# ---------------------------------------------------------------------------
# Forget / right-to-be-forgotten
# ---------------------------------------------------------------------------

def _stale_user_sql(days):
    ts = datetime.now() - timedelta(days=days)
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
    return (
        "SELECT * FROM users WHERE level=0 AND total_xp=0 AND total_messages=0 "
        "AND vc_minutes=0 AND (last_message='' OR last_message < ?)",
        (ts_str,)
    )


def _forget_preview(spec):
    conn = _db()
    try:
        def rows(sql, params=()):
            return conn.execute(sql, params).fetchall()

        if spec["type"] == "user_all":
            ids = spec["user_ids"]
            marks = ",".join("?" * len(ids))
            ur = rows(f"SELECT * FROM users WHERE user_id IN ({marks})", ids)
            br = rows(f"SELECT * FROM vote_boosts WHERE user_id IN ({marks})", ids)
            return {
                "users_rows": len(ur),
                "distinct_guilds": len({r["guild_id"] for r in ur}),
                "boost_rows": len(br),
                "user_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                  "username": r["username"] or "unknown",
                                  "display_name": r["display_name"] or "",
                                  "level": r["level"], "total_xp": r["total_xp"]} for r in ur[:50]],
                "boost_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                   "expires_at": r["expires_at"]} for r in br[:50]],
            }
        if spec["type"] == "user_guild":
            gid = spec["guild_id"]
            marks = ",".join("?" * len(spec["user_ids"]))
            ur = rows(f"SELECT * FROM users WHERE guild_id=? AND user_id IN ({marks})", [gid] + spec["user_ids"])
            return {
                "users_rows": len(ur), "distinct_guilds": 1, "boost_rows": 0,
                "user_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                  "username": r["username"] or "unknown",
                                  "display_name": r["display_name"] or "",
                                  "level": r["level"], "total_xp": r["total_xp"]} for r in ur[:50]],
            }
        if spec["type"] == "guild_users":
            ur = rows("SELECT * FROM users WHERE guild_id=?", (spec["guild_id"],))
            return {
                "users_rows": len(ur), "distinct_guilds": 1, "boost_rows": 0,
                "user_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                  "username": r["username"] or "unknown",
                                  "display_name": r["display_name"] or "",
                                  "level": r["level"], "total_xp": r["total_xp"]} for r in ur[:50]],
            }
        if spec["type"] == "guild_full":
            gid = spec["guild_id"]
            ur = rows("SELECT * FROM users WHERE guild_id=?", (gid,))
            gr = rows("SELECT * FROM guild_settings WHERE guild_id=?", (gid,))
            lr = rows("SELECT * FROM level_roles WHERE guild_id=?", (gid,))
            return {
                "users_rows": len(ur), "guild_settings_rows": len(gr), "level_roles_rows": len(lr),
                "user_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                  "username": r["username"] or "unknown",
                                  "display_name": r["display_name"] or "",
                                  "level": r["level"], "total_xp": r["total_xp"]} for r in ur[:50]],
                "level_role_details": [{"level": r["level"], "role_id": r["role_id"]} for r in lr],
            }
        if spec["type"] == "boost":
            marks = ",".join("?" * len(spec["user_ids"]))
            br = rows(f"SELECT * FROM vote_boosts WHERE user_id IN ({marks})", spec["user_ids"])
            return {
                "users_rows": 0, "boost_rows": len(br),
                "boost_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                   "expires_at": r["expires_at"]} for r in br[:50]],
            }
        if spec["type"] == "expired_boosts":
            br = rows("SELECT * FROM vote_boosts WHERE expires_at <= ?", (int(time.time()),))
            return {
                "users_rows": 0, "boost_rows": len(br),
                "boost_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                   "expires_at": r["expires_at"]} for r in br[:50]],
            }
        if spec["type"] == "stale_users":
            sql, params = _stale_user_sql(spec["days"])
            ur = rows(sql, params)
            return {
                "users_rows": len(ur), "distinct_guilds": len({r["guild_id"] for r in ur}), "boost_rows": 0,
                "user_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                  "username": r["username"] or "unknown",
                                  "display_name": r["display_name"] or "",
                                  "level": r["level"], "total_xp": r["total_xp"]} for r in ur[:50]],
            }
        if spec["type"] == "reset_all":
            return {"users_rows": rows("SELECT COUNT(*) c FROM users")[0]["c"],
                    "boost_rows": rows("SELECT COUNT(*) c FROM vote_boosts")[0]["c"]}
        if spec["type"] == "reset_table":
            t = spec["table"]
            return {f"{t}_rows": rows(f"SELECT COUNT(*) c FROM {t}")[0]["c"]}
    finally:
        conn.close()
    return {}


def _forget_execute(spec):
    conn = _db()
    counts = {}
    try:
        cur = conn.cursor()

        def run(sql, params=()):
            cur.execute(sql, params)
            counts.setdefault("_total", 0)
            counts["_total"] += cur.rowcount
            return cur.rowcount

        if spec["type"] == "user_all":
            marks = ",".join("?" * len(spec["user_ids"]))
            run(f"DELETE FROM users WHERE user_id IN ({marks})", spec["user_ids"])
            run(f"DELETE FROM vote_boosts WHERE user_id IN ({marks})", spec["user_ids"])
        elif spec["type"] == "user_guild":
            marks = ",".join("?" * len(spec["user_ids"]))
            run(f"DELETE FROM users WHERE guild_id=? AND user_id IN ({marks})",
                [spec["guild_id"]] + spec["user_ids"])
        elif spec["type"] == "guild_users":
            run("DELETE FROM users WHERE guild_id=?", (spec["guild_id"],))
        elif spec["type"] == "guild_full":
            gid = spec["guild_id"]
            run("DELETE FROM users WHERE guild_id=?", (gid,))
            run("DELETE FROM guild_settings WHERE guild_id=?", (gid,))
            run("DELETE FROM level_roles WHERE guild_id=?", (gid,))
        elif spec["type"] == "boost":
            marks = ",".join("?" * len(spec["user_ids"]))
            run(f"DELETE FROM vote_boosts WHERE user_id IN ({marks})", spec["user_ids"])
        elif spec["type"] == "expired_boosts":
            run("DELETE FROM vote_boosts WHERE expires_at <= ?", (int(time.time()),))
        elif spec["type"] == "stale_users":
            sql, params = _stale_user_sql(spec["days"])
            run(sql, params)
        elif spec["type"] == "reset_all":
            run("DELETE FROM users")
            run("DELETE FROM vote_boosts")
        elif spec["type"] == "reset_table":
            t = spec["table"]
            if t not in TABLES:
                abort(400)
            run(f"DELETE FROM {t}")

        conn.commit()
        _clear_cache()
        return counts
    finally:
        conn.close()


def _forget_spec_from_form(form):
    mode = form.get("mode")
    ids_raw = [ln.strip() for ln in (form.get("user_ids") or "").splitlines() if ln.strip()]
    user_ids = []
    for v in ids_raw:
        try:
            iv = int(v)
        except ValueError:
            abort(400)
        if iv < 1000000000000:
            abort(400)
        user_ids.append(iv)
    user_ids = list(dict.fromkeys(user_ids))

    guild_raw = form.get("guild_id", "").strip()
    guild_id = _parse_int(guild_raw, "guild_id") if guild_raw else None

    if mode == "user_all":
        if not user_ids:
            abort(400)
        return {"type": "user_all", "user_ids": user_ids}, "DELETE"
    if mode == "user_guild":
        if not user_ids or not guild_id:
            abort(400)
        return {"type": "user_guild", "user_ids": user_ids, "guild_id": guild_id}, "DELETE"
    if mode in ("guild_users", "guild_full"):
        if not guild_id:
            abort(400)
        return {"type": mode, "guild_id": guild_id}, "DELETE"
    if mode == "boost":
        if not user_ids:
            abort(400)
        return {"type": "boost", "user_ids": user_ids}, "DELETE"
    if mode == "expired_boosts":
        return {"type": "expired_boosts"}, "DELETE"
    if mode == "stale_users":
        days = max(1, min(365, _parse_int(form.get("days", "30"), "days")))
        return {"type": "stale_users", "days": days}, "DELETE"
    if mode == "reset_all":
        return {"type": "reset_all"}, "RESET"
    if mode == "reset_table":
        t = form.get("table", "")
        if t not in TABLES:
            abort(400)
        return {"type": "reset_table", "table": t}, t.upper()
    abort(400)


def _recent_forget_ops(limit=15):
    lines = _read_log_lines()
    ops = []
    for ln in reversed(lines):
        if "FORGET EXEC" in ln:
            parts = ln.split(" ", 3)
            ts = " ".join(parts[:2]) if len(parts) >= 2 else ln[:19]
            detail = parts[3] if len(parts) > 3 else ""
            try:
                data = json.loads(detail)
                spec = data.get("spec", {})
                counts = data.get("counts", {})
                ops.append({"timestamp": ts, "spec": spec, "counts": counts})
            except (json.JSONDecodeError, IndexError):
                ops.append({"timestamp": ts, "spec": {}, "counts": {}, "raw": detail})
            if len(ops) >= limit:
                break
    return ops


@admin_bp.route("/forget", methods=["GET", "POST"])
def forget():
    if request.method == "POST":
        spec, word = _forget_spec_from_form(request.form)
        preview = _forget_preview(spec)
        session["pending_forget_spec"] = spec
        session["pending_forget_word"] = word
        return render_template(
            "admin_forget_confirm.html", spec=spec, preview=preview, word=word
        )
    recent = _recent_forget_ops()
    return render_template("admin_forget.html", recent=recent)


@admin_bp.route("/forget/confirm", methods=["POST"])
def forget_confirm():
    word = session.get("pending_forget_word", "")
    spec = session.get("pending_forget_spec")
    if not spec or not word:
        abort(400)

    confirm = (request.form.get("confirm") or "").strip()
    if not hmac.compare_digest(confirm, word):
        _log("FORGET FAIL", "confirmation mismatch")
        return render_template("admin_forget_confirm.html",
                               spec=spec, preview=_forget_preview(spec), word=word,
                               error=f"Confirmation must be exactly: {word}")

    counts = _forget_execute(spec)
    session.pop("pending_forget_spec", None)
    session.pop("pending_forget_word", None)
    _log("FORGET EXEC", json.dumps({"spec": spec, "counts": counts}))
    return render_template("admin_forget_result.html", spec=spec, counts=counts)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def _run_checks():
    conn = _db()
    results = []

    def add(category, name, ok, detail="", fix=None, sql=None):
        results.append({
            "category": category, "name": name, "ok": bool(ok),
            "detail": detail, "fix": fix, "sql": sql,
        })

    try:
        def q(sql, params=()):
            return conn.execute(sql, params).fetchall()

        integrity = q("PRAGMA integrity_check")
        add("Structure", "SQLite integrity check", all(r[0] == "ok" for r in integrity),
            "; ".join(str(r[0]) for r in integrity), sql="PRAGMA integrity_check")

        quick = q("PRAGMA quick_check")
        add("Structure", "Quick check", all(r[0] == "ok" for r in quick),
            "; ".join(str(r[0]) for r in quick), sql="PRAGMA quick_check")

        tables = {r["name"] for r in q("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in sorted(TABLES) if t not in tables]
        add("Structure", "Required tables", not missing,
            "missing: " + ", ".join(missing) if missing else "all present",
            sql="SELECT name FROM sqlite_master WHERE type='table'")

        cols = {r["name"] for r in q("PRAGMA table_info(users)")}
        missing_cols = sorted(REQUIRED_USERS_COLUMNS - cols)
        add("Structure", "users columns", not missing_cols,
            "missing: " + ", ".join(missing_cols) if missing_cols else "all present",
            sql="PRAGMA table_info(users)")

        rows = q("SELECT guild_id, user_id, level, progress, out_of FROM users WHERE progress >= out_of")
        add("Data", "progress >= out_of", not rows,
            f"{len(rows)} row(s)", fix="normalize" if rows else None,
            sql="SELECT guild_id, user_id, level, progress, out_of FROM users\nWHERE progress >= out_of")

        rows = q("SELECT guild_id, user_id FROM users WHERE out_of <= 0")
        add("Data", "out_of <= 0", not rows,
            f"{len(rows)} row(s)", fix="out_of" if rows else None,
            sql="SELECT guild_id, user_id FROM users WHERE out_of <= 0")

        rows = q("""SELECT guild_id, user_id FROM users WHERE level<0 OR progress<0 OR out_of<0
            OR total_messages<0 OR total_messages_xp<0 OR total_xp<0
            OR vc_minutes<0 OR vc_xp_minutes<0""")
        add("Data", "Negative stat values", not rows,
            f"{len(rows)} row(s)", fix="negatives" if rows else None,
            sql="""SELECT guild_id, user_id FROM users
WHERE level < 0 OR progress < 0 OR out_of < 0
   OR total_messages < 0 OR total_messages_xp < 0 OR total_xp < 0
   OR vc_minutes < 0 OR vc_xp_minutes < 0""")

        rows = q("""SELECT guild_id, user_id FROM users WHERE user_id IS NULL OR guild_id IS NULL
            OR level IS NULL OR progress IS NULL OR out_of IS NULL""")
        add("Data", "NULL required fields", not rows,
            f"{len(rows)} row(s)", fix="nulls" if rows else None,
            sql="""SELECT guild_id, user_id FROM users
WHERE user_id IS NULL OR guild_id IS NULL
   OR level IS NULL OR progress IS NULL OR out_of IS NULL""")

        rows = q("SELECT user_id FROM users WHERE user_id < 1000000000000 GROUP BY user_id")
        add("Data", "Suspicious user IDs", not rows, f"{len(rows)} id(s)",
            sql="SELECT user_id FROM users WHERE user_id < 1000000000000 GROUP BY user_id")

        rows = q("SELECT guild_id FROM users WHERE guild_id < 1000000000000 GROUP BY guild_id")
        add("Data", "Suspicious guild IDs", not rows, f"{len(rows)} id(s)",
            sql="SELECT guild_id FROM users WHERE guild_id < 1000000000000 GROUP BY guild_id")

        rows = q("""SELECT guild_id, user_id FROM users
            WHERE level=0 AND total_xp=0 AND total_messages=0 AND vc_minutes=0 AND last_message=''""")
        add("Data", "Empty placeholder users", not rows,
            f"{len(rows)} row(s)", fix="empty" if rows else None,
            sql="""SELECT guild_id, user_id FROM users
WHERE level = 0 AND total_xp = 0 AND total_messages = 0
  AND vc_minutes = 0 AND last_message = ''""")

        rows = q("SELECT COUNT(*) c FROM users WHERE total_messages_xp > total_messages")
        add("Data", "message_xp > total_messages", not rows[0]["c"],
            f"{rows[0]['c']} row(s)",
            sql="SELECT COUNT(*) c FROM users WHERE total_messages_xp > total_messages")

        rows = q("SELECT COUNT(*) c FROM users WHERE total_messages_xp > total_xp")
        add("Data", "message_xp count > total_xp", not rows[0]["c"],
            f"{rows[0]['c']} row(s)",
            sql="SELECT COUNT(*) c FROM users WHERE total_messages_xp > total_xp")

        rows = q("SELECT COUNT(*) c FROM users WHERE vc_xp_minutes > vc_minutes")
        add("Data", "vc_xp_minutes > vc_minutes", not rows[0]["c"],
            f"{rows[0]['c']} row(s)",
            sql="SELECT COUNT(*) c FROM users WHERE vc_xp_minutes > vc_minutes")

        rows = q("""SELECT g.guild_id FROM guild_settings g
            LEFT JOIN (SELECT DISTINCT guild_id FROM users) u ON u.guild_id=g.guild_id
            WHERE u.guild_id IS NULL""")
        add("Data", "guild_settings without any users", not rows,
            f"{len(rows)} guild(s)", fix="orphan_settings" if rows else None,
            sql="""SELECT g.guild_id FROM guild_settings g
LEFT JOIN (SELECT DISTINCT guild_id FROM users) u ON u.guild_id = g.guild_id
WHERE u.guild_id IS NULL""")

        rows = q("SELECT COUNT(*) c FROM users GROUP BY guild_id, user_id HAVING c > 1")
        add("Data", "Duplicate user rows", not rows, f"{len(rows)} duplicated pair(s)",
            sql="SELECT COUNT(*) c FROM users GROUP BY guild_id, user_id HAVING c > 1")

        rows = q("SELECT guild_id FROM users GROUP BY guild_id HAVING COUNT(*) < 2")
        add("Data", "Single-user guilds", True,
            f"{len(rows)} guild(s) with only 1 user",
            sql="SELECT guild_id FROM users GROUP BY guild_id HAVING COUNT(*) < 2")

        rows = q("""SELECT guild_id, user_id FROM users
            WHERE last_message != '' AND date(last_message) > date('now', 'localtime')""")
        add("Data", "Future timestamps", not rows,
            f"{len(rows)} row(s)", fix="future_timestamps" if rows else None,
            sql="""SELECT guild_id, user_id FROM users
WHERE last_message != '' AND date(last_message) > date('now', 'localtime')""")

        rows = q("""SELECT guild_id, user_id, level, progress, out_of FROM users
            WHERE out_of > 0 AND progress > 0 AND level = 0
            AND total_xp = 0 AND total_messages = 0""")
        add("Data", "Has progress but zero stats", not rows,
            f"{len(rows)} row(s)",
            sql="""SELECT guild_id, user_id, level, progress, out_of FROM users
WHERE out_of > 0 AND progress > 0 AND level = 0
  AND total_xp = 0 AND total_messages = 0""")

        rows = q("""SELECT guild_id, user_id FROM users
            WHERE display_name IS NOT NULL AND LENGTH(display_name) > 32""")
        add("Data", "Display names > 32 chars", not rows,
            f"{len(rows)} row(s)",
            sql="""SELECT guild_id, user_id FROM users
WHERE display_name IS NOT NULL AND LENGTH(display_name) > 32""")

        rows = q("""SELECT guild_id, user_id FROM users
            WHERE username IS NOT NULL AND LENGTH(username) > 32""")
        add("Data", "Usernames > 32 chars", not rows,
            f"{len(rows)} row(s)",
            sql="""SELECT guild_id, user_id FROM users
WHERE username IS NOT NULL AND LENGTH(username) > 32""")

        rows = q("""SELECT lr.guild_id, lr.level, lr.role_id
            FROM level_roles lr
            LEFT JOIN guild_settings gs ON gs.guild_id = lr.guild_id
            WHERE gs.guild_id IS NULL""")
        add("Data", "Level roles without guild settings", not rows,
            f"{len(rows)} role(s)", fix="orphan_level_roles" if rows else None,
            sql="""SELECT lr.guild_id, lr.level, lr.role_id
FROM level_roles lr
LEFT JOIN guild_settings gs ON gs.guild_id = lr.guild_id
WHERE gs.guild_id IS NULL""")

        rows = q("""SELECT lr1.guild_id, lr1.level
            FROM level_roles lr1
            JOIN level_roles lr2 ON lr1.guild_id = lr2.guild_id AND lr1.level = lr2.level
            AND lr1.rowid != lr2.rowid""")
        add("Data", "Duplicate level roles", not rows,
            f"{len(rows)} duplicate(s)",
            sql="""SELECT lr1.guild_id, lr1.level
FROM level_roles lr1
JOIN level_roles lr2
  ON lr1.guild_id = lr2.guild_id AND lr1.level = lr2.level AND lr1.rowid != lr2.rowid""")

        rows = q("""SELECT gs.guild_id FROM guild_settings gs
            LEFT JOIN (SELECT DISTINCT guild_id FROM level_roles) lr ON lr.guild_id = gs.guild_id
            WHERE gs.level_channel_id IS NOT NULL AND gs.level_channel_id != 0
            AND lr.guild_id IS NULL""")
        add("Info", "Guilds with level channel but no level roles", True,
            f"{len(rows)} guild(s)",
            sql="""SELECT gs.guild_id FROM guild_settings gs
LEFT JOIN (SELECT DISTINCT guild_id FROM level_roles) lr ON lr.guild_id = gs.guild_id
WHERE gs.level_channel_id IS NOT NULL AND gs.level_channel_id != 0
  AND lr.guild_id IS NULL""")

        rows = q("SELECT guild_id FROM guild_settings WHERE qotd_enabled=1 AND (qotd_channel IS NULL OR qotd_channel=0)")
        add("Info", "QOTD enabled but no channel", not rows,
            f"{len(rows)} guild(s)",
            sql="SELECT guild_id FROM guild_settings\nWHERE qotd_enabled = 1 AND (qotd_channel IS NULL OR qotd_channel = 0)")

        rows = q("SELECT guild_id FROM guild_settings WHERE qotd_enabled=1 AND (qotd_role_id IS NULL OR qotd_role_id=0)")
        add("Info", "QOTD enabled but no role", not rows,
            f"{len(rows)} guild(s)",
            sql="SELECT guild_id FROM guild_settings\nWHERE qotd_enabled = 1 AND (qotd_role_id IS NULL OR qotd_role_id = 0)")

        rows = q("""SELECT guild_id, user_id FROM users
            WHERE vc_minutes > 0 AND vc_xp_minutes = 0""")
        add("Info", "Users with VC time but no VC XP", True,
            f"{len(rows)} row(s)",
            sql="SELECT guild_id, user_id FROM users\nWHERE vc_minutes > 0 AND vc_xp_minutes = 0")

        total_xp = q("SELECT COALESCE(SUM(total_xp),0) FROM users")[0][0]
        total_msgs_xp = q("SELECT COALESCE(SUM(total_messages_xp),0) FROM users")[0][0]
        if total_xp > 0:
            msg_ratio = round(total_msgs_xp / total_xp * 100, 1)
            add("Info", "Message XP share of total XP", True, f"{msg_ratio}%",
                sql="SELECT COALESCE(SUM(total_messages_xp),0) * 100.0 /\n     COALESCE(SUM(total_xp),0) AS msg_xp_pct\nFROM users")

        try:
            import subprocess
            r = subprocess.run(["systemctl", "is-active", "voidwave.service"],
                               capture_output=True, text=True, timeout=2)
            bot_active = r.stdout.strip() == "active"
        except Exception:
            bot_active = None
        add("Info", "Bot service running", bot_active,
            "voidwave.service" if bot_active is not None else "could not check",
            sql="systemctl is-active voidwave.service")

        try:
            r = subprocess.run(["systemctl", "is-active", "voidwave_website.service"],
                               capture_output=True, text=True, timeout=2)
            web_active = r.stdout.strip() == "active"
        except Exception:
            web_active = None
        add("Info", "Website service running", web_active,
            "voidwave_website.service" if web_active is not None else "could not check",
            sql="systemctl is-active voidwave_website.service")

        db_path = Path("database.db")
        if db_path.exists():
            db_kb = db_path.stat().st_size / 1024
            add("Info", "Database file size", db_kb < 102400,
                f"{db_kb:.1f} KB" + (" (large!)" if db_kb >= 102400 else ""),
                sql="-- File system check: stat database.db")

        rows = q("SELECT COUNT(*) c FROM admin_rate_limits")
        if rows and rows[0]["c"] > 0:
            add("Info", "Rate limit entries", True, f"{rows[0]['c']} tracked IP(s)",
                sql="SELECT COUNT(*) c FROM admin_rate_limits")

        rows = q("SELECT COUNT(*) c FROM admin_login_codes WHERE expires_at > ?", (int(time.time()),))
        if rows and rows[0]["c"] > 0:
            add("Info", "Pending 2FA codes", True, f"{rows[0]['c']} active",
                sql="SELECT COUNT(*) c FROM admin_login_codes\nWHERE expires_at > strftime('%s', 'now')")

        for suffix in ("-wal", "-shm"):
            p = Path("database.db" + suffix)
            if p.exists():
                add("Info", f"database.db{suffix} present", True, f"{p.stat().st_size/1024:.1f} KB",
                    sql=f"-- File system check: stat database.db{suffix}")
    finally:
        conn.close()
    return results


@admin_bp.route("/check")
def check():
    results = _run_checks()
    return render_template("admin_check.html", results=results)


@admin_bp.route("/check/fix/<kind>", methods=["POST"])
def check_fix(kind):
    conn = _db()
    changed = 0
    executed_sql = []
    try:
        cur = conn.cursor()
        if kind == "normalize":
            executed_sql.append(
                "SELECT guild_id, user_id, level, progress, out_of FROM users WHERE progress >= out_of"
            )
            rows = cur.execute(
                "SELECT guild_id, user_id, level, progress, out_of FROM users WHERE progress >= out_of"
            ).fetchall()
            for r in rows:
                level, progress, out_of = _normalize_progress(r["level"], r["progress"], r["out_of"])
                stmt = "UPDATE users SET level=%d, progress=%d, out_of=%d WHERE guild_id=%d AND user_id=%d" % (
                    level, progress, out_of, r["guild_id"], r["user_id"])
                executed_sql.append(stmt)
                cur.execute(
                    "UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?",
                    (level, progress, out_of, r["guild_id"], r["user_id"])
                )
                changed += 1
        elif kind == "negatives":
            executed_sql.append("""UPDATE users SET level=MAX(level,0), progress=MAX(progress,0),
                out_of=MAX(out_of,0), total_messages=MAX(total_messages,0),
                total_messages_xp=MAX(total_messages_xp,0), total_xp=MAX(total_xp,0),
                vc_minutes=MAX(vc_minutes,0), vc_xp_minutes=MAX(vc_xp_minutes,0)""")
            cur.execute("""UPDATE users SET level=MAX(level,0), progress=MAX(progress,0),
                out_of=MAX(out_of,0), total_messages=MAX(total_messages,0),
                total_messages_xp=MAX(total_messages_xp,0), total_xp=MAX(total_xp,0),
                vc_minutes=MAX(vc_minutes,0), vc_xp_minutes=MAX(vc_xp_minutes,0)""")
            changed = cur.rowcount
        elif kind == "out_of":
            executed_sql.append("UPDATE users SET out_of = 100 + level * 20 WHERE out_of <= 0")
            cur.execute("UPDATE users SET out_of = 100 + level * 20 WHERE out_of <= 0")
            changed = cur.rowcount
        elif kind == "nulls":
            for col, val in [("level", 0), ("progress", 0), ("out_of", 100),
                             ("total_messages", 0), ("total_messages_xp", 0), ("total_xp", 0),
                             ("vc_minutes", 0), ("vc_xp_minutes", 0)]:
                executed_sql.append(f"UPDATE users SET {col}={val} WHERE {col} IS NULL")
                cur.execute(f"UPDATE users SET {col}=? WHERE {col} IS NULL", (val,))
            executed_sql.append("DELETE FROM users WHERE user_id IS NULL OR guild_id IS NULL")
            cur.execute("DELETE FROM users WHERE user_id IS NULL OR guild_id IS NULL")
            changed = cur.rowcount
        elif kind == "empty":
            executed_sql.append("""DELETE FROM users
                WHERE level=0 AND total_xp=0 AND total_messages=0 AND vc_minutes=0 AND last_message=''""")
            cur.execute("""DELETE FROM users
                WHERE level=0 AND total_xp=0 AND total_messages=0 AND vc_minutes=0 AND last_message=''""")
            changed = cur.rowcount
        elif kind == "orphan_settings":
            executed_sql.append("""DELETE FROM guild_settings
                WHERE guild_id NOT IN (SELECT DISTINCT guild_id FROM users)""")
            cur.execute("""DELETE FROM guild_settings
                WHERE guild_id NOT IN (SELECT DISTINCT guild_id FROM users)""")
            changed = cur.rowcount
        elif kind == "expired_boosts":
            executed_sql.append("DELETE FROM vote_boosts WHERE expires_at <= ?" % int(time.time()))
            cur.execute("DELETE FROM vote_boosts WHERE expires_at <= ?", (int(time.time()),))
            changed = cur.rowcount
        elif kind == "orphan_level_roles":
            executed_sql.append("""DELETE FROM level_roles
                WHERE guild_id NOT IN (SELECT DISTINCT guild_id FROM guild_settings)""")
            cur.execute("""DELETE FROM level_roles
                WHERE guild_id NOT IN (SELECT DISTINCT guild_id FROM guild_settings)""")
            changed = cur.rowcount
        elif kind == "future_timestamps":
            executed_sql.append("""UPDATE users SET last_message = ''
                WHERE last_message != '' AND date(last_message) > date('now', 'localtime')""")
            cur.execute("""UPDATE users SET last_message = ''
                WHERE last_message != '' AND date(last_message) > date('now', 'localtime')""")
            changed = cur.rowcount
        else:
            abort(404)
        conn.commit()
        _clear_cache()
    finally:
        conn.close()

    session["last_fix_sql"] = "\n".join(executed_sql)
    session["last_fix_result"] = f"{kind}: {changed} row(s) affected"

    _log("CHECK FIX", f"kind={kind} rows={changed}")
    return redirect(url_for("admin.check", fixed=f"{kind}:{changed}"))


@admin_bp.route("/check/fix-sql")
def check_fix_sql():
    sql = session.get("last_fix_sql", "")
    result = session.get("last_fix_result", "")
    return jsonify({"sql": sql, "result": result})


# ---------------------------------------------------------------------------
# Bot Status
# ---------------------------------------------------------------------------

BOT_SERVICE = "voidwave.service"


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
    except Exception as e:
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


@admin_bp.route("/bot")
def bot_status():
    status = _service_status(BOT_SERVICE)
    logs = _service_logs(BOT_SERVICE, 80)
    return render_template("admin_bot.html", status=status, logs=logs, service=BOT_SERVICE)


@admin_bp.route("/bot/confirm/<action>")
def bot_confirm(action):
    if action not in ("stop", "restart"):
        abort(404)
    status = _service_status(BOT_SERVICE)
    return render_template("admin_bot_confirm.html", action=action, status=status, service=BOT_SERVICE)


@admin_bp.route("/bot/action/<action>", methods=["POST"])
def bot_action(action):
    if action not in ("start", "stop", "restart"):
        abort(404)

    confirm_text = request.form.get("confirm", "").strip()
    if action == "stop" and confirm_text.upper() != "STOP":
        return redirect(url_for("admin.bot_confirm", action="stop", err="Type STOP to confirm"))
    if action == "restart" and confirm_text.upper() != "RESTART":
        return redirect(url_for("admin.bot_confirm", action="restart", err="Type RESTART to confirm"))

    if action == "stop":
        ok, msg = _service_stop(BOT_SERVICE)
    elif action == "start":
        ok, msg = _service_start(BOT_SERVICE)
    else:
        ok, msg = _service_stop(BOT_SERVICE)
        if ok:
            ok, msg = _service_start(BOT_SERVICE)
            if ok:
                msg = f"Restarted {BOT_SERVICE}"

    _log("BOT ACTION", f"{action} -> {msg}")
    if ok:
        return redirect(url_for("admin.bot_status", msg=msg))
    return redirect(url_for("admin.bot_status", err=msg))


@admin_bp.route("/bot/logs")
def bot_logs():
    lines = _service_logs(BOT_SERVICE, 300)
    return jsonify({"lines": lines})


# ---------------------------------------------------------------------------
# Backups
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


@admin_bp.route("/backups")
def backups():
    items = _list_backups()
    return render_template("admin_backups.html", backups=items)


@admin_bp.route("/backups/create", methods=["POST"])
def backup_create():
    dst, err = _backup_current()
    if err:
        abort(500, description=err)
    removed = _prune_backups()
    _log("BACKUP CREATE", dst.name)
    return redirect(url_for("admin.backups", msg=f"Backup created: {dst.name} ({removed} pruned)"))


@admin_bp.route("/backups/<name>/restore", methods=["GET", "POST"])
def backup_restore(name):
    path = BACKUP_DIR / name
    if not path.exists() or not path.is_file():
        abort(404)

    bot_active = _service_active("voidwave.service")
    site_active = _service_active("voidwave_website.service")

    if request.method == "POST":
        confirm = (request.form.get("confirm") or "").strip()
        if not hmac.compare_digest(confirm, "RESTORE"):
            _log("RESTORE FAIL", "confirmation mismatch", name)
            return redirect(url_for("admin.backups", err="Confirmation must be exactly: RESTORE"))

        stop_bot = request.form.get("stop_bot") == "on"
        bot_stopped = request.form.get("bot_stopped") == "on"

        if not stop_bot and not bot_stopped:
            return redirect(
                url_for("admin.backup_restore", name=name,
                        err="You must either stop the bot or confirm it is already stopped.")
            )

        try:
            if stop_bot:
                ok, msg = _service_stop("voidwave.service")
                if not ok:
                    return redirect(url_for("admin.backup_restore", name=name, err=msg))
        except Exception as e:
            return redirect(url_for("admin.backup_restore", name=name, err=str(e)))

        dst, err = _backup_current(suffix="_prerestore")
        if err:
            _log("RESTORE FAIL", f"no safety backup: {err}")
            return redirect(url_for("admin.backup_restore", name=name, err=err))

        try:
            shutil.copy2(path, "database.db")
        except OSError as e:
            _log("RESTORE FAIL", f"copy error: {e}")
            return redirect(url_for("admin.backup_restore", name=name, err=f"Copy failed: {e}"))

        for suffix in ("-wal", "-shm"):
            p = Path("database.db" + suffix)
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

        _clear_cache()
        _log("RESTORE OK", f"from {name} (safety backup {dst.name})")

        restart_msg = None
        if stop_bot:
            ok, msg = _service_start("voidwave.service")
            restart_msg = msg if not ok else "Bot restarted."

        return render_template(
            "admin_backups.html",
            backups=_list_backups(),
            restore_done=f"Restored {name} from backup. Safety copy: {dst.name}.",
            restart_msg=restart_msg,
        )

    return render_template(
        "admin_backups.html",
        backups=_list_backups(),
        restore_target=name,
        bot_active=bot_active,
        site_active=site_active,
    )


@admin_bp.route("/backups/<name>/delete", methods=["POST"])
def backup_delete(name):
    confirm = (request.form.get("confirm") or "").strip()
    if not hmac.compare_digest(confirm, "DELETE"):
        return redirect(url_for("admin.backups", err="Confirmation must be exactly: DELETE"))

    path = BACKUP_DIR / name
    if path.exists() and path.is_file():
        try:
            path.unlink()
            _log("BACKUP DELETE", name)
            return redirect(url_for("admin.backups", msg=f"Deleted backup {name}"))
        except OSError as e:
            return redirect(url_for("admin.backups", err=str(e)))
    return redirect(url_for("admin.backups", err="Backup not found"))


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


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

@admin_bp.route("/stats")
def stats():
    conn = _db()
    try:
        def scalar(sql, params=()):
            r = conn.execute(sql, params).fetchone()
            return r[0] if r else 0

        def percentile(field, pct):
            r = conn.execute(f"""
                SELECT {field} v FROM users ORDER BY {field} DESC
                LIMIT 1 OFFSET (SELECT CAST(COUNT(*) * {pct} AS INT) FROM users)
            """).fetchone()
            return r["v"] if r else 0

        total = scalar("SELECT COUNT(*) FROM users")
        agg = {
            "users": total,
            "guilds": scalar("SELECT COUNT(DISTINCT guild_id) FROM users"),
            "total_xp": scalar("SELECT COALESCE(SUM(total_xp),0) FROM users"),
            "total_messages": scalar("SELECT COALESCE(SUM(total_messages),0) FROM users"),
            "total_messages_xp": scalar("SELECT COALESCE(SUM(total_messages_xp),0) FROM users"),
            "vc_minutes": scalar("SELECT COALESCE(SUM(vc_minutes),0) FROM users"),
            "vc_xp_minutes": scalar("SELECT COALESCE(SUM(vc_xp_minutes),0) FROM users"),
            "avg_level": round(scalar("SELECT COALESCE(AVG(level),0) FROM users"), 2),
            "avg_xp": round(scalar("SELECT COALESCE(AVG(total_xp),0) FROM users"), 2),
            "avg_messages": round(scalar("SELECT COALESCE(AVG(total_messages),0) FROM users"), 2),
            "avg_vc": round(scalar("SELECT COALESCE(AVG(vc_minutes),0) FROM users"), 2),
            "max_level": scalar("SELECT COALESCE(MAX(level),0) FROM users"),
            "max_xp": scalar("SELECT COALESCE(MAX(total_xp),0) FROM users"),
            "max_messages": scalar("SELECT COALESCE(MAX(total_messages),0) FROM users"),
            "max_vc": scalar("SELECT COALESCE(MAX(vc_minutes),0) FROM users"),
            "median_level": percentile("level", 0.5),
            "p90_level": percentile("level", 0.1),
            "p10_level": percentile("level", 0.9),
            "level_100": scalar("SELECT COUNT(*) FROM users WHERE level >= 100"),
            "level_50": scalar("SELECT COUNT(*) FROM users WHERE level >= 50"),
            "level_20": scalar("SELECT COUNT(*) FROM users WHERE level >= 20"),
            "level_10": scalar("SELECT COUNT(*) FROM users WHERE level >= 10"),
            "level_5": scalar("SELECT COUNT(*) FROM users WHERE level >= 5"),
            "xp_per_user": 0,
            "msgs_per_user": 0,
            "vc_per_user": 0,
            "zero_level": scalar("SELECT COUNT(*) FROM users WHERE level = 0"),
            "total_vc_hours": 0,
        }
        agg["xp_per_user"] = round(agg["total_xp"] / total, 2) if total else 0
        agg["msgs_per_user"] = round(agg["total_messages"] / total, 2) if total else 0
        agg["vc_per_user"] = round(agg["vc_minutes"] / total, 2) if total else 0
        agg["total_vc_hours"] = round(agg["vc_minutes"] / 60, 1)

        active = {}
        for label, days in (("24h", 1), ("7d", 7), ("30d", 30)):
            ts = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            active[label] = scalar(
                "SELECT COUNT(*) FROM users WHERE last_message != '' AND last_message >= ?",
                (ts,)
            )

        level_buckets = []
        bounds = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 10),
                  (11, 15), (16, 20), (21, 30), (31, 40), (41, 50), (51, None)]
        for lo, hi in bounds:
            if hi is None:
                n = scalar("SELECT COUNT(*) FROM users WHERE level >= ?", (lo,))
            elif lo == hi:
                n = scalar("SELECT COUNT(*) FROM users WHERE level = ?", (lo,))
            else:
                n = scalar("SELECT COUNT(*) FROM users WHERE level BETWEEN ? AND ?", (lo, hi))
            label = f"Lvl {lo}" if lo == hi else (f"Lvl {lo}-{hi}" if hi else f"Lvl {lo}+")
            level_buckets.append({"range": label, "count": n})

        guild_rows = conn.execute("""
            SELECT guild_id, COUNT(*) users, COALESCE(SUM(total_xp),0) xp,
                   COALESCE(SUM(total_messages),0) msgs,
                   COALESCE(SUM(vc_minutes),0) vc,
                   COALESCE(AVG(level),0) avg_level,
                   COALESCE(MAX(level),0) max_level
            FROM users GROUP BY guild_id ORDER BY users DESC LIMIT 50
        """).fetchall()

        def top(field, n=10):
            rows = conn.execute(
                f"SELECT * FROM users ORDER BY {field} DESC LIMIT ?", (n,)
            ).fetchall()
            return [dict(r) for r in rows]

        boost_rows = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END),0) active, "
            "COALESCE(SUM(CASE WHEN expires_at <= ? THEN 1 ELSE 0 END),0) expired "
            "FROM vote_boosts", (int(time.time()), int(time.time()))
        ).fetchone()

        bot_rows = conn.execute("SELECT * FROM bot_stats").fetchall()

        top_xp = top("total_xp")
        top_messages = top("total_messages")
        top_vc = top("vc_minutes")
        top_level = top("level")

        guild_settings_count = scalar("SELECT COUNT(*) FROM guild_settings")
        level_roles_count = scalar("SELECT COUNT(*) FROM level_roles")

        xp_distribution = []
        xp_bounds = [(0, 0), (1, 49), (50, 99), (100, 249), (250, 499),
                     (500, 999), (1000, 4999), (5000, 9999), (10000, 49999),
                     (50000, 99999), (100000, None)]
        xp_labels = ["0", "1-49", "50-99", "100-249", "250-499",
                     "500-999", "1K-5K", "5K-10K", "10K-50K", "50K-100K", "100K+"]
        for (lo, hi), label in zip(xp_bounds, xp_labels):
            if hi is None:
                n = scalar("SELECT COUNT(*) FROM users WHERE total_xp >= ?", (lo,))
            elif lo == hi:
                n = scalar("SELECT COUNT(*) FROM users WHERE total_xp = ?", (lo,))
            else:
                n = scalar("SELECT COUNT(*) FROM users WHERE total_xp BETWEEN ? AND ?", (lo, hi))
            xp_distribution.append({"range": label, "count": n})

    finally:
        conn.close()

    snapshots = []
    try:
        with open("stats_history.json", "r") as f:
            snapshots = json.load(f)[-30:]
    except Exception:
        snapshots = []

    snap_deltas = []
    prev = None
    for s in snapshots:
        row = {"ts": s.get("timestamp"), "users": s.get("total_users"),
               "xp": s.get("total_xp"), "messages": s.get("total_messages"),
               "vc": s.get("total_vc_minutes"), "guilds": s.get("total_guilds")}
        if prev:
            row["d_users"] = row["users"] - prev["users"]
            row["d_xp"] = row["xp"] - prev["xp"]
            row["d_messages"] = row["messages"] - prev["messages"]
            row["d_vc"] = row["vc"] - prev["vc"] if row["vc"] and prev["vc"] else None
        else:
            row["d_users"] = row["d_xp"] = row["d_messages"] = row["d_vc"] = None
        snap_deltas.append(row)
        prev = row

    db_size = Path("database.db").stat().st_size if Path("database.db").exists() else 0
    wal_size = 0
    if Path("database.db-wal").exists():
        wal_size = Path("database.db-wal").stat().st_size

    return render_template(
        "admin_stats.html",
        agg=agg,
        active=active,
        level_buckets=level_buckets,
        xp_distribution=xp_distribution,
        guild_rows=guild_rows,
        top_xp=top_xp,
        top_messages=top_messages,
        top_vc=top_vc,
        top_level=top_level,
        boost_rows=dict(boost_rows) if boost_rows else {"c": 0, "active": 0, "expired": 0},
        bot_rows=[dict(r) for r in bot_rows],
        snap_deltas=snap_deltas,
        db_size=db_size,
        wal_size=wal_size,
        guild_settings_count=guild_settings_count,
        level_roles_count=level_roles_count,
    )


# ---------------------------------------------------------------------------
# Guild Settings
# ---------------------------------------------------------------------------

GUILD_SETTING_FIELDS = {
    "level_channel_id": "int",
    "level_channel_enabled": "bool",
    "qotd_enabled": "bool",
    "qotd_channel": "int",
    "qotd_role_id": "int",
    "delete_old_qotd": "bool",
}

LEVEL_ROLE_FIELDS = {
    "level": "int",
    "role_id": "int",
}


@admin_bp.route("/guilds")
def guilds():
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "users")
    order = request.args.get("order", "desc")
    page = max(1, request.args.get("page", 1, type=int))
    per = 25

    valid_sorts = {"guild_id", "users", "xp", "avg_level", "settings"}
    if sort not in valid_sorts:
        sort = "users"
    dir_sql = "ASC" if order == "asc" else "DESC"

    conn = _db()
    try:
        rows = conn.execute("""
            SELECT
                u.guild_id,
                COUNT(DISTINCT u.user_id) AS users,
                COALESCE(SUM(u.total_xp), 0) AS xp,
                COALESCE(SUM(u.total_messages), 0) AS msgs,
                COALESCE(SUM(u_vc.vc_minutes_sum), 0) AS vc,
                ROUND(COALESCE(AVG(u.level), 0), 1) AS avg_level,
                COALESCE(MAX(u.level), 0) AS max_level,
                CASE WHEN gs.guild_id IS NOT NULL THEN 1 ELSE 0 END AS has_settings,
                gs.level_channel_enabled,
                gs.qotd_enabled
            FROM (SELECT DISTINCT guild_id, user_id, total_xp, total_messages, level FROM users) u
            LEFT JOIN (
                SELECT guild_id, SUM(vc_minutes) AS vc_minutes_sum
                FROM users GROUP BY guild_id
            ) u_vc ON u_vc.guild_id = u.guild_id
            LEFT JOIN guild_settings gs ON gs.guild_id = u.guild_id
            GROUP BY u.guild_id
        """).fetchall()

        if q and q.isdigit() and len(q) >= 8:
            rows = [r for r in rows if str(r["guild_id"]) == q]
        elif q:
            like = f"%{q}%"
            rows = [r for r in rows if q in str(r["guild_id"])]

        sort_map = {"guild_id": "guild_id", "users": "users", "xp": "xp",
                    "avg_level": "avg_level", "settings": "has_settings"}
        rows = [dict(r) for r in rows]
        rows = sorted(rows, key=lambda r: r.get(sort_map.get(sort, "users"), 0),
                      reverse=(order == "desc"))

        total = len(rows)
        total_pages = max(1, (total + per - 1) // per)
        page_rows = rows[(page - 1) * per: page * per]
    finally:
        conn.close()

    return render_template(
        "admin_guilds.html",
        rows=page_rows,
        total=total,
        q=q,
        sort=sort,
        order=order,
        page=page,
        total_pages=total_pages,
    )


@admin_bp.route("/guilds/<int:guild_id>", methods=["GET", "POST"])
def guild_edit(guild_id):
    conn = _db()
    try:
        settings = conn.execute(
            "SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,)
        ).fetchone()

        level_roles = conn.execute(
            "SELECT * FROM level_roles WHERE guild_id=? ORDER BY level", (guild_id,)
        ).fetchall()

        user_count = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE guild_id=?", (guild_id,)
        ).fetchone()["c"]

        total_xp = conn.execute(
            "SELECT COALESCE(SUM(total_xp),0) FROM users WHERE guild_id=?", (guild_id,)
        ).fetchone()[0]

        total_msgs = conn.execute(
            "SELECT COALESCE(SUM(total_messages),0) FROM users WHERE guild_id=?", (guild_id,)
        ).fetchone()[0]

        flash_msg = None
        error = None

        if request.method == "POST":
            action = request.form.get("action", "save_settings")

            if action == "save_settings":
                if not settings:
                    conn.execute(
                        "INSERT INTO guild_settings (guild_id) VALUES (?)", (guild_id,)
                    )
                    conn.commit()
                    settings = conn.execute(
                        "SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,)
                    ).fetchone()

                for field, ftype in GUILD_SETTING_FIELDS.items():
                    raw = request.form.get(field, "")
                    if ftype == "int":
                        if raw == "" or raw is None:
                            val = None
                        else:
                            try:
                                val = int(raw)
                            except ValueError:
                                val = None
                        conn.execute(
                            f"UPDATE guild_settings SET {field}=? WHERE guild_id=?",
                            (val, guild_id)
                        )
                    elif ftype == "bool":
                        val = 1 if raw == "on" or raw == "1" else 0
                        conn.execute(
                            f"UPDATE guild_settings SET {field}=? WHERE guild_id=?",
                            (val, guild_id)
                        )
                conn.commit()
                _clear_cache()
                _log("GUILD SETTINGS EDIT", f"guild={guild_id}")
                flash_msg = "Guild settings saved."

            elif action == "add_role":
                try:
                    level = int(request.form.get("level", 0))
                    role_id = int(request.form.get("role_id", 0))
                except (TypeError, ValueError):
                    error = "Invalid level or role ID."
                else:
                    if level < 0 or role_id < 1000000000000:
                        error = "Level must be >= 0 and role ID must be a valid Discord ID."
                    else:
                        conn.execute("""
                            INSERT INTO level_roles (guild_id, level, role_id)
                            VALUES (?, ?, ?)
                            ON CONFLICT(guild_id, level) DO UPDATE SET role_id=excluded.role_id
                        """, (guild_id, level, role_id))
                        conn.commit()
                        _log("LEVEL ROLE ADD", f"guild={guild_id} level={level} role={role_id}")
                        flash_msg = f"Level role added: level {level} -> role {role_id}."

            elif action == "delete_role":
                try:
                    level = int(request.form.get("level", -1))
                except (TypeError, ValueError):
                    error = "Invalid level."
                else:
                    conn.execute(
                        "DELETE FROM level_roles WHERE guild_id=? AND level=?",
                        (guild_id, level)
                    )
                    conn.commit()
                    _log("LEVEL ROLE DELETE", f"guild={guild_id} level={level}")
                    flash_msg = f"Level role at level {level} removed."

            settings = conn.execute(
                "SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,)
            ).fetchone()
            level_roles = conn.execute(
                "SELECT * FROM level_roles WHERE guild_id=? ORDER BY level", (guild_id,)
            ).fetchall()
    finally:
        conn.close()

    return render_template(
        "admin_guild_edit.html",
        guild_id=guild_id,
        settings=settings,
        level_roles=level_roles,
        user_count=user_count,
        total_xp=total_xp,
        total_msgs=total_msgs,
        flash_msg=flash_msg,
        error=error,
    )


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

@admin_bp.route("/logs")
def logs():
    q = (request.args.get("q") or "").strip().lower()
    page = max(1, request.args.get("page", 1, type=int))
    per = 100

    lines = _read_log_lines()[::-1]
    if q:
        lines = [ln for ln in lines if q in ln.lower()]

    total = len(lines)
    total_pages = max(1, (total + per - 1) // per)
    chunk = lines[(page - 1) * per: page * per]

    return render_template(
        "admin_logs.html",
        lines=chunk,
        total=total,
        q=q,
        page=page,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# JSON API (read-only convenience)
# ---------------------------------------------------------------------------

@admin_bp.route("/api/health")
def api_health():
    checks = _run_checks()
    return jsonify({
        "ok": all(c["ok"] for c in checks),
        "results": checks,
    })


@admin_bp.route("/api/users/search")
def api_user_search():
    q = (request.args.get("q") or "").strip()
    conn = _db()
    try:
        if q.isdigit() and len(q) >= 8:
            rows = conn.execute(
                "SELECT guild_id, user_id, username, display_name, level, total_xp "
                "FROM users WHERE user_id=? OR guild_id=? LIMIT 50",
                (int(q), int(q))
            ).fetchall()
        elif q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT guild_id, user_id, username, display_name, level, total_xp "
                "FROM users WHERE username LIKE ? OR display_name LIKE ? LIMIT 50",
                (like, like)
            ).fetchall()
        else:
            rows = []
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()
