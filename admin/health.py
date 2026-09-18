import time
import json
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import render_template, redirect, url_for, session, jsonify, abort, flash

from . import admin_bp
from .helpers import _db, _log, _clear_cache, _normalize_progress, _list_backups
from .constants import (
    TABLES, REQUIRED_USERS_COLUMNS, REQUIRED_GUILD_COLUMNS, REQUIRED_VOTE_BOOST_COLUMNS,
)


_GUILD_SCHEMA_FIXES = (
    ("level_channel_enabled", "BOOLEAN DEFAULT 0"),
    ("qotd_enabled", "BOOLEAN DEFAULT 0"),
    ("qotd_channel", "INTEGER"),
    ("qotd_role_id", "INTEGER"),
    ("last_qotd_id", "INTEGER"),
    ("last_qotd_thread_id", "INTEGER"),
    ("qotd_queue", "TEXT"),
    ("delete_old_qotd", "BOOLEAN DEFAULT 1"),
    ("qotd_time", "TEXT DEFAULT '16:00'"),
    ("qotd_tz", "TEXT"),
    ("last_qotd_date", "TEXT"),
    ("vote_announce_enabled", "BOOLEAN DEFAULT 1"),
    ("ai_enabled", "BOOLEAN DEFAULT 1"),
)

_VOTE_BOOST_SCHEMA_FIXES = (
    ("multiplier", "INTEGER DEFAULT 1"),
    ("expires_at", "INTEGER"),
    ("last_vote_at", "INTEGER"),
)


def _valid_qotd_time(value):
    if value is None or value == "":
        return True
    parts = str(value).split(":")
    if len(parts) != 2:
        return False
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= hours <= 23 and 0 <= minutes <= 59


def _valid_tz(value):
    if value is None or value == "":
        return True
    try:
        ZoneInfo(value)
        return True
    except Exception:
        return False


def _load_qotd_count():
    qfile = Path("questions.json")
    if not qfile.exists():
        return None
    try:
        with open(qfile, encoding="utf-8") as f:
            return len(json.load(f))
    except Exception:
        return None


def _parse_qotd_queue(value, q_count=None):
    """Return (ok, reason) for a stored qotd_queue value."""
    if value is None or value == "":
        return True, ""
    try:
        parsed = json.loads(value)
    except ValueError:
        return False, "not valid JSON"
    if not isinstance(parsed, list):
        return False, "not a JSON array"
    if any(not isinstance(i, int) or isinstance(i, bool) or i < 0 for i in parsed):
        return False, "contains non-integer or negative entries"
    if q_count is not None and any(i >= q_count for i in parsed):
        return False, f"index out of range (max {q_count - 1})"
    return True, ""


