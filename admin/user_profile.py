import time

from flask import render_template

from . import admin_bp
from .helpers import _db


@admin_bp.route("/user/<int:user_id>")
def user_profile(user_id):
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT * FROM users WHERE user_id=? ORDER BY total_xp DESC",
            (user_id,)
        ).fetchall()

        if not rows:
            return render_template("admin_user_profile.html", user_id=user_id, guilds=[], boost=None, not_found=True)

        boost = conn.execute(
            "SELECT multiplier, expires_at FROM vote_boosts WHERE user_id=?",
            (user_id,)
        ).fetchone()

        display_name = rows[0]["display_name"] or rows[0]["username"] or str(user_id)
        username = rows[0]["username"] or ""

        guilds = []
        total_xp = 0
        total_messages = 0
        total_vc = 0
        max_level = 0
        for r in rows:
            guilds.append(dict(r))
            total_xp += r["total_xp"] or 0
            total_messages += r["total_messages"] or 0
            total_vc += r["vc_minutes"] or 0
            max_level = max(max_level, r["level"] or 0)

        now_ts = int(time.time())
        return render_template(
            "admin_user_profile.html",
            user_id=user_id,
            display_name=display_name,
            username=username,
            guilds=guilds,
            boost=dict(boost) if boost else None,
            total_xp=total_xp,
            total_messages=total_messages,
            total_vc=total_vc,
            max_level=max_level,
            not_found=False,
            now_ts=now_ts,
        )
    finally:
        conn.close()
