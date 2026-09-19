import time
from datetime import datetime, timedelta
from pathlib import Path

from flask import flash, jsonify, redirect, render_template, request, url_for

from . import admin_bp
from .health import _run_checks
from .helpers import (
    _bot_status,
    _clear_cache,
    _db,
    _list_backups,
    _log,
    _parse_log_line,
    _read_log_lines,
    _stale_users,
)

_AGG_TTL = 15.0
_agg_cache = {"ts": 0.0, "data": None}


def _dashboard_data():
    import time as _t
    now_cache = _t.time()
    if _agg_cache["data"] is not None and now_cache - _agg_cache["ts"] < _AGG_TTL:
        return _agg_cache["data"]

    conn = _db()
    try:
        def scalar(sql, params=()):
            r = conn.execute(sql, params).fetchone()
            return r[0] if r else 0

        now_ts = int(time.time())
        day = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

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
                "SELECT COUNT(*) FROM users WHERE last_message != '' AND last_message >= ?",
                (day,)
            ),
            "active_7d": scalar(
                "SELECT COUNT(*) FROM users WHERE last_message != '' AND last_message >= ?",
                (week,)
            ),
            "total_vc_hours": round(scalar("SELECT COALESCE(SUM(vc_minutes),0) FROM users") / 60, 1),
        }
        data["avg_level"] = round(data["avg_level"], 2)
    finally:
        conn.close()

    _agg_cache["ts"] = now_cache
    _agg_cache["data"] = data
    return data


@admin_bp.route("/")
def dashboard():
    data = _dashboard_data()
    conn = _db()
    try:
        def scalar(sql, params=()):
            r = conn.execute(sql, params).fetchone()
            return r[0] if r else 0

        ratings = {
            "total": scalar("SELECT COUNT(*) FROM user_ratings"),
            "avg": round(scalar("SELECT COALESCE(AVG(rating),0) FROM user_ratings"), 1),
        }
        ratings["distribution"] = {star: 0 for star in range(1, 6)}
        for r in conn.execute("SELECT rating, COUNT(*) c FROM user_ratings GROUP BY rating"):
            if 1 <= r["rating"] <= 5:
                ratings["distribution"][r["rating"]] = r["c"]
        ratings["recent"] = [dict(r) for r in conn.execute("""
            SELECT r.id AS rating_id, r.user_id, u.display_name, u.username, u.avatar_hash,
                   r.rating, r.feedback, r.guild_name, r.created_at
            FROM user_ratings r
            LEFT JOIN users u ON u.user_id = r.user_id
            GROUP BY r.id
            ORDER BY r.id DESC LIMIT 8
        """).fetchall()]

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
    backup_age_hours = None
    backup_stale = False
    if latest_backup:
        backup_age_hours = round((datetime.now() - latest_backup["mtime"]).total_seconds() / 3600, 1)
        backup_stale = backup_age_hours > 7 * 24

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
        backup_age_hours=backup_age_hours,
        backup_stale=backup_stale,
        db_size=db_size,
        wal_size=wal_size,
        bot_alive=bot_alive,
        recent_actions=recent_actions,
        stale_users=stale,
        ratings=ratings,
    )


@admin_bp.route("/api/dashboard")
def api_dashboard():
    data = _dashboard_data()
    return jsonify({
        "users": data["users"],
        "guilds": data["guilds"],
        "total_xp": data["total_xp"],
        "total_messages": data["total_messages"],
        "vc_minutes": data["vc_minutes"],
        "total_vc_hours": data["total_vc_hours"],
        "avg_level": data["avg_level"],
        "max_level": data["max_level"],
        "active_boosts": data["active_boosts"],
        "active_24h": data["active_24h"],
        "active_7d": data["active_7d"],
        "bot_alive": _bot_status(),
    })


@admin_bp.route("/ratings/<int:rating_id>/delete", methods=["POST"])
def rating_delete(rating_id):
    conn = _db()
    removed = 0
    try:
        row = conn.execute(
            "SELECT user_id FROM user_ratings WHERE id=?", (rating_id,)
        ).fetchone()
        if row:
            removed = conn.execute("DELETE FROM user_ratings WHERE id=?", (rating_id,)).rowcount
            conn.commit()
            _clear_cache()
            _log("RATING DELETE", f"id={rating_id} user={row['user_id']}")
    finally:
        conn.close()

    if removed:
        flash(f"Deleted rating #{rating_id}.", "success")
    else:
        flash(f"Rating #{rating_id} not found.", "error")
    return redirect(request.referrer or url_for("admin.dashboard"))
