import time

from flask import render_template, request, redirect, url_for, flash

from . import admin_bp
from .helpers import _db, _log, _log_event
from .constants import BLOCK_FEATURES, BLOCK_DURATIONS, VALID_BLOCK_DURATIONS


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
    return conn.execute(
        "SELECT feature, blocked_at, expires_at, note FROM user_blocks WHERE user_id=? ORDER BY feature",
        (user_id,)
    ).fetchall()


def _humanize_remaining(seconds):
    if seconds >= 86400:
        value = seconds / 86400
        unit = "day"
    elif seconds >= 3600:
        value = seconds / 3600
        unit = "hour"
    else:
        value = seconds / 60
        unit = "minute"
    rounded = round(value)
    return f"{rounded} {unit}{'s' if rounded != 1 else ''}"


def _format_blocks(rows):
    now = time.time()
    out = []
    for r in rows:
        expires_at = r["expires_at"]
        expired = False
        if expires_at is None:
            expires_label = "Permanent"
        elif expires_at <= now:
            expired = True
            expires_label = "expired"
        else:
            expires_label = f"expires in {_humanize_remaining(expires_at - now)}"
        out.append({
            "feature": r["feature"],
            "since": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["blocked_at"])) if r["blocked_at"] else "",
            "expired": expired,
            "expires_label": expires_label,
            "note": r["note"] or "",
        })
    return out


@admin_bp.route("/blocks")
def blocks():
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT ub.user_id, ub.feature, ub.blocked_at, ub.expires_at, ub.note, "
            "COALESCE(NULLIF(u.display_name,''), NULLIF(u.username,''), CAST(ub.user_id AS TEXT)) AS name "
            "FROM user_blocks ub LEFT JOIN users u ON u.user_id = ub.user_id "
            "ORDER BY ub.user_id, ub.feature"
        ).fetchall()
    finally:
        conn.close()

    grouped = {}
    for r in rows:
        entry = grouped.setdefault(r["user_id"], {"user_id": r["user_id"], "name": r["name"], "blocks": []})
        formatted = _format_blocks([r])[0]
        entry["blocks"].append(formatted)

    blocked_rows = list(grouped.values())

    return render_template(
        "admin_blocks.html",
        blocked=blocked_rows,
        features=BLOCK_FEATURES,
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
            chosen = [f for f in request.form.getlist("features") if f in BLOCK_FEATURES]
            existing = {r["feature"]: dict(r) for r in _user_blocks(conn, user_id)}
            now_ts = int(time.time())

            inserts = []
            summary = []
            for feature in chosen:
                duration_raw = (request.form.get(f"duration_{feature}") or "").strip()
                note = (request.form.get(f"note_{feature}") or "").strip()[:500] or None

                if duration_raw == "perm":
                    expires_at = None
                    expiry_text = "permanent"
                elif duration_raw.isdigit() and int(duration_raw) in VALID_BLOCK_DURATIONS:
                    expires_at = now_ts + int(duration_raw)
                    expiry_text = _humanize_remaining(int(duration_raw))
                else:
                    prev = existing.get(feature)
                    expires_at = prev["expires_at"] if prev else None
                    if expires_at is None:
                        expiry_text = "kept" if prev else "permanent"
                    else:
                        expiry_text = "kept"

                inserts.append((user_id, feature, now_ts, expires_at, note))
                summary.append(f"{feature}:{expiry_text}")

            conn.execute("DELETE FROM user_blocks WHERE user_id=?", (user_id,))
            if inserts:
                conn.executemany(
                    "INSERT INTO user_blocks (user_id, feature, blocked_at, expires_at, note) VALUES (?, ?, ?, ?, ?)",
                    inserts
                )
            conn.commit()

            _log("USER BLOCKS", f"user={user_id} {', '.join(summary) if summary else 'none'}")
            _log_event("block_update", ", ".join(summary) if summary else "none", user_id=user_id)
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

    block_map = {b["feature"]: b for b in current_blocks}

    return render_template(
        "admin_block_user.html",
        user_id=user_id,
        user=user,
        avatar_url=_avatar_url(user_id, user["avatar_hash"]) if user else None,
        guild_rows=guild_rows,
        current_blocks=current_blocks,
        block_map=block_map,
        features=BLOCK_FEATURES,
        durations=BLOCK_DURATIONS,
        saved=form_saved,
        not_known=user is None,
    )
