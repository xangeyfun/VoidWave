import time
import json
from datetime import datetime, timedelta
from pathlib import Path

from flask import render_template, redirect, url_for, request

from . import admin_bp
from .helpers import _db


@admin_bp.route("/stats")
def stats():
    conn = _db()
    try:
        def scalar(sql, params=()):
            r = conn.execute(sql, params).fetchone()
            return r[0] if r else 0

        def percentile(field, pct):
            r = conn.execute(f"""
                SELECT {field} v FROM users ORDER BY {field} DESC
                LIMIT 1 OFFSET (SELECT CAST(COUNT(*) * {pct} AS INT) FROM users)
            """).fetchone()
            return r["v"] if r else 0

        total = scalar("SELECT COUNT(*) FROM users")
        agg = {
            "users": total,
            "guilds": scalar("""
                SELECT COUNT(*) FROM (
                    SELECT DISTINCT guild_id FROM users
                    UNION
                    SELECT guild_id FROM guild_settings
                )
            """),
            "total_xp": scalar("SELECT COALESCE(SUM(total_xp),0) FROM users"),
            "total_messages": scalar("SELECT COALESCE(SUM(total_messages),0) FROM users"),
            "total_messages_xp": scalar("SELECT COALESCE(SUM(total_messages_xp),0) FROM users"),
            "vc_minutes": scalar("SELECT COALESCE(SUM(vc_minutes),0) FROM users"),
            "vc_xp_minutes": scalar("SELECT COALESCE(SUM(vc_xp_minutes),0) FROM users"),
            "avg_level": round(scalar("SELECT COALESCE(AVG(level),0) FROM users"), 2),
            "avg_xp": round(scalar("SELECT COALESCE(AVG(total_xp),0) FROM users"), 2),
            "avg_messages": round(scalar("SELECT COALESCE(AVG(total_messages),0) FROM users"), 2),
            "avg_vc": round(scalar("SELECT COALESCE(AVG(vc_minutes),0) FROM users"), 2),
            "max_level": scalar("SELECT COALESCE(MAX(level),0) FROM users"),
            "max_xp": scalar("SELECT COALESCE(MAX(total_xp),0) FROM users"),
            "max_messages": scalar("SELECT COALESCE(MAX(total_messages),0) FROM users"),
            "max_vc": scalar("SELECT COALESCE(MAX(vc_minutes),0) FROM users"),
            "median_level": percentile("level", 0.5),
            "p90_level": percentile("level", 0.1),
            "p10_level": percentile("level", 0.9),
            "level_100": scalar("SELECT COUNT(*) FROM users WHERE level >= 100"),
            "level_50": scalar("SELECT COUNT(*) FROM users WHERE level >= 50"),
            "level_20": scalar("SELECT COUNT(*) FROM users WHERE level >= 20"),
            "level_10": scalar("SELECT COUNT(*) FROM users WHERE level >= 10"),
            "level_5": scalar("SELECT COUNT(*) FROM users WHERE level >= 5"),
            "xp_per_user": 0,
            "msgs_per_user": 0,
            "vc_per_user": 0,
            "zero_level": scalar("SELECT COUNT(*) FROM users WHERE level = 0"),
            "total_vc_hours": 0,
        }
        agg["xp_per_user"] = round(agg["total_xp"] / total, 2) if total else 0
        agg["msgs_per_user"] = round(agg["total_messages"] / total, 2) if total else 0
        agg["vc_per_user"] = round(agg["vc_minutes"] / total, 2) if total else 0
        agg["total_vc_hours"] = round(agg["vc_minutes"] / 60, 1)

        active = {}
        for label, days in (("24h", 1), ("7d", 7), ("30d", 30)):
            ts = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            active[label] = scalar(
                "SELECT COUNT(*) FROM users WHERE last_message != '' AND last_message >= ?",
                (ts,)
            )

        level_buckets = []
        bounds = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 10),
                  (11, 15), (16, 20), (21, 30), (31, 40), (41, 50), (51, None)]
        for lo, hi in bounds:
            if hi is None:
                n = scalar("SELECT COUNT(*) FROM users WHERE level >= ?", (lo,))
            elif lo == hi:
                n = scalar("SELECT COUNT(*) FROM users WHERE level = ?", (lo,))
            else:
                n = scalar("SELECT COUNT(*) FROM users WHERE level BETWEEN ? AND ?", (lo, hi))
            label = f"Lvl {lo}" if lo == hi else (f"Lvl {lo}-{hi}" if hi else f"Lvl {lo}+")
            level_buckets.append({"range": label, "count": n})

        guild_rows = conn.execute("""
            SELECT a.guild_id,
                   COALESCE(s.users, 0) AS users,
                   COALESCE(s.xp, 0) AS xp,
                   COALESCE(s.msgs, 0) AS msgs,
                   COALESCE(s.vc, 0) AS vc,
                   ROUND(COALESCE(s.avg_level, 0), 1) AS avg_level,
                   COALESCE(s.max_level, 0) AS max_level
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
            ORDER BY users DESC LIMIT 50
        """).fetchall()

        def top(field, n=10):
            rows = conn.execute(
                f"SELECT * FROM users ORDER BY {field} DESC LIMIT ?", (n,)
            ).fetchall()
            return [dict(r) for r in rows]

        boost_rows = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END),0) active, "
            "COALESCE(SUM(CASE WHEN expires_at <= ? THEN 1 ELSE 0 END),0) expired "
            "FROM vote_boosts", (int(time.time()), int(time.time()))
        ).fetchone()

        bot_rows = conn.execute("SELECT * FROM bot_stats").fetchall()

        top_xp = top("total_xp")
        top_messages = top("total_messages")
        top_vc = top("vc_minutes")
        top_level = top("level")

        guild_settings_count = scalar("SELECT COUNT(*) FROM guild_settings")
        level_roles_count = scalar("SELECT COUNT(*) FROM level_roles")

        xp_distribution = []
        xp_bounds = [(0, 0), (1, 49), (50, 99), (100, 249), (250, 499),
                     (500, 999), (1000, 4999), (5000, 9999), (10000, 49999),
                     (50000, 99999), (100000, None)]
        xp_labels = ["0", "1-49", "50-99", "100-249", "250-499",
                     "500-999", "1K-5K", "5K-10K", "10K-50K", "50K-100K", "100K+"]
        for (lo, hi), label in zip(xp_bounds, xp_labels):
            if hi is None:
                n = scalar("SELECT COUNT(*) FROM users WHERE total_xp >= ?", (lo,))
            elif lo == hi:
                n = scalar("SELECT COUNT(*) FROM users WHERE total_xp = ?", (lo,))
            else:
                n = scalar("SELECT COUNT(*) FROM users WHERE total_xp BETWEEN ? AND ?", (lo, hi))
            xp_distribution.append({"range": label, "count": n})

    finally:
        conn.close()

    snapshots = []
    try:
        with open("stats_history.json", "r") as f:
            snapshots = json.load(f)[-30:]
    except Exception:
        snapshots = []

    snap_deltas = []
    prev = None
    for s in snapshots:
        row = {"ts": s.get("timestamp"), "users": s.get("total_users"),
               "xp": s.get("total_xp"), "messages": s.get("total_messages"),
               "vc": s.get("total_vc_minutes"), "guilds": s.get("total_guilds")}
        if prev:
            row["d_users"] = row["users"] - prev["users"]
            row["d_xp"] = row["xp"] - prev["xp"]
            row["d_messages"] = row["messages"] - prev["messages"]
            row["d_vc"] = row["vc"] - prev["vc"] if row["vc"] and prev["vc"] else None
        else:
            row["d_users"] = row["d_xp"] = row["d_messages"] = row["d_vc"] = None
        snap_deltas.append(row)
        prev = row

    db_size = Path("database.db").stat().st_size if Path("database.db").exists() else 0
    wal_size = 0
    if Path("database.db-wal").exists():
        wal_size = Path("database.db-wal").stat().st_size

    return render_template(
        "admin_stats.html",
        agg=agg,
        active=active,
        level_buckets=level_buckets,
        xp_distribution=xp_distribution,
        guild_rows=guild_rows,
        top_xp=top_xp,
        top_messages=top_messages,
        top_vc=top_vc,
        top_level=top_level,
        boost_rows=dict(boost_rows) if boost_rows else {"c": 0, "active": 0, "expired": 0},
        bot_rows=[dict(r) for r in bot_rows],
        snap_deltas=snap_deltas,
        db_size=db_size,
        wal_size=wal_size,
        guild_settings_count=guild_settings_count,
        level_roles_count=level_roles_count,
    )