def _run_checks():
    conn = _db()
    results = []

    def add(category, name, ok, detail="", fix=None, sql=None):
        results.append({
            "category": category, "name": name, "ok": bool(ok),
            "detail": detail, "fix": fix, "sql": sql,
        })

    try:
        def q(sql, params=()):
            return conn.execute(sql, params).fetchall()

        integrity = q("PRAGMA integrity_check")
        add("Structure", "SQLite integrity check", all(r[0] == "ok" for r in integrity),
            "; ".join(str(r[0]) for r in integrity), sql="PRAGMA integrity_check")

        quick = q("PRAGMA quick_check")
        add("Structure", "Quick check", all(r[0] == "ok" for r in quick),
            "; ".join(str(r[0]) for r in quick), sql="PRAGMA quick_check")

        tables = {r["name"] for r in q("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in sorted(TABLES) if t not in tables]
        add("Structure", "Required tables", not missing,
            "missing: " + ", ".join(missing) if missing else "all present",
            sql="SELECT name FROM sqlite_master WHERE type='table'")

        cols = {r["name"] for r in q("PRAGMA table_info(users)")}
        missing_cols = sorted(REQUIRED_USERS_COLUMNS - cols)
        add("Structure", "users columns", not missing_cols,
            "missing: " + ", ".join(missing_cols) if missing_cols else "all present",
            sql="PRAGMA table_info(users)")

        g_cols = {r["name"] for r in q("PRAGMA table_info(guild_settings)")}
        missing_g = sorted(REQUIRED_GUILD_COLUMNS - g_cols)
        add("Structure", "guild_settings columns", not missing_g,
            "missing: " + ", ".join(missing_g) if missing_g else "all present",
            fix="guild_schema" if missing_g else None,
            sql="PRAGMA table_info(guild_settings)")

        b_cols = {r["name"] for r in q("PRAGMA table_info(vote_boosts)")}
        missing_b = sorted(REQUIRED_VOTE_BOOST_COLUMNS - b_cols)
        add("Structure", "vote_boosts columns", not missing_b,
            "missing: " + ", ".join(missing_b) if missing_b else "all present",
            fix="vote_boost_schema" if missing_b else None,
            sql="PRAGMA table_info(vote_boosts)")

        try:
            backups = _list_backups()
        except Exception:
            backups = []
        if not backups:
            add("System", "Backup up to date", False,
                "No backups found", sql="SELECT NULL FROM database_backups")
        else:
            age_h = (time.time() - backups[0]["mtime"].timestamp()) / 3600
            add("System", "Backup up to date", age_h <= 7 * 24,
                f"Latest backup is {int(age_h)}h old" if age_h >= 1 else "Latest backup is fresh",
                sql="SELECT name FROM database_backups ORDER BY mtime DESC LIMIT 1")

        rows = q("SELECT guild_id, user_id, level, progress, out_of FROM users WHERE progress >= out_of")
        add("Data", "progress >= out_of", not rows,
            f"{len(rows)} row(s)", fix="normalize" if rows else None,
            sql="SELECT guild_id, user_id, level, progress, out_of FROM users\nWHERE progress >= out_of")

        rows = q("SELECT guild_id, user_id FROM users WHERE out_of <= 0")
        add("Data", "out_of <= 0", not rows,
            f"{len(rows)} row(s)", fix="out_of" if rows else None,
            sql="SELECT guild_id, user_id FROM users WHERE out_of <= 0")

        rows = q("""SELECT guild_id, user_id FROM users WHERE level<0 OR progress<0 OR out_of<0
            OR total_messages<0 OR total_messages_xp<0 OR total_xp<0
            OR vc_minutes<0 OR vc_xp_minutes<0""")
        add("Data", "Negative stat values", not rows,
            f"{len(rows)} row(s)", fix="negatives" if rows else None,
            sql="""SELECT guild_id, user_id FROM users
WHERE level < 0 OR progress < 0 OR out_of < 0
   OR total_messages < 0 OR total_messages_xp < 0 OR total_xp < 0
   OR vc_minutes < 0 OR vc_xp_minutes < 0""")

        rows = q("""SELECT guild_id, user_id FROM users WHERE user_id IS NULL OR guild_id IS NULL
            OR level IS NULL OR progress IS NULL OR out_of IS NULL
            OR total_messages IS NULL OR total_messages_xp IS NULL OR total_xp IS NULL
            OR vc_minutes IS NULL OR vc_xp_minutes IS NULL
            OR command_uses IS NULL OR rated IS NULL OR prompt_sent IS NULL""")
        add("Data", "NULL required fields", not rows,
            f"{len(rows)} row(s)", fix="nulls" if rows else None,
            sql="""SELECT guild_id, user_id FROM users
WHERE user_id IS NULL OR guild_id IS NULL
   OR level IS NULL OR progress IS NULL OR out_of IS NULL
   OR total_messages IS NULL OR total_messages_xp IS NULL OR total_xp IS NULL
   OR vc_minutes IS NULL OR vc_xp_minutes IS NULL
   OR command_uses IS NULL OR rated IS NULL OR prompt_sent IS NULL""")

        rows = q("SELECT user_id FROM users WHERE user_id < 1000000000000 GROUP BY user_id")
        add("Data", "Suspicious user IDs", not rows, f"{len(rows)} id(s)",
            sql="SELECT user_id FROM users WHERE user_id < 1000000000000 GROUP BY user_id")

        rows = q("SELECT guild_id FROM users WHERE guild_id < 1000000000000 GROUP BY guild_id")
        add("Data", "Suspicious guild IDs", not rows, f"{len(rows)} id(s)",
            sql="SELECT guild_id FROM users WHERE guild_id < 1000000000000 GROUP BY guild_id")

        rows = q("""SELECT guild_id, user_id FROM users
            WHERE level=0 AND total_xp=0 AND total_messages=0 AND vc_minutes=0 AND last_message=''""")
        add("Data", "Empty placeholder users", not rows,
            f"{len(rows)} row(s)", fix="empty" if rows else None,
            sql="""SELECT guild_id, user_id FROM users
WHERE level = 0 AND total_xp = 0 AND total_messages = 0
  AND vc_minutes = 0 AND last_message = ''""")

        rows = q("SELECT COUNT(*) c FROM users WHERE total_messages_xp > total_messages")
        add("Data", "message_xp > total_messages", not rows[0]["c"],
            f"{rows[0]['c']} row(s)",
            sql="SELECT COUNT(*) c FROM users WHERE total_messages_xp > total_messages")

        rows = q("SELECT COUNT(*) c FROM users WHERE total_messages_xp > total_xp")
        add("Data", "message_xp count > total_xp", not rows[0]["c"],
            f"{rows[0]['c']} row(s)",
            sql="SELECT COUNT(*) c FROM users WHERE total_messages_xp > total_xp")

        rows = q("SELECT COUNT(*) c FROM users WHERE vc_xp_minutes > vc_minutes")
        add("Data", "vc_xp_minutes > vc_minutes", not rows[0]["c"],
            f"{rows[0]['c']} row(s)",
            sql="SELECT COUNT(*) c FROM users WHERE vc_xp_minutes > vc_minutes")

        rows = q("""SELECT g.guild_id FROM guild_settings g
            LEFT JOIN (SELECT DISTINCT guild_id FROM users) u ON u.guild_id=g.guild_id
            WHERE u.guild_id IS NULL""")
        add("Info", "Guild settings without tracked users", True,
            f"{len(rows)} guild(s) (normal for brand new servers)",
            sql="""SELECT g.guild_id FROM guild_settings g
LEFT JOIN (SELECT DISTINCT guild_id FROM users) u ON u.guild_id = g.guild_id
WHERE u.guild_id IS NULL""")

        rows = q("SELECT COUNT(*) c FROM users GROUP BY guild_id, user_id HAVING c > 1")
        add("Data", "Duplicate user rows", not rows, f"{len(rows)} duplicated pair(s)",
            sql="SELECT COUNT(*) c FROM users GROUP BY guild_id, user_id HAVING c > 1")

        rows = q("SELECT guild_id FROM users GROUP BY guild_id HAVING COUNT(*) < 2")
        add("Data", "Single-user guilds", True,
            f"{len(rows)} guild(s) with only 1 user",
            sql="SELECT guild_id FROM users GROUP BY guild_id HAVING COUNT(*) < 2")

        rows = q("""SELECT guild_id, user_id FROM users
            WHERE last_message != '' AND date(last_message) > date('now', 'localtime')""")
        add("Data", "Future timestamps", not rows,
            f"{len(rows)} row(s)", fix="future_timestamps" if rows else None,
            sql="""SELECT guild_id, user_id FROM users
WHERE last_message != '' AND date(last_message) > date('now', 'localtime')""")

        rows = q("""SELECT guild_id, user_id, level, progress, out_of FROM users
            WHERE out_of > 0 AND progress > 0 AND level = 0
            AND total_xp = 0 AND total_messages = 0""")
        add("Data", "Has progress but zero stats", not rows,
            f"{len(rows)} row(s)",
            sql="""SELECT guild_id, user_id, level, progress, out_of FROM users
WHERE out_of > 0 AND progress > 0 AND level = 0
  AND total_xp = 0 AND total_messages = 0""")

        rows = q("""SELECT guild_id, user_id FROM users
            WHERE display_name IS NOT NULL AND LENGTH(display_name) > 32""")
        add("Data", "Display names > 32 chars", not rows,
            f"{len(rows)} row(s)",
            sql="""SELECT guild_id, user_id FROM users
WHERE display_name IS NOT NULL AND LENGTH(display_name) > 32""")

        rows = q("""SELECT guild_id, user_id FROM users
            WHERE username IS NOT NULL AND LENGTH(username) > 32""")
        add("Data", "Usernames > 32 chars", not rows,
            f"{len(rows)} row(s)",
            sql="""SELECT guild_id, user_id FROM users
WHERE username IS NOT NULL AND LENGTH(username) > 32""")

        rows = q("""SELECT lr.guild_id, lr.level, lr.role_id
            FROM level_roles lr
            LEFT JOIN guild_settings gs ON gs.guild_id = lr.guild_id
            WHERE gs.guild_id IS NULL""")
        add("Data", "Level roles without guild settings", not rows,
            f"{len(rows)} role(s)", fix="orphan_level_roles" if rows else None,
            sql="""SELECT lr.guild_id, lr.level, lr.role_id
FROM level_roles lr
LEFT JOIN guild_settings gs ON gs.guild_id = lr.guild_id
WHERE gs.guild_id IS NULL""")

        rows = q("""SELECT lr1.guild_id, lr1.level
            FROM level_roles lr1
            JOIN level_roles lr2 ON lr1.guild_id = lr2.guild_id AND lr1.level = lr2.level
            AND lr1.rowid != lr2.rowid""")
        add("Data", "Duplicate level roles", not rows,
            f"{len(rows)} duplicate(s)",
            sql="""SELECT lr1.guild_id, lr1.level
FROM level_roles lr1
JOIN level_roles lr2
  ON lr1.guild_id = lr2.guild_id AND lr1.level = lr2.level AND lr1.rowid != lr2.rowid""")

        rows = q("""SELECT gs.guild_id FROM guild_settings gs
            LEFT JOIN (SELECT DISTINCT guild_id FROM level_roles) lr ON lr.guild_id = gs.guild_id
            WHERE gs.level_channel_id IS NOT NULL AND gs.level_channel_id != 0
            AND lr.guild_id IS NULL""")
        add("Info", "Guilds with level channel but no level roles", True,
            f"{len(rows)} guild(s)",
            sql="""SELECT gs.guild_id FROM guild_settings gs
LEFT JOIN (SELECT DISTINCT guild_id FROM level_roles) lr ON lr.guild_id = gs.guild_id
WHERE gs.level_channel_id IS NOT NULL AND gs.level_channel_id != 0
  AND lr.guild_id IS NULL""")

        rows = q("SELECT guild_id FROM guild_settings WHERE qotd_enabled=1 AND (qotd_channel IS NULL OR qotd_channel=0)")
        add("Data", "QOTD enabled but no channel", not rows,
            f"{len(rows)} guild(s) cannot post", fix="qotd_disable" if rows else None,
            sql="SELECT guild_id FROM guild_settings\nWHERE qotd_enabled = 1 AND (qotd_channel IS NULL OR qotd_channel = 0)")

        bad_times = [r for r in q("SELECT guild_id, qotd_time FROM guild_settings")
                     if not _valid_qotd_time(r["qotd_time"])]
        add("Data", "Invalid QOTD post time", not bad_times,
            f"{len(bad_times)} guild(s)", fix="qotd_time" if bad_times else None,
            sql="SELECT guild_id, qotd_time FROM guild_settings")

        bad_tzs = [r for r in q("SELECT guild_id, qotd_tz FROM guild_settings")
                   if not _valid_tz(r["qotd_tz"])]
        add("Data", "Invalid QOTD timezone", not bad_tzs,
            f"{len(bad_tzs)} guild(s)", fix="qotd_tz" if bad_tzs else None,
            sql="SELECT guild_id, qotd_tz FROM guild_settings")

        q_count = _load_qotd_count()
        bad_queues = []
        for r in q("SELECT guild_id, qotd_queue FROM guild_settings"):
            if r["qotd_queue"] is None:
                continue
            ok, reason = _parse_qotd_queue(r["qotd_queue"], q_count)
            if not ok:
                bad_queues.append((r["guild_id"], reason))
        add("Data", "Invalid QOTD queue", not bad_queues,
            f"{len(bad_queues)} guild(s)",
            fix="qotd_queue" if bad_queues else None,
            sql="SELECT guild_id, qotd_queue FROM guild_settings")

        now = int(time.time())
        rows = q("SELECT user_id FROM vote_boosts WHERE last_vote_at > ?", (now,))
        add("Data", "Vote boosts with future last vote", not rows,
            f"{len(rows)} row(s)", fix="future_votes" if rows else None,
            sql="SELECT user_id FROM vote_boosts\nWHERE last_vote_at > strftime('%s', 'now')")

        rows = q("""SELECT guild_id, role_id FROM level_roles WHERE level < 0""")
        add("Data", "Level roles below level 0", not rows,
            f"{len(rows)} role(s)", fix="level_role_neg" if rows else None,
            sql="SELECT guild_id, role_id FROM level_roles WHERE level < 0")

        rows = q("""SELECT guild_id, user_id FROM users
            WHERE rated NOT IN (0, 1) OR prompt_sent NOT IN (0, 1)""")
        add("Data", "Invalid boolean flags", not rows,
            f"{len(rows)} row(s)", fix="bools" if rows else None,
            sql="""SELECT guild_id, user_id FROM users
WHERE rated NOT IN (0, 1) OR prompt_sent NOT IN (0, 1)""")

        rows = q("""SELECT guild_id FROM guild_settings
            WHERE ai_enabled IS NOT NULL AND ai_enabled NOT IN (0, 1)""")
        add("Data", "Invalid ai_enabled values", not rows,
            f"{len(rows)} guild(s)", fix="bools" if rows else None,
            sql="""SELECT guild_id FROM guild_settings
WHERE ai_enabled IS NOT NULL AND ai_enabled NOT IN (0, 1)""")

        rows = q("SELECT guild_id FROM guild_settings WHERE qotd_enabled=1 AND (qotd_role_id IS NULL OR qotd_role_id=0)")
        add("Info", "QOTD enabled without ping role", True,
            f"{len(rows)} guild(s) (role is optional)",
            sql="SELECT guild_id FROM guild_settings\nWHERE qotd_enabled = 1 AND (qotd_role_id IS NULL OR qotd_role_id = 0)")

        rows = q("""SELECT guild_id, user_id FROM users
            WHERE vc_minutes > 0 AND vc_xp_minutes = 0""")
        add("Info", "Users with VC time but no VC XP", True,
            f"{len(rows)} row(s)",
            sql="SELECT guild_id, user_id FROM users\nWHERE vc_minutes > 0 AND vc_xp_minutes = 0")

        for table in ("vote_boosts", "user_blocks", "user_prefs", "vote_reminders", "user_ratings", "playlists"):
            try:
                rows = q(f"""SELECT user_id FROM {table}
                    WHERE user_id IS NOT NULL
                    AND user_id NOT IN (SELECT DISTINCT user_id FROM users)""")
            except Exception:
                continue
            if rows:
                add("Info", f"Orphan rows in {table}", True,
                    f"{len(rows)} user(s) not in users table",
                    sql=f"SELECT user_id FROM {table}\nWHERE user_id NOT IN (SELECT DISTINCT user_id FROM users)")

        try:
            rows = q("SELECT playlist_id FROM playlist_tracks WHERE playlist_id NOT IN (SELECT id FROM playlists)")
        except Exception:
            rows = []
        if rows:
            add("Info", "Orphan rows in playlist_tracks", True,
                f"{len(rows)} track(s) pointing at missing playlists",
                sql="SELECT playlist_id FROM playlist_tracks\nWHERE playlist_id NOT IN (SELECT id FROM playlists)")

        now = int(time.time())
        rows = q("SELECT user_id FROM vote_reminders WHERE remind_at IS NOT NULL AND remind_at <= ?", (now,))
        if rows:
            add("Info", "Stale vote reminders owed", True,
                f"{len(rows)} reminder(s) waiting to be sent",
                sql="SELECT user_id FROM vote_reminders\nWHERE remind_at IS NOT NULL AND remind_at <= strftime('%s', 'now')")

        rows = q("SELECT user_id, feature FROM user_blocks WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        add("Info", "Expired user blocks", True,
            f"{len(rows)} block(s) ignored but kept",
            fix="purge_expired_blocks" if rows else None,
            sql="SELECT user_id, feature FROM user_blocks\nWHERE expires_at IS NOT NULL AND expires_at <= strftime('%s', 'now')")

        rows = q("""SELECT guild_id, last_qotd_date FROM guild_settings
            WHERE last_qotd_date != '' AND date(last_qotd_date) > date('now', 'localtime')""")
        if rows:
            add("Info", "QOTD last posted in the future", True,
                f"{len(rows)} guild(s)",
                sql="""SELECT guild_id, last_qotd_date FROM guild_settings
WHERE last_qotd_date != ''
  AND date(last_qotd_date) > date('now', 'localtime')""")

        rows = q("""SELECT guild_id FROM guild_settings
            WHERE delete_old_qotd = 1 AND last_qotd_id IS NOT NULL
            AND (last_qotd_thread_id IS NULL OR last_qotd_thread_id = 0)""")
        if rows:
            add("Info", "QOTD cleanup needs a thread id", True,
                f"{len(rows)} guild(s) may not clean up the old message",
                sql="""SELECT guild_id FROM guild_settings
WHERE delete_old_qotd = 1 AND last_qotd_id IS NOT NULL
  AND (last_qotd_thread_id IS NULL OR last_qotd_thread_id = 0)""")

        queued = [r for r in q("SELECT qotd_queue FROM guild_settings WHERE qotd_queue IS NOT NULL")
                  if _parse_qotd_queue(r["qotd_queue"])[0]]
        total_queued = sum(len(json.loads(r["qotd_queue"])) for r in queued)
        add("Info", "Questions left in QOTD queues", True,
            f"{total_queued} across {len(queued)} guild(s)",
            sql="SELECT qotd_queue FROM guild_settings WHERE qotd_queue IS NOT NULL")

        rows = q("""SELECT guild_id FROM users GROUP BY guild_id HAVING COUNT(*) < 50""")
        add("Info", "Servers with under 50 tracked users", True, f"{len(rows)} guild(s)",
            sql="SELECT guild_id FROM users GROUP BY guild_id HAVING COUNT(*) < 50")

        total_xp = q("SELECT COALESCE(SUM(total_xp),0) FROM users")[0][0]
        total_msgs_xp = q("SELECT COALESCE(SUM(total_messages_xp),0) FROM users")[0][0]
        if total_xp > 0:
            msg_ratio = round(total_msgs_xp / total_xp * 100, 1)
            add("Info", "Message XP share of total XP", True, f"{msg_ratio}%",
                sql="SELECT COALESCE(SUM(total_messages_xp),0) * 100.0 /\n     COALESCE(SUM(total_xp),0) AS msg_xp_pct\nFROM users")

        try:
            r = subprocess.run(["systemctl", "is-active", "voidwave.service"],
                               capture_output=True, text=True, timeout=2)
            bot_active = r.stdout.strip() == "active"
        except Exception:
            bot_active = None
        add("Info", "Bot service running", bot_active,
            "voidwave.service" if bot_active is not None else "could not check",
            sql="systemctl is-active voidwave.service")

        try:
            r = subprocess.run(["systemctl", "is-active", "voidwave_website.service"],
                               capture_output=True, text=True, timeout=2)
            web_active = r.stdout.strip() == "active"
        except Exception:
            web_active = None
        add("Info", "Website service running", web_active,
            "voidwave_website.service" if web_active is not None else "could not check",
            sql="systemctl is-active voidwave_website.service")

        db_path = Path("database.db")
        if db_path.exists():
            db_kb = db_path.stat().st_size / 1024
            add("Info", "Database file size", db_kb < 102400,
                f"{db_kb:.1f} KB" + (" (large!)" if db_kb >= 102400 else ""),
                sql="-- File system check: stat database.db")

        rows = q("SELECT COUNT(*) c FROM admin_rate_limits")
        if rows and rows[0]["c"] > 0:
            add("Info", "Rate limit entries", True, f"{rows[0]['c']} tracked IP(s)",
                sql="SELECT COUNT(*) c FROM admin_rate_limits")

        rows = q("SELECT COUNT(*) c FROM admin_login_codes WHERE expires_at > ?", (int(time.time()),))
        if rows and rows[0]["c"] > 0:
            add("Info", "Pending 2FA codes", True, f"{rows[0]['c']} active",
                sql="SELECT COUNT(*) c FROM admin_login_codes\nWHERE expires_at > strftime('%s', 'now')")

        for suffix in ("-wal", "-shm"):
            p = Path("database.db" + suffix)
            if p.exists():
                add("Info", f"database.db{suffix} present", True, f"{p.stat().st_size/1024:.1f} KB",
                    sql=f"-- File system check: stat database.db{suffix}")
    finally:
        conn.close()
    return results


@admin_bp.route("/check")
def check():
    results = _run_checks()
    return render_template("admin_check.html", results=results)


@admin_bp.route("/check/fix/<kind>", methods=["POST"])
def check_fix(kind):
    conn = _db()
    changed = 0
    executed_sql = []
    try:
        cur = conn.cursor()
        if kind == "normalize":
            executed_sql.append(
                "SELECT guild_id, user_id, level, progress, out_of FROM users WHERE progress >= out_of"
            )
            rows = cur.execute(
                "SELECT guild_id, user_id, level, progress, out_of FROM users WHERE progress >= out_of"
            ).fetchall()
            for r in rows:
                level, progress, out_of = _normalize_progress(r["level"], r["progress"], r["out_of"])
                stmt = "UPDATE users SET level=%d, progress=%d, out_of=%d WHERE guild_id=%d AND user_id=%d" % (
                    level, progress, out_of, r["guild_id"], r["user_id"])
                executed_sql.append(stmt)
                cur.execute(
                    "UPDATE users SET level=?, progress=?, out_of=? WHERE guild_id=? AND user_id=?",
                    (level, progress, out_of, r["guild_id"], r["user_id"])
                )
                changed += 1
        elif kind == "negatives":
            executed_sql.append("""UPDATE users SET level=MAX(level,0), progress=MAX(progress,0),
                out_of=MAX(out_of,0), total_messages=MAX(total_messages,0),
                total_messages_xp=MAX(total_messages_xp,0), total_xp=MAX(total_xp,0),
                vc_minutes=MAX(vc_minutes,0), vc_xp_minutes=MAX(vc_xp_minutes,0)""")
            cur.execute("""UPDATE users SET level=MAX(level,0), progress=MAX(progress,0),
                out_of=MAX(out_of,0), total_messages=MAX(total_messages,0),
                total_messages_xp=MAX(total_messages_xp,0), total_xp=MAX(total_xp,0),
                vc_minutes=MAX(vc_minutes,0), vc_xp_minutes=MAX(vc_xp_minutes,0)""")
            changed = cur.rowcount
        elif kind == "out_of":
            executed_sql.append("UPDATE users SET out_of = 100 + level * 20 WHERE out_of <= 0")
            cur.execute("UPDATE users SET out_of = 100 + level * 20 WHERE out_of <= 0")
            changed = cur.rowcount
        elif kind == "nulls":
            for col, val in [("level", 0), ("progress", 0), ("out_of", 100),
                             ("total_messages", 0), ("total_messages_xp", 0), ("total_xp", 0),
                             ("vc_minutes", 0), ("vc_xp_minutes", 0),
                             ("command_uses", 0), ("rated", 0), ("prompt_sent", 0),
                             ("last_message", "")]:
                executed_sql.append(f"UPDATE users SET {col}={val!r} WHERE {col} IS NULL")
                cur.execute(f"UPDATE users SET {col}=? WHERE {col} IS NULL", (val,))
            executed_sql.append("DELETE FROM users WHERE user_id IS NULL OR guild_id IS NULL")
            cur.execute("DELETE FROM users WHERE user_id IS NULL OR guild_id IS NULL")
            changed = cur.rowcount
        elif kind == "guild_schema":
            cols = {r["name"] for r in cur.execute("PRAGMA table_info(guild_settings)")}
            for col, ddl in _GUILD_SCHEMA_FIXES:
                if col not in cols:
                    stmt = f"ALTER TABLE guild_settings ADD COLUMN {col} {ddl}"
                    executed_sql.append(stmt)
                    cur.execute(stmt)
                    changed += 1
        elif kind == "vote_boost_schema":
            cols = {r["name"] for r in cur.execute("PRAGMA table_info(vote_boosts)")}
            for col, ddl in _VOTE_BOOST_SCHEMA_FIXES:
                if col not in cols:
                    stmt = f"ALTER TABLE vote_boosts ADD COLUMN {col} {ddl}"
                    executed_sql.append(stmt)
                    cur.execute(stmt)
                    changed += 1
        elif kind == "qotd_disable":
            executed_sql.append("UPDATE guild_settings SET qotd_enabled = 0 WHERE qotd_enabled = 1 AND (qotd_channel IS NULL OR qotd_channel = 0)")
            cur.execute("UPDATE guild_settings SET qotd_enabled = 0 WHERE qotd_enabled = 1 AND (qotd_channel IS NULL OR qotd_channel = 0)")
            changed = cur.rowcount
        elif kind == "qotd_time":
            bad = [r["guild_id"] for r in cur.execute("SELECT guild_id, qotd_time FROM guild_settings")
                   if not _valid_qotd_time(r["qotd_time"])]
            for gid in bad:
                stmt = f"UPDATE guild_settings SET qotd_time = NULL WHERE guild_id = {gid}"
                executed_sql.append(stmt)
                cur.execute("UPDATE guild_settings SET qotd_time = NULL WHERE guild_id = ?", (gid,))
            changed = len(bad)
        elif kind == "qotd_tz":
            bad = [r["guild_id"] for r in cur.execute("SELECT guild_id, qotd_tz FROM guild_settings")
                   if not _valid_tz(r["qotd_tz"])]
            for gid in bad:
                stmt = f"UPDATE guild_settings SET qotd_tz = NULL WHERE guild_id = {gid}"
                executed_sql.append(stmt)
                cur.execute("UPDATE guild_settings SET qotd_tz = NULL WHERE guild_id = ?", (gid,))
            changed = len(bad)
        elif kind == "qotd_queue":
            q_count = _load_qotd_count()
            bad = [r["guild_id"] for r in cur.execute("SELECT guild_id, qotd_queue FROM guild_settings")
                   if r["qotd_queue"] is not None
                   and not _parse_qotd_queue(r["qotd_queue"], q_count)[0]]
            for gid in bad:
                stmt = f"UPDATE guild_settings SET qotd_queue = NULL WHERE guild_id = {gid}"
                executed_sql.append(stmt)
                cur.execute("UPDATE guild_settings SET qotd_queue = NULL WHERE guild_id = ?", (gid,))
            changed = len(bad)
        elif kind == "future_votes":
            executed_sql.append("UPDATE vote_boosts SET last_vote_at = NULL WHERE last_vote_at > strftime('%s', 'now')")
            cur.execute("UPDATE vote_boosts SET last_vote_at = NULL WHERE last_vote_at > ?", (int(time.time()),))
            changed = cur.rowcount
        elif kind == "level_role_neg":
            executed_sql.append("DELETE FROM level_roles WHERE level < 0")
            cur.execute("DELETE FROM level_roles WHERE level < 0")
            changed = cur.rowcount
        elif kind == "bools":
            for table, col in (("users", "rated"), ("users", "prompt_sent"), ("guild_settings", "ai_enabled")):
                stmt = f"UPDATE {table} SET {col} = 0 WHERE {col} IS NOT NULL AND {col} NOT IN (0, 1)"
                executed_sql.append(stmt)
                cur.execute(stmt)
                changed += cur.rowcount
        elif kind == "purge_expired_blocks":
            executed_sql.append("DELETE FROM user_blocks WHERE expires_at IS NOT NULL AND expires_at <= strftime('%s', 'now')")
            cur.execute("DELETE FROM user_blocks WHERE expires_at IS NOT NULL AND expires_at <= ?", (int(time.time()),))
            changed = cur.rowcount
        elif kind == "empty":
            executed_sql.append("""DELETE FROM users
                WHERE level=0 AND total_xp=0 AND total_messages=0 AND vc_minutes=0 AND last_message=''""")
            cur.execute("""DELETE FROM users
                WHERE level=0 AND total_xp=0 AND total_messages=0 AND vc_minutes=0 AND last_message=''""")
            changed = cur.rowcount
        elif kind == "expired_boosts":
            executed_sql.append(f"DELETE FROM vote_boosts WHERE expires_at <= {int(time.time())}")
            cur.execute("DELETE FROM vote_boosts WHERE expires_at <= ?", (int(time.time()),))
            changed = cur.rowcount
        elif kind == "orphan_level_roles":
            executed_sql.append("""DELETE FROM level_roles
                WHERE guild_id NOT IN (SELECT DISTINCT guild_id FROM guild_settings)""")
            cur.execute("""DELETE FROM level_roles
                WHERE guild_id NOT IN (SELECT DISTINCT guild_id FROM guild_settings)""")
            changed = cur.rowcount
        elif kind == "future_timestamps":
            executed_sql.append("""UPDATE users SET last_message = ''
                WHERE last_message != '' AND date(last_message) > date('now', 'localtime')""")
            cur.execute("""UPDATE users SET last_message = ''
                WHERE last_message != '' AND date(last_message) > date('now', 'localtime')""")
            changed = cur.rowcount
        else:
            abort(404)
        conn.commit()
        _clear_cache()
    finally:
        conn.close()

    session["last_fix_sql"] = "\n".join(executed_sql)
    session["last_fix_result"] = f"{kind}: {changed} row(s) affected"

    _log("CHECK FIX", f"kind={kind} rows={changed}")
    flash(f"Fixed {kind}: {changed} row(s) affected", "success")
    return redirect(url_for("admin.check"))


@admin_bp.route("/check/fix-sql")
def check_fix_sql():
    sql = session.get("last_fix_sql", "")
    result = session.get("last_fix_result", "")
    return jsonify({"sql": sql, "result": result})
