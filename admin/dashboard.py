import time
from pathlib import Path

from flask import jsonify, render_template, request, flash, redirect, url_for

from . import admin_bp
from .helpers import (
    _db, _read_log_lines, _parse_log_line, _list_backups, _bot_status, _stale_users,
    _clear_cache, _log,
)
from .health import _run_checks


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
            "guilds": scalar("""
                SELECT COUNT(*) FROM (
                    SELECT DISTINCT guild_id FROM users
                    UNION
                    SELECT guild_id FROM guild_settings
                )
            """),
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

        ratings = {
            "total": scalar("SELECT COUNT(*) FROM user_ratings"),
            "avg": round(scalar("SELECT COALESCE(AVG(rating),0) FROM user_ratings"), 1),
        }
        ratings["distribution"] = {star: 0 for star in range(1, 6)}
        for r in conn.execute("SELECT rating, COUNT(*) c FROM user_ratings GROUP BY rating"):
            if 1 <= r["rating"] <= 5:
                ratings["distribution"][r["rating"]] = r["c"]
        ratings["recent"] = [dict(r) for r in conn.execute(
            "SELECT * FROM user_ratings ORDER BY id DESC LIMIT 10").fetchall()]

        recent_logs = _read_log_lines()[-8:][::-1]
        recent_actions = [
            {"ts": e["ts"], "action": e["action"], "detail": e["detail"][:60]}
            for e in (_parse_log_line(line) for line in recent_logs)
        ]
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

    stale = _stale_users(30)

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
        stale_users=stale,
        ratings=ratings,
    )


@admin_bp.route("/api/dashboard")
def api_dashboard():
    conn = _db()
    try:
        def scalar(sql, params=()):
            r = conn.execute(sql, params).fetchone()
            return r[0] if r else 0

        now_ts = int(time.time())
        day = now_ts - 86400
        week = now_ts - 604800

        users = scalar("SELECT COUNT(*) FROM users")
        total_xp = scalar("SELECT COALESCE(SUM(total_xp),0) FROM users")
        total_vc_minutes = scalar("SELECT COALESCE(SUM(vc_minutes),0) FROM users")

        return jsonify({
            "users": users,
            "guilds": scalar("""
                SELECT COUNT(*) FROM (
                    SELECT DISTINCT guild_id FROM users
                    UNION
                    SELECT guild_id FROM guild_settings
                )
            """),
            "total_xp": total_xp,
            "total_messages": scalar("SELECT COALESCE(SUM(total_messages),0) FROM users"),
            "vc_minutes": total_vc_minutes,
            "total_vc_hours": round(total_vc_minutes / 60, 1),
            "avg_level": round(scalar("SELECT COALESCE(AVG(level),0) FROM users"), 2),
            "max_level": scalar("SELECT COALESCE(MAX(level),0) FROM users"),
            "active_boosts": scalar("SELECT COUNT(*) FROM vote_boosts WHERE expires_at > ?", (now_ts,)),
            "active_24h": scalar(
                "SELECT COUNT(*) FROM users WHERE last_message != '' AND datetime(last_message) > datetime(?, 'unixepoch')",
                (day,)
            ),
            "active_7d": scalar(
                "SELECT COUNT(*) FROM users WHERE last_message != '' AND datetime(last_message) > datetime(?, 'unixepoch')",
                (week,)
            ),
            "bot_alive": _bot_status(),
        })
    finally:
        conn.close()


@admin_bp.route("/ratings/<int:rating_id>/delete", methods=["POST"])
def rating_delete(rating_id):
    conn = _db()
    try:
        cur = conn.execute("DELETE FROM user_ratings WHERE id=?", (rating_id,))
        removed = cur.rowcount
        conn.commit()
        _clear_cache()
    finally:
        conn.close()

    _log("RATING DELETE", f"rating={rating_id} rows={removed}")
    if removed:
        flash(f"Deleted rating #{rating_id}.", "success")
    else:
        flash(f"Rating #{rating_id} not found.", "error")
    return redirect(url_for("admin.dashboard"))
