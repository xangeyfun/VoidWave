import time
import hmac
import json
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, session, abort

from . import admin_bp
from .helpers import _db, _log, _clear_cache, _parse_int, _read_log_lines
from .constants import TABLES


def _stale_user_sql(days):
    ts = datetime.now() - timedelta(days=days)
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
    return (
        "SELECT * FROM users WHERE level=0 AND total_xp=0 AND total_messages=0 "
        "AND vc_minutes=0 AND (last_message='' OR last_message < ?)",
        (ts_str,)
    )


def _forget_preview(spec):
    conn = _db()
    try:
        def rows(sql, params=()):
            return conn.execute(sql, params).fetchall()

        if spec["type"] == "user_all":
            ids = spec["user_ids"]
            marks = ",".join("?" * len(ids))
            ur = rows(f"SELECT * FROM users WHERE user_id IN ({marks})", ids)
            br = rows(f"SELECT * FROM vote_boosts WHERE user_id IN ({marks})", ids)
            return {
                "users_rows": len(ur),
                "distinct_guilds": len({r["guild_id"] for r in ur}),
                "boost_rows": len(br),
                "user_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                  "username": r["username"] or "unknown",
                                  "display_name": r["display_name"] or "",
                                  "level": r["level"], "total_xp": r["total_xp"]} for r in ur[:50]],
                "boost_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                   "expires_at": r["expires_at"]} for r in br[:50]],
            }
        if spec["type"] == "user_guild":
            gid = spec["guild_id"]
            marks = ",".join("?" * len(spec["user_ids"]))
            ur = rows(f"SELECT * FROM users WHERE guild_id=? AND user_id IN ({marks})", [gid] + spec["user_ids"])
            return {
                "users_rows": len(ur), "distinct_guilds": 1, "boost_rows": 0,
                "user_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                  "username": r["username"] or "unknown",
                                  "display_name": r["display_name"] or "",
                                  "level": r["level"], "total_xp": r["total_xp"]} for r in ur[:50]],
            }
        if spec["type"] == "guild_users":
            ur = rows("SELECT * FROM users WHERE guild_id=?", (spec["guild_id"],))
            return {
                "users_rows": len(ur), "distinct_guilds": 1, "boost_rows": 0,
                "user_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                  "username": r["username"] or "unknown",
                                  "display_name": r["display_name"] or "",
                                  "level": r["level"], "total_xp": r["total_xp"]} for r in ur[:50]],
            }
        if spec["type"] == "guild_full":
            gid = spec["guild_id"]
            ur = rows("SELECT * FROM users WHERE guild_id=?", (gid,))
            gr = rows("SELECT * FROM guild_settings WHERE guild_id=?", (gid,))
            lr = rows("SELECT * FROM level_roles WHERE guild_id=?", (gid,))
            return {
                "users_rows": len(ur), "guild_settings_rows": len(gr), "level_roles_rows": len(lr),
                "user_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                  "username": r["username"] or "unknown",
                                  "display_name": r["display_name"] or "",
                                  "level": r["level"], "total_xp": r["total_xp"]} for r in ur[:50]],
                "level_role_details": [{"level": r["level"], "role_id": r["role_id"]} for r in lr],
            }
        if spec["type"] == "boost":
            marks = ",".join("?" * len(spec["user_ids"]))
            br = rows(f"SELECT * FROM vote_boosts WHERE user_id IN ({marks})", spec["user_ids"])
            return {
                "users_rows": 0, "boost_rows": len(br),
                "boost_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                   "expires_at": r["expires_at"]} for r in br[:50]],
            }
        if spec["type"] == "expired_boosts":
            br = rows("SELECT * FROM vote_boosts WHERE expires_at <= ?", (int(time.time()),))
            return {
                "users_rows": 0, "boost_rows": len(br),
                "boost_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                   "expires_at": r["expires_at"]} for r in br[:50]],
            }
        if spec["type"] == "stale_users":
            sql, params = _stale_user_sql(spec["days"])
            ur = rows(sql, params)
            return {
                "users_rows": len(ur), "distinct_guilds": len({r["guild_id"] for r in ur}), "boost_rows": 0,
                "user_details": [{"user_id": r["user_id"], "guild_id": r["guild_id"],
                                  "username": r["username"] or "unknown",
                                  "display_name": r["display_name"] or "",
                                  "level": r["level"], "total_xp": r["total_xp"]} for r in ur[:50]],
            }
        if spec["type"] == "reset_all":
            return {"users_rows": rows("SELECT COUNT(*) c FROM users")[0]["c"],
                    "boost_rows": rows("SELECT COUNT(*) c FROM vote_boosts")[0]["c"]}
        if spec["type"] == "reset_table":
            t = spec["table"]
            return {f"{t}_rows": rows(f"SELECT COUNT(*) c FROM {t}")[0]["c"]}
    finally:
        conn.close()
    return {}


