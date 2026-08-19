import time
import json
from flask import render_template, request, redirect, url_for, session, abort

from . import admin_bp
from .helpers import (
    _db, _log, _clear_cache, _parse_int, _normalize_progress,
)
from .constants import USER_FIELDS


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
