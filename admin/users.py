import time
import json
import io
import csv
from flask import render_template, request, redirect, url_for, session, abort, flash, Response

from . import admin_bp
from .helpers import (
    _db, _log, _clear_cache, _parse_int, _normalize_progress,
)
from .constants import USER_FIELDS


def _parse_bulk_targets(raw):
    targets = []
    for line in (raw or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            targets.append((int(parts[0]), int(parts[1])))
    return targets


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


@admin_bp.route("/users/export")
def users_export():
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "total_xp")
    order = request.args.get("order", "desc")

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
        rows = conn.execute(
            f"SELECT * FROM users {wsql} ORDER BY {sort} {dir_sql}, user_id",
            params
        ).fetchall()
    finally:
        conn.close()

    columns = [
        "user_id", "guild_id", "username", "display_name",
        "level", "progress", "out_of",
        "total_xp", "total_messages", "total_messages_xp",
        "vc_minutes", "vc_xp_minutes", "last_message",
    ]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for r in rows:
        writer.writerow([r[c] for c in columns])

    output = buf.getvalue()
    buf.close()

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=users_export.csv"},
    )


@admin_bp.route("/users/add", methods=["POST"])
def user_add():
    guild_id = _parse_int(request.form.get("guild_id"), "guild_id")
    user_id = _parse_int(request.form.get("user_id"), "user_id")
    username = (request.form.get("username") or "unknown").strip() or "unknown"

    if guild_id < 1000000000000 or user_id < 1000000000000:
        _log("USER ADD FAIL", f"invalid ids guild={guild_id} user={user_id}")
        flash("Invalid Discord IDs (must be 13+ digits)", "error")
        return redirect(url_for("admin.users"))

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

        def render_page(error=None, flash_msg=None):
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
            return render_template(
                "admin_user_edit.html",
                user=user,
                rank=rank,
                global_rank=global_rank,
                boost=boost,
                guild_rows=guild_rows,
                flash_msg=flash_msg,
                error=error,
                now=int(time.time()),
            )

        if request.method == "POST":
            action = request.form.get("action", "save_user")

            if action == "clear_boost":
                conn.execute("DELETE FROM vote_boosts WHERE user_id=?", (user_id,))
                conn.commit()
                _clear_cache()
                _log("VOTE BOOST REVOKE", f"user={user_id}")
                return render_page(flash_msg="Vote boost revoked.")

            if action == "set_boost":
                try:
                    multiplier = round(float(request.form.get("boost_multiplier", "")), 2)
                    hours = int(request.form.get("boost_hours", ""))
                except (TypeError, ValueError):
                    return render_page(error="Multiplier must be a number and duration a whole number of hours.")
                if not (1.0 <= multiplier <= 10.0):
                    return render_page(error="Multiplier must be between 1 and 10.")
                if hours <= 0 or hours > 24 * 30:
                    return render_page(error="Duration must be between 1 and 720 hours.")
                expires_at = int(time.time()) + hours * 3600
                conn.execute(
                    "INSERT INTO vote_boosts (user_id, multiplier, expires_at, last_vote_at) "
                    "VALUES (?, ?, ?, NULL) "
                    "ON CONFLICT(user_id) DO UPDATE SET multiplier=excluded.multiplier, expires_at=excluded.expires_at",
                    (user_id, multiplier, expires_at)
                )
                conn.commit()
                _clear_cache()
                _log("VOTE BOOST SET", f"user={user_id} multiplier={multiplier} expires_at={expires_at}")
                return render_page(flash_msg="Vote boost saved.")

            data = {}
            for field, ftype in USER_FIELDS.items():
                raw = request.form.get(field, "")
                if ftype == "int":
                    try:
                        data[field] = int(raw)
                    except (TypeError, ValueError):
                        _log("USER EDIT FAIL", f"bad value {field} guild={guild_id} user={user_id}")
                        return render_page(error=f"Invalid number for {field}.")
                else:
                    data[field] = raw.strip()

            if any(data[f] < 0 for f in ("level", "progress", "out_of", "total_xp",
                                         "total_messages", "total_messages_xp",
                                         "vc_minutes", "vc_xp_minutes")):
                _log("USER EDIT FAIL", f"negative value guild={guild_id} user={user_id}")
                return render_page(error="Values cannot be negative.")

            auto_fix = request.form.get("auto_fix") == "on"

            if auto_fix:
                level, progress, out_of = _normalize_progress(
                    data["level"], data["progress"], data["out_of"]
                )
                data["level"], data["progress"], data["out_of"] = level, progress, out_of
            elif data["out_of"] <= 0:
                return render_page(error="out_of must be positive (or enable auto-fix).")
            elif data["progress"] >= data["out_of"]:
                _log("USER EDIT WARN", f"progress>=out_of after edit guild={guild_id} user={user_id}")

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
            return render_page(flash_msg="User updated.")

        return render_page()
    finally:
        conn.close()


@admin_bp.route("/users/<int:guild_id>/<int:user_id>/delete", methods=["POST"])
def user_delete(guild_id, user_id):
    confirm = (request.form.get("confirm") or "").strip()
    if confirm != "DELETE":
        flash("Confirmation must be DELETE", "error")
        return redirect(url_for("admin.user_edit", guild_id=guild_id, user_id=user_id))

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
    flash(f"Deleted {removed} row(s).", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/bulk/reset", methods=["POST"])
def user_bulk_reset():
    confirm = (request.form.get("confirm") or "").strip()
    if confirm != "RESET":
        flash("Confirmation must be RESET", "error")
        return redirect(url_for("admin.users"))

    targets = _parse_bulk_targets(request.form.get("targets", ""))
    if not targets:
        flash("No valid user targets provided.", "error")
        return redirect(url_for("admin.users"))

    conn = _db()
    try:
        count = 0
        for guild_id, user_id in targets:
            cur = conn.execute("""
                UPDATE users SET
                    level=0, progress=0, out_of=100,
                    total_xp=0, total_messages=0, total_messages_xp=0,
                    vc_minutes=0, vc_xp_minutes=0
                WHERE guild_id=? AND user_id=?
            """, (guild_id, user_id))
            count += cur.rowcount
        conn.commit()
        _clear_cache()
    finally:
        conn.close()

    _log("USER BULK RESET", f"count={count} ids={[(g, u) for g, u in targets[:20]]}")
    flash(f"Reset {count} user(s).", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/bulk/delete", methods=["POST"])
def user_bulk_delete():
    confirm = (request.form.get("confirm") or "").strip()
    if confirm != "DELETE":
        flash("Confirmation must be DELETE", "error")
        return redirect(url_for("admin.users"))

    targets = _parse_bulk_targets(request.form.get("targets", ""))
    if not targets:
        flash("No valid user targets provided.", "error")
        return redirect(url_for("admin.users"))

    conn = _db()
    try:
        count = 0
        for guild_id, user_id in targets:
            cur = conn.execute(
                "DELETE FROM users WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            )
            count += cur.rowcount
        conn.commit()
        _clear_cache()
    finally:
        conn.close()

    _log("USER BULK DELETE", f"count={count} ids={[(g, u) for g, u in targets[:20]]}")
    flash(f"Deleted {count} user(s).", "success")
    return redirect(url_for("admin.users"))