def _forget_execute(spec):
    conn = _db()
    counts = {}
    try:
        cur = conn.cursor()

        def run(sql, params=()):
            cur.execute(sql, params)
            counts.setdefault("_total", 0)
            counts["_total"] += cur.rowcount
            return cur.rowcount

        if spec["type"] == "user_all":
            marks = ",".join("?" * len(spec["user_ids"]))
            run(f"DELETE FROM users WHERE user_id IN ({marks})", spec["user_ids"])
            run(f"DELETE FROM vote_boosts WHERE user_id IN ({marks})", spec["user_ids"])
        elif spec["type"] == "user_guild":
            marks = ",".join("?" * len(spec["user_ids"]))
            run(f"DELETE FROM users WHERE guild_id=? AND user_id IN ({marks})",
                [spec["guild_id"]] + spec["user_ids"])
        elif spec["type"] == "guild_users":
            run("DELETE FROM users WHERE guild_id=?", (spec["guild_id"],))
        elif spec["type"] == "guild_full":
            gid = spec["guild_id"]
            run("DELETE FROM users WHERE guild_id=?", (gid,))
            run("DELETE FROM guild_settings WHERE guild_id=?", (gid,))
            run("DELETE FROM level_roles WHERE guild_id=?", (gid,))
        elif spec["type"] == "boost":
            marks = ",".join("?" * len(spec["user_ids"]))
            run(f"DELETE FROM vote_boosts WHERE user_id IN ({marks})", spec["user_ids"])
        elif spec["type"] == "expired_boosts":
            run("DELETE FROM vote_boosts WHERE expires_at <= ?", (int(time.time()),))
        elif spec["type"] == "stale_users":
            sql, params = _stale_user_sql(spec["days"])
            run(sql, params)
        elif spec["type"] == "reset_all":
            run("DELETE FROM users")
            run("DELETE FROM vote_boosts")
        elif spec["type"] == "reset_table":
            t = spec["table"]
            if t not in TABLES:
                abort(400)
            run(f"DELETE FROM {t}")

        conn.commit()
        _clear_cache()
        return counts
    finally:
        conn.close()


def _forget_spec_from_form(form):
    mode = form.get("mode")
    ids_raw = [ln.strip() for ln in (form.get("user_ids") or "").splitlines() if ln.strip()]
    user_ids = []
    for v in ids_raw:
        try:
            iv = int(v)
        except ValueError:
            abort(400)
        if iv < 1000000000000:
            abort(400)
        user_ids.append(iv)
    user_ids = list(dict.fromkeys(user_ids))

    guild_raw = form.get("guild_id", "").strip()
    guild_id = _parse_int(guild_raw, "guild_id") if guild_raw else None

    if mode == "user_all":
        if not user_ids:
            abort(400)
        return {"type": "user_all", "user_ids": user_ids}, "DELETE"
    if mode == "user_guild":
        if not user_ids or not guild_id:
            abort(400)
        return {"type": "user_guild", "user_ids": user_ids, "guild_id": guild_id}, "DELETE"
    if mode in ("guild_users", "guild_full"):
        if not guild_id:
            abort(400)
        return {"type": mode, "guild_id": guild_id}, "DELETE"
    if mode == "boost":
        if not user_ids:
            abort(400)
        return {"type": "boost", "user_ids": user_ids}, "DELETE"
    if mode == "expired_boosts":
        return {"type": "expired_boosts"}, "DELETE"
    if mode == "stale_users":
        days = max(1, min(365, _parse_int(form.get("days", "30"), "days")))
        return {"type": "stale_users", "days": days}, "DELETE"
    if mode == "reset_all":
        return {"type": "reset_all"}, "RESET"
    if mode == "reset_table":
        t = form.get("table", "")
        if t not in TABLES:
            abort(400)
        return {"type": "reset_table", "table": t}, t.upper()
    abort(400)


def _recent_forget_ops(limit=15):
    lines = _read_log_lines()
    ops = []
    for ln in reversed(lines):
        if "FORGET EXEC" in ln:
            parts = ln.split(" ", 3)
            ts = " ".join(parts[:2]) if len(parts) >= 2 else ln[:19]
            detail = parts[3] if len(parts) > 3 else ""
            try:
                data = json.loads(detail)
                spec = data.get("spec", {})
                counts = data.get("counts", {})
                ops.append({"timestamp": ts, "spec": spec, "counts": counts})
            except (json.JSONDecodeError, IndexError):
                ops.append({"timestamp": ts, "spec": {}, "counts": {}, "raw": detail})
            if len(ops) >= limit:
                break
    return ops


@admin_bp.route("/forget", methods=["GET", "POST"])
def forget():
    if request.method == "POST":
        spec, word = _forget_spec_from_form(request.form)
        preview = _forget_preview(spec)
        session["pending_forget_spec"] = spec
        session["pending_forget_word"] = word
        return render_template(
            "admin_forget_confirm.html", spec=spec, preview=preview, word=word
        )
    recent = _recent_forget_ops()
    return render_template("admin_forget.html", recent=recent)


@admin_bp.route("/forget/confirm", methods=["POST"])
def forget_confirm():
    word = session.get("pending_forget_word", "")
    spec = session.get("pending_forget_spec")
    if not spec or not word:
        abort(400)

    confirm = (request.form.get("confirm") or "").strip()
    if not hmac.compare_digest(confirm, word):
        _log("FORGET FAIL", "confirmation mismatch")
        return render_template("admin_forget_confirm.html",
                               spec=spec, preview=_forget_preview(spec), word=word,
                               error=f"Confirmation must be exactly: {word}")

    counts = _forget_execute(spec)
    session.pop("pending_forget_spec", None)
    session.pop("pending_forget_word", None)
    _log("FORGET EXEC", json.dumps({"spec": spec, "counts": counts}))
    return render_template("admin_forget_result.html", spec=spec, counts=counts)
