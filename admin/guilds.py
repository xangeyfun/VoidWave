import time
import json
from datetime import datetime, timedelta
from pathlib import Path

import io
import csv
from flask import render_template, redirect, url_for, request, Response

from . import admin_bp
from .helpers import _db, _log, _clear_cache, _parse_int
from .constants import GUILD_SETTING_FIELDS, LEVEL_ROLE_FIELDS


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

    conn = _db()
    try:
        rows = conn.execute("""
            SELECT
                a.guild_id,
                COALESCE(s.users, 0) AS users,
                COALESCE(s.xp, 0) AS xp,
                COALESCE(s.msgs, 0) AS msgs,
                COALESCE(s.vc, 0) AS vc,
                ROUND(COALESCE(s.avg_level, 0), 1) AS avg_level,
                COALESCE(s.max_level, 0) AS max_level,
                CASE WHEN gs.guild_id IS NOT NULL THEN 1 ELSE 0 END AS has_settings,
                gs.level_channel_enabled,
                gs.qotd_enabled
            FROM (
                SELECT DISTINCT guild_id FROM users
                UNION
                SELECT guild_id FROM guild_settings
            ) a
            LEFT JOIN (
                SELECT guild_id,
                       COUNT(*) AS users,
                       SUM(total_xp) AS xp,
                       SUM(total_messages) AS msgs,
                       SUM(vc_minutes) AS vc,
                       AVG(level) AS avg_level,
                       MAX(level) AS max_level
                FROM users GROUP BY guild_id
            ) s ON s.guild_id = a.guild_id
            LEFT JOIN guild_settings gs ON gs.guild_id = a.guild_id
        """).fetchall()

        if q and q.isdigit() and len(q) >= 8:
            rows = [r for r in rows if str(r["guild_id"]) == q]
        elif q:
            rows = [r for r in rows if q in str(r["guild_id"])]

        sort_map = {"guild_id": "guild_id", "users": "users", "xp": "xp",
                    "avg_level": "avg_level", "settings": "has_settings"}
        rows = [dict(r) for r in rows]
        rows = sorted(rows, key=lambda r: r.get(sort_map.get(sort, "users"), 0),
                      reverse=(order == "desc"))

        total = len(rows)
        total_pages = max(1, (total + per - 1) // per)
        page = min(page, total_pages)
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


@admin_bp.route("/guilds/export")
def guilds_export():
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "users")
    order = request.args.get("order", "desc")

    valid_sorts = {"guild_id", "users", "xp", "avg_level", "settings"}
    if sort not in valid_sorts:
        sort = "users"

    conn = _db()
    try:
        rows = conn.execute("""
            SELECT
                a.guild_id,
                COALESCE(s.users, 0) AS users,
                COALESCE(s.xp, 0) AS xp,
                COALESCE(s.msgs, 0) AS msgs,
                ROUND(COALESCE(s.avg_level, 0), 1) AS avg_level,
                COALESCE(s.max_level, 0) AS max_level,
                CASE WHEN gs.guild_id IS NOT NULL THEN 1 ELSE 0 END AS has_settings
            FROM (
                SELECT DISTINCT guild_id FROM users
                UNION
                SELECT guild_id FROM guild_settings
            ) a
            LEFT JOIN (
                SELECT guild_id,
                       COUNT(*) AS users,
                       SUM(total_xp) AS xp,
                       SUM(total_messages) AS msgs,
                       AVG(level) AS avg_level,
                       MAX(level) AS max_level
                FROM users GROUP BY guild_id
            ) s ON s.guild_id = a.guild_id
            LEFT JOIN guild_settings gs ON gs.guild_id = a.guild_id
        """).fetchall()

        if q and q.isdigit() and len(q) >= 8:
            rows = [r for r in rows if str(r["guild_id"]) == q]
        elif q:
            rows = [r for r in rows if q in str(r["guild_id"])]

        sort_map = {"guild_id": "guild_id", "users": "users", "xp": "xp",
                    "avg_level": "avg_level", "settings": "has_settings"}
        rows = sorted(rows, key=lambda r: r.get(sort_map.get(sort, "users"), 0),
                      reverse=(order == "desc"))
    finally:
        conn.close()

    columns = ["guild_id", "users", "xp", "msgs", "avg_level", "max_level", "has_settings"]

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
        headers={"Content-Disposition": "attachment; filename=guilds_export.csv"},
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
