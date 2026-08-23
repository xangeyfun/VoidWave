from flask import jsonify, request

from . import admin_bp
from .helpers import _db
from .health import _run_checks


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
                "SELECT guild_id, user_id, username, display_name, level, total_xp, "
                "avatar_hash FROM users WHERE user_id=? OR guild_id=? LIMIT 50",
                (int(q), int(q))
            ).fetchall()
        elif q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT guild_id, user_id, username, display_name, level, total_xp, "
                "avatar_hash FROM users WHERE username LIKE ? OR display_name LIKE ? LIMIT 50",
                (like, like)
            ).fetchall()
        else:
            rows = []
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@admin_bp.route("/api/guilds/lookup")
def api_guild_lookup():
    q = (request.args.get("q") or "").strip()
    if not (q.isdigit() and len(q) >= 8):
        return jsonify(None)
    gid = int(q)
    conn = _db()
    try:
        stats = conn.execute(
            "SELECT COUNT(*) AS users, COALESCE(SUM(total_xp),0) AS xp, "
            "MAX(last_message) AS last_message FROM users WHERE guild_id=?",
            (gid,)
        ).fetchone()
        roles = conn.execute(
            "SELECT COUNT(*) c FROM level_roles WHERE guild_id=?", (gid,)
        ).fetchone()["c"]
        settings = conn.execute(
            "SELECT qotd_enabled, qotd_time, qotd_tz, level_channel_enabled FROM guild_settings WHERE guild_id=?",
            (gid,)
        ).fetchone()
        if not settings and not stats["users"] and not roles:
            return jsonify(None)
        return jsonify({
            "guild_id": str(gid),
            "users": stats["users"],
            "xp": stats["xp"],
            "last_message": stats["last_message"],
            "level_roles": roles,
            "qotd_enabled": bool(settings["qotd_enabled"]) if settings else False,
            "qotd_time": settings["qotd_time"] if settings else None,
            "level_channel": bool(settings["level_channel_enabled"]) if settings else False,
        })
    finally:
        conn.close()
