import time

from flask import render_template, request, redirect, url_for, flash

from . import admin_bp
from .helpers import _db, _log, _log_event
from .constants import BLOCK_FEATURES


def _known_user(conn, user_id):
    return conn.execute(
        "SELECT display_name, username, COUNT(*) AS guild_count, SUM(total_xp) AS total_xp, "
        "MAX(avatar_hash) AS avatar_hash "
        "FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()


def _avatar_url(user_id, avatar_hash):
    if avatar_hash:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=64"
    return "https://cdn.discordapp.com/embed/avatars/0.png"


def _user_blocks(conn, user_id):
    rows = conn.execute(
        "SELECT feature, blocked_at FROM user_blocks WHERE user_id=?", (user_id,)
    ).fetchall()
    return {r["feature"]: r["blocked_at"] for r in rows}


def _format_blocks(raw):
    return [
        {
            "feature": feature,
            "since": time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "",
        }
        for feature, ts in sorted(raw.items())
    ]


@admin_bp.route("/blocks")
def blocks():
    q = (request.args.get("q") or "").strip()

    conn = _db()
    try:
        if q:
            like = f"%{q}%"
            known = conn.execute(
                "SELECT user_id, MAX(COALESCE(NULLIF(display_name,''), NULLIF(username,''), user_id)) AS name, "
                "COUNT(DISTINCT guild_id) AS guild_count "
                "FROM users WHERE CAST(user_id AS TEXT)=? OR username LIKE ? OR display_name LIKE ? "
                "GROUP BY user_id ORDER BY name LIMIT 25",
                (q, like, like)
            ).fetchall()
        else:
            known = conn.execute(
                "SELECT user_id, MAX(COALESCE(NULLIF(display_name,''), NULLIF(username,''), user_id)) AS name, "
                "COUNT(DISTINCT guild_id) AS guild_count "
                "FROM users GROUP BY user_id ORDER BY SUM(total_xp) DESC LIMIT 100"
            ).fetchall()

        blocked = conn.execute(
            "SELECT ub.user_id, GROUP_CONCAT(ub.feature) AS features, MIN(ub.blocked_at) AS blocked_at, "
            "COALESCE(NULLIF(MAX(u.display_name),''), NULLIF(MAX(u.username),''), CAST(ub.user_id AS TEXT)) AS name "
            "FROM user_blocks ub LEFT JOIN users u ON u.user_id = ub.user_id "
            "GROUP BY ub.user_id ORDER BY ub.user_id"
        ).fetchall()
    finally:
        conn.close()

    blocked_rows = [
        {
            "user_id": b["user_id"],
            "name": b["name"],
            "features": sorted(b["features"].split(",")),
            "since": time.strftime("%Y-%m-%d %H:%M", time.localtime(b["blocked_at"])) if b["blocked_at"] else "",
        }
        for b in blocked
    ]

    return render_template(
        "admin_blocks.html",
        known=known,
        blocked=blocked_rows,
        features=BLOCK_FEATURES,
        q=q,
        now=time.time(),
    )


@admin_bp.route("/blocks/lookup", methods=["POST"])
def blocks_lookup():
    raw = (request.form.get("user_id") or "").strip()
    if not raw.isdigit():
        flash("Enter a numeric Discord user ID.", "error")
        return redirect(url_for("admin.blocks"))
    return redirect(url_for("admin.block_user", user_id=int(raw)))


@admin_bp.route("/blocks/<int:user_id>", methods=["GET", "POST"])
def block_user(user_id):
    conn = _db()
    try:
        user = _known_user(conn, user_id)

        if request.method == "POST":
            chosen = [f for f in (request.form.getlist("features")) if f in BLOCK_FEATURES]

            conn.execute("DELETE FROM user_blocks WHERE user_id=?", (user_id,))
            for feature in chosen:
                conn.execute(
                    "INSERT OR REPLACE INTO user_blocks (user_id, feature, blocked_at) VALUES (?, ?, ?)",
                    (user_id, feature, int(time.time()))
                )
            conn.commit()

            _log("USER BLOCKS", f"user={user_id} features={chosen or 'none'}")
            _log_event("block_update", f"features={chosen or 'none'}", user_id=user_id)
            flash(f"Updated blocks for {user_id}: {', '.join(chosen) if chosen else 'nothing blocked'}.", "success")

            user = _known_user(conn, user_id)
            current_blocks = _format_blocks(_user_blocks(conn, user_id))
            form_saved = True
        else:
            current_blocks = _format_blocks(_user_blocks(conn, user_id))
            form_saved = False

        guild_rows = conn.execute(
            "SELECT DISTINCT guild_id FROM users WHERE user_id=? LIMIT 10",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    return render_template(
        "admin_block_user.html",
        user_id=user_id,
        user=user,
        avatar_url=_avatar_url(user_id, user["avatar_hash"]) if user else None,
        guild_rows=guild_rows,
        current_blocks=current_blocks,
        features=BLOCK_FEATURES,
        saved=form_saved,
        not_known=user is None,
    )
