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
