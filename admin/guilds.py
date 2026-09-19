import csv
import io
import json
from zoneinfo import ZoneInfo

from flask import Response, render_template, request

from . import admin_bp
from .constants import GUILD_SETTING_FIELDS
from .helpers import _clear_cache, _db, _log


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

        all_guilds = conn.execute("""
            SELECT DISTINCT guild_id FROM users
            UNION
            SELECT guild_id FROM guild_settings
            ORDER BY guild_id
        """).fetchall()
        guild_picker = [r["guild_id"] for r in all_guilds]

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

        leaderboard = [
            dict(r) for r in conn.execute("""
                SELECT user_id, display_name, username, level, progress, out_of, total_xp
                FROM users WHERE guild_id=?
                ORDER BY level DESC, total_xp DESC, user_id
                LIMIT 10
            """, (guild_id,)).fetchall()
        ]

        lr_by_level = {r["level"]: r["role_id"] for r in level_roles}
        for entry in leaderboard:
            best = None
            for lvl, rid in lr_by_level.items():
                if entry["level"] >= lvl and (best is None or lvl > best["level"]):
                    best = {"level": lvl, "role_id": rid}
            entry["role"] = best

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

                time_raw = (request.form.get("qotd_time") or "").strip()
                tz_raw = (request.form.get("qotd_tz") or "").strip()
                parsed_time = None
                parsed_tz = None

                if time_raw:
                    try:
                        hh_s, mm_s = time_raw.split(":")
                        hh, mm = int(hh_s), int(mm_s)
                    except ValueError:
                        hh = mm = -1
                    if 0 <= hh <= 23 and 0 <= mm <= 59:
                        parsed_time = f"{hh:02d}:{mm:02d}"
                    else:
                        error = "QOTD post time must be a valid 24h HH:MM value."

                if not error and tz_raw:
                    try:
                        ZoneInfo(tz_raw)
                        parsed_tz = tz_raw
                    except Exception:
                        error = "QOTD timezone must be a valid IANA name such as Europe/Berlin."

                queue_val = None
                if not error:
                    queue_raw = (request.form.get("qotd_queue") or "").strip()
                    if queue_raw:
                        try:
                            parsed_queue = json.loads(queue_raw)
                        except ValueError:
                            error = "QOTD queue must be valid JSON, e.g. [0, 3, 7]."
                        else:
                            if not isinstance(parsed_queue, list) or not all(
                                isinstance(i, int) and i >= 0 for i in parsed_queue
                            ):
                                error = "QOTD queue must be a JSON array of question indexes, e.g. [0, 3, 7]."
                            else:
                                queue_val = json.dumps(parsed_queue)

                if not error:
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
                        elif ftype == "text":
                            val = raw.strip() or None
                            conn.execute(
                                f"UPDATE guild_settings SET {field}=? WHERE guild_id=?",
                                (val, guild_id)
                            )
                    conn.execute(
                        "UPDATE guild_settings SET qotd_time=?, qotd_tz=?, qotd_queue=? WHERE guild_id=?",
                        (parsed_time, parsed_tz, queue_val, guild_id)
                    )
                    conn.commit()
                    _clear_cache()
                    _log("GUILD SETTINGS EDIT", f"guild={guild_id}")
                    flash_msg = "Guild settings saved."

            elif action == "clone_settings":
                source_id = request.form.get("clone_source")
                if not source_id or not source_id.isdigit():
                    error = "Please select a source guild."
                else:
                    source_id = int(source_id)
                    source = conn.execute(
                        "SELECT * FROM guild_settings WHERE guild_id=?", (source_id,)
                    ).fetchone()
                    if not source:
                        error = f"No settings found for guild {source_id}."
                    elif source_id == guild_id:
                        error = "Source and target guild are the same."
                    else:
                        if not settings:
                            conn.execute(
                                "INSERT INTO guild_settings (guild_id) VALUES (?)", (guild_id,)
                            )
                            conn.commit()
                            settings = conn.execute(
                                "SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,)
                            ).fetchone()
                        for field in GUILD_SETTING_FIELDS:
                            conn.execute(
                                f"UPDATE guild_settings SET {field}=? WHERE guild_id=?",
                                (source[field], guild_id)
                            )
                        conn.execute(
                            "UPDATE guild_settings SET qotd_time=?, qotd_tz=?, qotd_queue=? WHERE guild_id=?",
                            (source["qotd_time"], source["qotd_tz"], source["qotd_queue"], guild_id)
                        )
                        conn.execute("DELETE FROM level_roles WHERE guild_id=?", (guild_id,))
                        source_roles = conn.execute(
                            "SELECT level, role_id FROM level_roles WHERE guild_id=?", (source_id,)
                        ).fetchall()
                        for role in source_roles:
                            conn.execute(
                                "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)",
                                (guild_id, role["level"], role["role_id"])
                            )
                        conn.commit()
                        _clear_cache()
                        _log("GUILD CLONE", f"guild={guild_id} from={source_id}")
                        flash_msg = f"Copied settings and level roles from {source_id}."

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

    qotd_queue_count = 0
    if settings and settings["qotd_queue"]:
        try:
            parsed = json.loads(settings["qotd_queue"])
            if isinstance(parsed, list):
                qotd_queue_count = len(parsed)
        except (ValueError, TypeError):
            qotd_queue_count = 0

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
        qotd_queue_count=qotd_queue_count,
        guild_picker=guild_picker,
        leaderboard=leaderboard,
    )
