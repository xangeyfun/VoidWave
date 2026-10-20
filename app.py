import base64
import hashlib
import hmac
import json
import logging
import math
import os
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request

from admin import admin_bp
from logconf import setup_logging
from outage import announcement as outage_announcement

setup_logging()

logger = logging.getLogger("app")

load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.getenv('SECRET_KEY')

# Session hardening for the /admin panel
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

app.register_blueprint(admin_bp)

cache = {}
CACHE_TTL = 15

def cached_query(key, query, params=(), ttl=CACHE_TTL):
    now = time.time()
    if key in cache and now - cache[key]['time'] < ttl:
        return cache[key]['data']
    conn = get_db()
    try:
        cur = conn.cursor()
        result = cur.execute(query, params).fetchall()
        cache[key] = {'data': result, 'time': now}
        return result
    finally:
        conn.close()

STATS_HISTORY_FILE = Path('stats_history.json')
STORY_KEYS = ['total_guilds', 'total_members', 'total_users', 'total_xp', 'total_messages', 'total_vc_minutes']
RANGE_DAYS = {'24h': 1, '7d': 7, '30d': 30, '90d': 90, 'all': None}

_history_cache = {'key': None, 'data': []}

def _load_stats_history():
    try:
        st = STATS_HISTORY_FILE.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return []
    if _history_cache['key'] != key:
        try:
            with open(STATS_HISTORY_FILE, 'r') as f:
                _history_cache['data'] = json.load(f)
            _history_cache['key'] = key
        except (json.JSONDecodeError, IOError):
            _history_cache['data'] = []
            _history_cache['key'] = key
    return _history_cache['data']

def _lttb_indices(ts, vals, target):
    n = len(vals)
    if target >= n or target < 3:
        return list(range(n))
    idxs = [0]
    every = (n - 2) / (target - 2)
    a = 0
    for i in range(target - 2):
        avg_start = int(1 + i * every)
        avg_end = min(int(1 + (i + 1) * every) + 1, n)
        if avg_end <= avg_start:
            avg_end = avg_start + 1
        avg_x = 0.0
        avg_y = 0.0
        for j in range(avg_start, avg_end):
            avg_x += ts[j]
            avg_y += vals[j]
        cnt = avg_end - avg_start
        avg_x /= cnt
        avg_y /= cnt
        r_start = int(1 + (i + 1) * every)
        r_end = min(int(1 + (i + 2) * every) + 1, n)
        if r_end <= r_start:
            r_end = r_start + 1
        xa = ts[a]
        ya = vals[a]
        best_area = -1.0
        best = -1
        for j in range(r_start, r_end):
            area = abs((xa - avg_x) * (vals[j] - ya) - (xa - ts[j]) * (avg_y - ya))
            if area > best_area:
                best_area = area
                best = j
        if best < 0:
            best = r_start
        idxs.append(best)
        a = best
    idxs.append(n - 1)
    return idxs

def _snap_ts_ms(snap):
    return datetime.fromisoformat(snap['timestamp']).timestamp() * 1000

def _range_history(history, range_name):
    days = RANGE_DAYS.get(range_name)
    if not days:
        return history
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    return [s for s in history if s.get('timestamp', '') >= cutoff]

_sysctl_cache = {'key': None, 'data': None, 'time': 0}
_SYSCTL_TTL = 5

def _service_status(service):
    now = time.time()
    if _sysctl_cache['key'] != service or now - _sysctl_cache['time'] > _SYSCTL_TTL:
        status = {'active': None, 'uptime': None}
        try:
            r = subprocess.run(['systemctl', 'is-active', service],
                               capture_output=True, text=True, timeout=2)
            status['active'] = r.stdout.strip() == 'active'
            if status['active']:
                ts = subprocess.run(['systemctl', 'show', service, '-p', 'ActiveEnterTimestamp', '--value'],
                                    capture_output=True, text=True, timeout=2).stdout.strip()
                m = re.search(r'(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})', ts)
                if m:
                    status['uptime'] = datetime.now() - datetime(*map(int, m.groups()))
        except Exception:
            status['active'] = None
        _sysctl_cache['key'] = service
        _sysctl_cache['data'] = status
        _sysctl_cache['time'] = now
    return _sysctl_cache['data']

def _fmt_uptime(delta):
    if not delta or delta.total_seconds() < 0:
        return None
    total = int(delta.total_seconds())
    d, rem = divmod(total, 86400)
    h, m = divmod(rem, 3600)
    m //= 60
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"

def _fmt_last_active(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            seconds = (datetime.now() - dt).total_seconds()
        else:
            seconds = (datetime.now(dt.tzinfo) - dt).total_seconds()
    except (ValueError, TypeError):
        return None
    if seconds < 0:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 604800:
        return f"{int(seconds // 86400)}d ago"
    return f"{int(seconds // 604800)}w ago"

_db_health_cache = {'time': 0, 'data': None}
_DB_HEALTH_TTL = 60

def _db_health():
    now = time.time()
    if now - _db_health_cache['time'] < _DB_HEALTH_TTL:
        return _db_health_cache['data']
    info = {'ok': False, 'size_mb': None, 'detail': 'could not check'}
    try:
        p = Path('database.db')
        if not p.exists():
            info['detail'] = 'file missing'
        else:
            info['size_mb'] = round(p.stat().st_size / 1024 / 1024, 1)
            conn = get_db()
            try:
                rows = conn.execute("PRAGMA quick_check").fetchall()
                failures = [str(r[0]) for r in rows if r[0] != 'ok']
                info['ok'] = not failures
                info['detail'] = (f"{info['size_mb']} MB" if info['ok']
                                  else ', '.join(failures)[:60])
            finally:
                conn.close()
    except Exception as e:
        info['detail'] = str(e)[:60]
    _db_health_cache['time'] = now
    _db_health_cache['data'] = info
    return info

@app.before_request
def remove_trailing_slash():
    if request.path != '/' and request.path.endswith('/') and not request.path.startswith('/admin'):
        return redirect(request.path[:-1])

@app.context_processor
def inject_outage():
    """Expose the active outage announcement to every template (None once past)."""
    return {'outage': outage_announcement()}

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def _level_from_xp(total_xp):
    if not total_xp or total_xp <= 0:
        return 0
    return int((-90 + math.isqrt(8100 + 40 * int(total_xp))) // 20)

PERIOD_DAYS = {'daily': 1, 'weekly': 7, 'monthly': 30}
PERIOD_SORT_COLUMNS = {'level': 'xp', 'total_xp': 'xp', 'total_messages': 'messages', 'vc_minutes': 'vc_minutes'}

def _period_start_day(period):
    """Earliest UTC day (inclusive) for a period label, or None for all time."""
    days = PERIOD_DAYS.get(period)
    if not days:
        return None
    return int(time.time() // 86400) - (days - 1)

def _xp_for_level(level):
    return 10 * level * level + 90 * level

def _get_combined_user_stats(user_id: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        agg = cur.execute(
            "SELECT SUM(total_xp), SUM(total_messages), SUM(total_messages_xp), "
            "SUM(vc_minutes), SUM(vc_xp_minutes), SUM(command_uses) "
            "FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
        latest = cur.execute(
            "SELECT username, display_name, avatar_hash, last_message FROM users "
            "WHERE user_id=? ORDER BY last_message DESC, rowid DESC LIMIT 1",
            (user_id,)
        ).fetchone()

        if not agg or agg[0] is None:
            return None

        total_xp = agg[0] or 0
        level = _level_from_xp(total_xp)
        progress = max(0, total_xp - _xp_for_level(level))
        out_of = 100 + level * 20

        rank = cur.execute(
            "SELECT COUNT(*) + 1 FROM (SELECT user_id, SUM(total_xp) AS x FROM users GROUP BY user_id) WHERE x > ?",
            (total_xp,)
        ).fetchone()[0]

        total_users = cur.execute("SELECT COUNT(DISTINCT user_id) FROM users").fetchone()[0]

        above = cur.execute(
            "SELECT x FROM (SELECT user_id, SUM(total_xp) AS x FROM users GROUP BY user_id) WHERE x > ? ORDER BY x ASC LIMIT 1",
            (total_xp,)
        ).fetchone()

        return {
            'username': (latest[0] if latest else None),
            'display_name': latest[1] if latest else None,
            'level': level,
            'progress': progress,
            'out_of': out_of,
            'total_xp': total_xp,
            'total_messages': agg[1] or 0,
            'total_messages_xp': agg[2] or 0,
            'vc_minutes': agg[3] or 0,
            'vc_xp_minutes': agg[4] or 0,
            'command_uses': agg[5] or 0,
            'last_message': (latest[3] if latest else "") or "",
            'avatar_hash': latest[2] if latest else None,
            'rank': rank,
            'global_rank': rank,
            'server_total': total_users,
            'global_total': total_users,
            'xp_to_overtake': (above[0] - total_xp) if above else None
        }
    except Exception as e:
        logger.error("Error fetching combined user stats: %s", e)
        return None
    finally:
        conn.close()

def get_user_stats(user_id: int, guild_id: int):
    if guild_id == 0:
        return _get_combined_user_stats(user_id)
    conn = get_db()
    try:
        cur = conn.cursor()
        
        user = cur.execute(
            "SELECT * FROM users WHERE user_id=? AND guild_id=?",
            (user_id, guild_id)
        ).fetchone()
        
        if not user:
            return None
        
        rank = cur.execute(
            "SELECT COUNT(*) + 1 FROM users WHERE guild_id=? AND total_xp > ?",
            (guild_id, user['total_xp'])
        ).fetchone()[0]
        
        global_rank = cur.execute(
            "SELECT COUNT(*) + 1 FROM users WHERE total_xp > ?",
            (user['total_xp'],)
        ).fetchone()[0]

        server_total = cur.execute(
            "SELECT COUNT(*) FROM users WHERE guild_id=?", (guild_id,)
        ).fetchone()[0]

        global_total = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]

        above = cur.execute(
            "SELECT total_xp FROM users WHERE guild_id=? AND total_xp > ? ORDER BY total_xp ASC LIMIT 1",
            (guild_id, user['total_xp'])
        ).fetchone()

        return {
            'username': user['username'],
            'display_name': user['display_name'],
            'level': user['level'],
            'progress': user['progress'],
            'out_of': user['out_of'],
            'total_xp': user['total_xp'],
            'total_messages': user['total_messages'],
            'total_messages_xp': user['total_messages_xp'],
            'vc_minutes': user['vc_minutes'],
            'vc_xp_minutes': user['vc_xp_minutes'],
            'command_uses': user['command_uses'],
            'last_message': user['last_message'],
            'avatar_hash': user['avatar_hash'],
            'rank': rank,
            'global_rank': global_rank,
            'server_total': server_total,
            'global_total': global_total,
            'xp_to_overtake': (above[0] - user['total_xp']) if above else None
        }
    except Exception as e:
        logger.error("Error fetching user stats: %s", e)
        return None
    finally:
        conn.close()

def _period_leaderboard(guild_id, sort_by, direction, page, per_page, combined, start_day):
    """One page of leaderboard rows summed from per-day buckets for a rolling period."""
    dir_sql = 'DESC' if direction == 'desc' else 'ASC'
    value_col = PERIOD_SORT_COLUMNS[sort_by]
    offset = (page - 1) * per_page

    if combined:
        total_rows = cached_query(
            f"lbp_total:combined:{start_day}",
            "SELECT COUNT(DISTINCT user_id) FROM user_stats_daily WHERE day >= ?",
            (start_day,)
        )
        total = total_rows[0][0] if total_rows else 0
        entries = cached_query(
            f"lbp:combined:{sort_by}:{dir_sql}:{page}:{per_page}:{start_day}",
            f"SELECT d.user_id, u.guild_id, u.username, u.display_name, u.avatar_hash, "
            f"SUM(d.xp) AS xp, SUM(d.messages) AS messages, SUM(d.vc_minutes) AS vc_minutes "
            f"FROM user_stats_daily d "
            f"JOIN (SELECT user_id, guild_id, username, display_name, avatar_hash, "
            f"ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY last_message DESC, rowid DESC) AS rn "
            f"FROM users) u ON u.user_id = d.user_id AND u.rn = 1 "
            f"WHERE d.day >= ? GROUP BY d.user_id "
            f"ORDER BY {value_col} {dir_sql}, xp DESC, d.user_id ASC LIMIT ? OFFSET ?",
            (start_day, per_page, offset)
        )
    else:
        where_sql = 'WHERE d.guild_id=? AND d.day>=?' if guild_id else 'WHERE d.day>=?'
        params = (guild_id, start_day) if guild_id else (start_day,)
        total_rows = cached_query(
            f"lbp_total:{guild_id}:{start_day}",
            f"SELECT COUNT(*) FROM (SELECT 1 FROM user_stats_daily d {where_sql} GROUP BY d.guild_id, d.user_id)",
            params
        )
        total = total_rows[0][0] if total_rows else 0
        entries = cached_query(
            f"lbp:{guild_id}:{sort_by}:{dir_sql}:{page}:{per_page}:{start_day}",
            f"SELECT d.user_id, d.guild_id, u.username, u.display_name, u.avatar_hash, "
            f"SUM(d.xp) AS xp, SUM(d.messages) AS messages, SUM(d.vc_minutes) AS vc_minutes "
            f"FROM user_stats_daily d "
            f"JOIN users u ON u.guild_id = d.guild_id AND u.user_id = d.user_id "
            f"{where_sql} GROUP BY d.guild_id, d.user_id "
            f"ORDER BY {value_col} {dir_sql}, xp DESC, d.user_id ASC LIMIT ? OFFSET ?",
            params + (per_page, offset)
        )

    rows = []
    for entry in entries:
        row = dict(entry)
        row['level'] = _level_from_xp(row['xp'])
        row['total_xp'] = row['xp']
        row['total_messages'] = row['messages']
        row['guild_id'] = 0 if combined else row['guild_id']
        rows.append(row)
    return rows, total


def get_leaderboard(guild_id: int = 0, sort_by: str = 'level', direction: str = 'desc', page: int = 1, per_page: int = 25, combined: bool = False, period: str = 'all'):
    valid_sorts = {'level', 'total_xp', 'total_messages', 'vc_minutes'}
    if sort_by not in valid_sorts:
        sort_by = 'level'

    start_day = _period_start_day(period)
    if start_day is not None:
        return _period_leaderboard(guild_id, sort_by, direction, page, per_page, combined, start_day)

    dir_sql = 'DESC' if direction == 'desc' else 'ASC'

    if combined:
        total_rows = cached_query("lb_total:combined", "SELECT COUNT(DISTINCT user_id) FROM users")
        total = total_rows[0][0] if total_rows else 0

        offset = (page - 1) * per_page
        sort_column = 'total_xp' if sort_by == 'level' else sort_by
        entries = cached_query(
            f"lb:combined:{sort_by}:{dir_sql}:{page}:{per_page}",
            f"SELECT user_id, guild_id, username, display_name, avatar_hash, "
            f"total_xp, total_messages, vc_minutes FROM ("
            f"SELECT user_id, guild_id, username, display_name, avatar_hash, "
            f"SUM(total_xp) OVER (PARTITION BY user_id) AS total_xp, "
            f"SUM(total_messages) OVER (PARTITION BY user_id) AS total_messages, "
            f"SUM(vc_minutes) OVER (PARTITION BY user_id) AS vc_minutes, "
            f"ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY last_message DESC, rowid DESC) AS rn "
            f"FROM users) WHERE rn = 1 ORDER BY {sort_column} {dir_sql} LIMIT ? OFFSET ?",
            (per_page, offset)
        )

        rows = []
        for entry in entries:
            row = dict(entry)
            row['guild_id'] = 0
            row['level'] = _level_from_xp(row['total_xp'] or 0)
            rows.append(row)
        return rows, total

    where_sql = 'WHERE guild_id=?' if guild_id else ''
    params = (guild_id,) if guild_id else ()
    
    cache_key = f"lb:{guild_id}:{sort_by}:{dir_sql}:{page}:{per_page}"
    total_key = f"lb_total:{guild_id}"
    
    total_rows = cached_query(total_key, f"SELECT COUNT(*) FROM users {where_sql}", params)
    total = total_rows[0][0] if total_rows else 0
    
    offset = (page - 1) * per_page
    sort_column = {
        'level': 'level',
        'total_xp': 'total_xp',
        'total_messages': 'total_messages',
        'vc_minutes': 'vc_minutes',
    }[sort_by]
    entries = cached_query(
        cache_key,
        f"SELECT * FROM users {where_sql} ORDER BY {sort_column} {dir_sql} LIMIT ? OFFSET ?",
        params + (per_page, offset)
    )
    
    return entries, total

@app.route('/')
def index():
    bot_stats = cached_query('bot_stats', "SELECT * FROM bot_stats")
    if bot_stats:
        bot_stats = bot_stats[0]

    rating_rows = cached_query('rating_agg', """
        SELECT COUNT(*) as total_ratings,
               COALESCE(AVG(rating), 0) as avg_rating
        FROM user_ratings
    """)
    r = rating_rows[0]
    total_ratings = r[0] or 0
    avg_rating = round(r[1] or 0, 1)

    return render_template('index.html', bot_stats=bot_stats,
                           total_ratings=total_ratings,
                           avg_rating=avg_rating), 200

@app.route('/setup')
def setup():
    return render_template('setup.html'), 200

_DOCS_PAGES = {
    'leveling': 'docs_leveling.html',
    'voting': 'docs_voting.html',
    'ai-chat': 'docs_ai_chat.html',
    'qotd': 'docs_qotd.html',
    'music': 'docs_music.html',
    'games': 'docs_games.html',
    'reminders': 'docs_reminders.html',
    'giveaways': 'docs_giveaways.html',
    'moderation': 'docs_moderation.html',
    'config': 'docs_config.html',
    'prefs': 'docs_prefs.html',
}

@app.route('/docs')
def docs():
    return render_template('docs.html'), 200

@app.route('/docs/<slug>')
def docs_category(slug):
    template = _DOCS_PAGES.get(slug)
    if template is None:
        return render_template('404.html'), 404
    return render_template(template), 200

@app.route('/terms')
def terms():
    return render_template('terms.html'), 200

@app.route('/privacy')
def privacy():
    return render_template('privacy.html'), 200

@app.route('/faq')
def faq():
    return render_template('faq.html'), 200

@app.route('/status')
def status_page():
    bot = cached_query('bot_stats', "SELECT * FROM bot_stats")
    bot = dict(bot[0]) if bot else {}

    hist = _load_stats_history()
    latest = hist[-1] if hist else {}
    last_ts = latest.get('timestamp')
    if last_ts:
        try:
            last_ts = datetime.fromisoformat(last_ts).strftime('%b %d, %Y %H:%M')
        except ValueError:
            pass

    bot_svc = _service_status('voidwave.service')
    web_svc = _service_status('voidwave_website.service')
    db = _db_health()

    return render_template('status.html',
        bot_stats=bot,
        latest=latest,
        last_stats_ts=last_ts,
        bot_active=bot_svc['active'],
        bot_uptime=_fmt_uptime(bot_svc['uptime']),
        web_active=web_svc['active'],
        web_uptime=_fmt_uptime(web_svc['uptime']),
        db_ok=db['ok'],
        db_detail=db['detail'],
    ), 200

def _vote_info(user_id):
    """Public profile vote info: lifetime votes, active boost, badge, streak, per-list timers."""
    now = time.time()
    today = int(now // 86400)
    info = {
        "vote_count": 0,
        "boost_minutes": None,
        "badge": None,
        "badge_progress": None,
        "streak": 0,
        "longest_streak": 0,
        "sites": [],
    }
    conn = get_db()
    try:
        row = conn.execute("SELECT vote_count, expires_at FROM vote_boosts WHERE user_id=?", (user_id,)).fetchone()
        try:
            streak_row = conn.execute(
                "SELECT current_streak, longest_streak, last_day FROM vote_streaks WHERE user_id=?",
                (user_id,),
            ).fetchone()
            site_rows = conn.execute(
                "SELECT source, voted_at FROM vote_site_history WHERE user_id=?", (user_id,)
            ).fetchall()
        except sqlite3.OperationalError:
            streak_row = None
            site_rows = []
    finally:
        conn.close()
    if row:
        info["vote_count"] = row["vote_count"] or 0
        info["badge"] = _vote_badge_label(info["vote_count"])
        info["badge_progress"] = _vote_badge_progress(info["vote_count"])
        if row["expires_at"] and row["expires_at"] > now:
            info["boost_minutes"] = int((row["expires_at"] - now) // 60)
    if streak_row:
        if streak_row["last_day"] in (today, today - 1):
            info["streak"] = streak_row["current_streak"] or 0
        info["longest_streak"] = streak_row["longest_streak"] or 0
    history = {site["source"]: site["voted_at"] for site in site_rows}
    for name, url in VOTE_SITE_LINKS:
        voted_at = history.get(name)
        ready_minutes = None
        if voted_at and voted_at + VOTE_SITE_COOLDOWN > now:
            ready_minutes = max(1, int((voted_at + VOTE_SITE_COOLDOWN - now) // 60))
        info["sites"].append({"name": name, "url": url, "ready_minutes": ready_minutes})
    return info


@app.route('/stats/<int:guild_id>/<int:user_id>')
def stats(guild_id: int, user_id: int):
    user_data = get_user_stats(user_id, guild_id)
    
    if not user_data:
        return render_template('stats.html', 
            username='Unknown User',
            display_name='Unknown User',
            level=0,
            progress=0,
            out_of=100,
            total_xp=0,
            total_messages=0,
            rank=0,
            global_rank=0,
            progress_percent=0,
            vc_minutes=0,
            last_active=None,
            server_top_pct=None,
            global_top_pct=None,
            xp_to_overtake=None,
            guild_id=guild_id,
            user_id=user_id,
            avatar_url='https://cdn.discordapp.com/embed/avatars/0.png',
            vote={"vote_count": 0, "boost_minutes": None, "badge": None, "streak": 0, "longest_streak": 0, "sites": []}
        ), 200
    
    progress_percent = (user_data['progress'] / user_data['out_of'] * 100) if user_data['out_of'] > 0 else 0
    
    avatar_ext = 'gif' if (user_data['avatar_hash'] or '').startswith('a_') else 'png'
    avatar_url = f'https://cdn.discordapp.com/avatars/{user_id}/{user_data["avatar_hash"]}.{avatar_ext}?size=128' if user_data['avatar_hash'] else 'https://cdn.discordapp.com/embed/avatars/0.png'
    
    vote = _vote_info(user_id)

    return render_template('stats.html',
        username=user_data['username'],
        display_name=user_data['display_name'] or user_data['username'],
        level=user_data['level'],
        progress=user_data['progress'],
        out_of=user_data['out_of'],
        total_xp=user_data['total_xp'],
        total_messages=user_data['total_messages'],
        rank=user_data['rank'],
        global_rank=user_data['global_rank'],
        progress_percent=progress_percent,
        vc_minutes=user_data['vc_minutes'],
        last_active=_fmt_last_active(user_data['last_message']),
        server_top_pct=round(user_data['rank'] / user_data['server_total'] * 100, 3) if user_data['server_total'] else None,
        global_top_pct=round(user_data['global_rank'] / user_data['global_total'] * 100, 3) if user_data['global_total'] else None,
        xp_to_overtake=user_data['xp_to_overtake'],
        guild_id=guild_id,
        user_id=user_id,
        avatar_url=avatar_url,
        vote=vote
    ), 200

def _lb_find_rank(username_query, guild_id, sort_by, direction, combined=False, period='all'):
    valid_sorts = {'level', 'total_xp', 'total_messages', 'vc_minutes'}
    if sort_by not in valid_sorts:
        sort_by = 'level'
    dir_sql = 'DESC' if direction == 'desc' else 'ASC'

    # A leading @ restricts search to usernames only
    only_username = username_query.startswith('@')
    term = username_query[1:] if only_username else username_query
    if not term:
        return []

    start_day = _period_start_day(period)

    if start_day is not None:
        value_col = PERIOD_SORT_COLUMNS[sort_by]
        if combined:
            base = f"""
                SELECT user_id, guild_id, username, display_name, avatar_hash, rk FROM (
                    SELECT r.user_id, r.guild_id, r.username, r.display_name, r.avatar_hash,
                           ROW_NUMBER() OVER (ORDER BY a.value {dir_sql}, r.user_id ASC) AS rk
                    FROM (
                        SELECT user_id, guild_id, username, display_name, avatar_hash,
                               ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY last_message DESC, rowid DESC) AS rn
                        FROM users
                    ) AS r
                    JOIN (
                        SELECT user_id, SUM({value_col}) AS value FROM user_stats_daily
                        WHERE day >= ? GROUP BY user_id
                    ) AS a ON a.user_id = r.user_id
                    WHERE r.rn = 1
                ) AS ranked
            """
            params = (start_day,)
            key = f"lb_find:combined:{sort_by}:{direction}:{only_username}:{term}:{start_day}"
        else:
            where_sql = 'WHERE d.guild_id=? AND d.day>=?' if guild_id else 'WHERE d.day>=?'
            params = (guild_id, start_day) if guild_id else (start_day,)
            base = f"""
            SELECT user_id, guild_id, username, display_name, avatar_hash, rk FROM (
                SELECT user_id, guild_id, username, display_name, avatar_hash,
                       ROW_NUMBER() OVER (ORDER BY {value_col} {dir_sql}, xp DESC, user_id ASC) AS rk
                FROM (
                    SELECT d.user_id AS user_id, d.guild_id AS guild_id, u.username AS username,
                           u.display_name AS display_name, u.avatar_hash AS avatar_hash,
                           SUM(d.xp) AS xp, SUM(d.messages) AS messages, SUM(d.vc_minutes) AS vc_minutes
                    FROM user_stats_daily d
                    JOIN users u ON u.guild_id = d.guild_id AND u.user_id = d.user_id
                    {where_sql} GROUP BY d.guild_id, d.user_id
                )
            ) AS ranked
            """
            key = f"lb_find:{guild_id}:{sort_by}:{direction}:{only_username}:{term}:{start_day}"
    elif combined:
        sort_column = 'total_xp' if sort_by == 'level' else sort_by
        base = f"""
            SELECT user_id, guild_id, username, display_name, avatar_hash, rk FROM (
                SELECT r.user_id, r.guild_id, r.username, r.display_name, r.avatar_hash,
                       ROW_NUMBER() OVER (ORDER BY a.value {dir_sql}, r.user_id ASC) AS rk
                FROM (
                    SELECT user_id, guild_id, username, display_name, avatar_hash,
                           ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY last_message DESC, rowid DESC) AS rn
                    FROM users
                ) AS r
                JOIN (
                    SELECT user_id, SUM({sort_column}) AS value FROM users GROUP BY user_id
                ) AS a ON a.user_id = r.user_id
                WHERE r.rn = 1
            ) AS ranked
        """
        params = ()
        key = f"lb_find:combined:{sort_by}:{direction}:{only_username}:{term}"
    else:
        where_sql = 'WHERE guild_id=?' if guild_id else ''
        params = (guild_id,) if guild_id else ()
        base = f"""
        SELECT user_id, guild_id, username, display_name, avatar_hash, rk FROM (
            SELECT user_id, guild_id, username, display_name, avatar_hash,
                   ROW_NUMBER() OVER (ORDER BY {sort_by} {dir_sql}) AS rk
            FROM users {where_sql}
        ) AS ranked
        """
        key = f"lb_find:{guild_id}:{sort_by}:{direction}:{only_username}:{term}"

    if only_username:
        order = (
            "LOWER(username) = LOWER(?)",
            "LOWER(username) LIKE LOWER(?)",
        )
    else:
        order = (
            "LOWER(COALESCE(display_name, '')) = LOWER(?)",
            "LOWER(COALESCE(display_name, '')) LIKE LOWER(?)",
            "LOWER(username) = LOWER(?)",
            "LOWER(username) LIKE LOWER(?)",
        )

    for cond in order:
        match = '%' if 'LIKE' in cond else ''
        rows = cached_query(
            key + ':' + cond,
            base + f" WHERE {cond} ORDER BY rk",
            params + (f"{match}{term}{match}",),
            ttl=30
        )
        if rows:
            return [
                {
                    'user_id': r['user_id'],
                    'guild_id': r['guild_id'],
                    'username': r['username'],
                    'display_name': r['display_name'],
                    'avatar_hash': r['avatar_hash'],
                    'rank': r['rk'],
                }
                for r in rows
            ]
    return []

@app.route('/leaderboard')
def leaderboard():
    guild_id = request.args.get('guild', 0, type=int)
    sort_by = request.args.get('sort', 'level')
    direction = request.args.get('dir', 'desc')
    page = request.args.get('page', 1, type=int)
    combined = request.args.get('mode') == 'combined'
    period = (request.args.get('period') or 'all').lower()
    if period not in PERIOD_DAYS:
        period = 'all'

    find_query = (request.args.get('find') or '').strip()
    find_user_id = None
    find_guild_id = None
    find_rank = None
    find_username = None
    find_display_name = None
    find_avatar_hash = None
    find_matches = []
    find_idx = 0

    if find_query:
        matches = _lb_find_rank(find_query, guild_id, sort_by, direction, combined, period)
        if matches:
            find_matches = matches
            find_idx = request.args.get('fi', 0, type=int) % len(matches)
            found = matches[find_idx]
            find_user_id = found['user_id']
            find_guild_id = 0 if combined else found['guild_id']
            find_username = found['username']
            find_display_name = found['display_name']
            find_avatar_hash = found['avatar_hash']
            find_rank = found['rank']
            page = max(1, (find_rank + 49) // 50)
    
    entries, total = get_leaderboard(guild_id=guild_id, sort_by=sort_by, direction=direction, page=page, per_page=50, combined=combined, period=period)
    
    leaderboard_list = []
    for i, entry in enumerate(entries):
        rank = (page - 1) * 50 + i + 1
        leaderboard_list.append({
            'rank': rank,
            'user_id': entry['user_id'],
            'username': entry['username'],
            'display_name': entry['display_name'],
            'avatar_hash': entry['avatar_hash'],
            'guild_id': 0 if combined else entry['guild_id'],
            'level': entry['level'],
            'total_xp': entry['total_xp'],
            'total_messages': entry['total_messages'],
            'vc_minutes': entry['vc_minutes']
        })
    
    total_pages = max(1, (total + 49) // 50)

    start_day = _period_start_day(period)
    if start_day is not None:
        if combined:
            agg = cached_query(
                f"lbp_agg:combined:{start_day}",
                "SELECT COALESCE(SUM(xp),0), COALESCE(SUM(messages),0), COALESCE(SUM(vc_minutes),0) FROM user_stats_daily WHERE day >= ?",
                (start_day,)
            )
        else:
            where = "WHERE guild_id = ? AND day >= ?" if guild_id else "WHERE day >= ?"
            params = (guild_id, start_day) if guild_id else (start_day,)
            agg = cached_query(
                f"lbp_agg:{guild_id}:{start_day}",
                f"SELECT COALESCE(SUM(xp),0), COALESCE(SUM(messages),0), COALESCE(SUM(vc_minutes),0) FROM user_stats_daily {where}",
                params
            )
    elif combined:
        agg = cached_query("lb_agg:combined", "SELECT COALESCE(SUM(total_xp),0), COALESCE(SUM(total_messages),0), COALESCE(SUM(vc_minutes),0) FROM users")
    else:
        where = "WHERE guild_id = ?" if guild_id else ""
        params = (guild_id,) if guild_id else ()
        agg = cached_query(f"lb_agg:{guild_id}", f"SELECT COALESCE(SUM(total_xp),0), COALESCE(SUM(total_messages),0), COALESCE(SUM(vc_minutes),0) FROM users {where}", params)
    
    agg_xp = agg[0][0]
    agg_messages = agg[0][1]
    agg_vc = agg[0][2]
    if agg_vc >= 1440:
        agg_vc_str = f"{agg_vc // 1440:,}d"
    elif agg_vc >= 60:
        agg_vc_str = f"{agg_vc // 60:,}h"
    else:
        agg_vc_str = f"{agg_vc:,}m"
    
    return render_template('leaderboard.html',
        leaderboard=leaderboard_list,
        total=total,
        guild_id=guild_id,
        combined=combined,
        sort_by=sort_by,
        direction=direction,
        period=period,
        page=page,
        total_pages=total_pages,
        agg_xp=f"{agg_xp:,}",
        agg_messages=f"{agg_messages:,}",
        agg_vc=agg_vc_str,
        find_query=find_query,
        find_user_id=find_user_id,
        find_guild_id=find_guild_id,
        find_rank=find_rank,
        find_username=find_username,
        find_display_name=find_display_name,
        find_avatar_hash=find_avatar_hash,
        find_matches=find_matches,
        find_idx=find_idx
    ), 200


def _fmt_ago(ts, now=None):
    now = time.time() if now is None else now
    delta = int(now - ts)
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _avatar_url(user_id, avatar_hash, size=128):
    if not avatar_hash:
        return "https://cdn.discordapp.com/embed/avatars/0.png"
    ext = "gif" if avatar_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size={size}"


@app.route('/voters')
def voters():
    current_month = time.strftime("%Y-%m", time.gmtime())
    today = int(time.time() // 86400)
    per_page = 25
    conn = get_db()
    try:
        try:
            month_rows = conn.execute(
                "SELECT DISTINCT month FROM vote_monthly WHERE votes > 0 ORDER BY month DESC LIMIT 12"
            ).fetchall()
        except sqlite3.OperationalError:
            # tables appear once the bot or a webhook has run since upgrading
            month_rows = []
    finally:
        conn.close()

    available = [current_month]
    for row in month_rows:
        if row["month"] not in available:
            available.append(row["month"])
    available = available[:12]

    requested = (request.args.get("month") or "").strip()
    month = requested if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", requested) and requested in available else current_month
    month_label = time.strftime("%B %Y", time.strptime(month + "-01", "%Y-%m-%d"))
    months = [
        {
            "value": value,
            "label": (
                time.strftime("%B %Y", time.strptime(value + "-01", "%Y-%m-%d"))
                + (" (current)" if value == current_month else "")
            ),
        }
        for value in available
    ]

    find = (request.args.get("find") or "").strip()[:80]
    raw_page = request.args.get("page", type=int)
    page = max(1, raw_page or 1)
    find_user_id = None
    find_rank = None
    find_votes = 0
    find_name = None
    find_missing = False

    ranked_sql = (
        "SELECT m.user_id, m.votes, v.vote_count, v.last_vote_at, "
        "u.username, u.display_name, u.avatar_hash, u.guild_id, "
        "s.current_streak, s.longest_streak, s.last_day, "
        "ROW_NUMBER() OVER (ORDER BY m.votes DESC, COALESCE(v.last_vote_at, 0) DESC, m.user_id ASC) AS rk "
        "FROM vote_monthly m "
        "LEFT JOIN vote_boosts v ON v.user_id = m.user_id "
        "LEFT JOIN (SELECT user_id, MAX(total_xp) AS total_xp, username, display_name, "
        "avatar_hash, MAX(guild_id) AS guild_id FROM users GROUP BY user_id) u "
        "ON u.user_id = m.user_id "
        "LEFT JOIN vote_streaks s ON s.user_id = m.user_id "
        "WHERE m.month = ? AND m.votes > 0"
    )

    rows = []
    total = 0
    streak_leaders = []
    conn = get_db()
    try:
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM vote_monthly WHERE month = ? AND votes > 0", (month,)
            ).fetchone()[0]

            if find:
                like = "%" + find.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                match = conn.execute(
                    f"SELECT * FROM ({ranked_sql}) AS ranked "
                    "WHERE LOWER(COALESCE(username, '')) = LOWER(?) "
                    "OR LOWER(COALESCE(display_name, '')) = LOWER(?) "
                    "OR LOWER(COALESCE(username, '')) LIKE ? ESCAPE '\\' "
                    "OR LOWER(COALESCE(display_name, '')) LIKE ? ESCAPE '\\' "
                    "ORDER BY CASE WHEN LOWER(COALESCE(username, '')) = LOWER(?) "
                    "OR LOWER(COALESCE(display_name, '')) = LOWER(?) THEN 0 ELSE 1 END, rk "
                    "LIMIT 1",
                    (month, find, find, like, like, find, find),
                ).fetchone()
                if match:
                    find_user_id = match["user_id"]
                    find_rank = match["rk"]
                    find_votes = match["votes"]
                    find_name = match["display_name"] or match["username"] or f"Voter {find_user_id}"
                    if raw_page is None:
                        page = (find_rank - 1) // per_page + 1
                else:
                    find_missing = True

            total_pages = max(1, (total + per_page - 1) // per_page)
            page = min(page, total_pages)
            offset = (page - 1) * per_page
            rows = conn.execute(
                f"SELECT * FROM ({ranked_sql}) AS ranked ORDER BY rk LIMIT ? OFFSET ?",
                (month, per_page, offset),
            ).fetchall()

            streak_leaders = conn.execute(
                "SELECT s.user_id, s.current_streak, s.longest_streak, "
                "u.username, u.display_name, u.avatar_hash, u.guild_id "
                "FROM vote_streaks s "
                "LEFT JOIN (SELECT user_id, MAX(total_xp) AS total_xp, username, display_name, "
                "avatar_hash, MAX(guild_id) AS guild_id FROM users GROUP BY user_id) u "
                "ON u.user_id = s.user_id "
                "WHERE s.current_streak >= 2 AND s.last_day IN (?, ?) "
                "ORDER BY s.current_streak DESC, s.longest_streak DESC, s.user_id ASC LIMIT 5",
                (today, today - 1),
            ).fetchall()
        except sqlite3.OperationalError:
            # tables appear once the bot or a webhook has run since upgrading
            rows, total, streak_leaders = [], 0, []
            total_pages = 1
    finally:
        conn.close()

    entries = []
    for row in rows:
        streak = 0
        if row["last_day"] in (today, today - 1):
            streak = row["current_streak"] or 0
        entries.append({
            "rank": row["rk"],
            "user_id": row["user_id"],
            "name": row["display_name"] or row["username"] or f"Voter {row['user_id']}",
            "votes": row["votes"],
            "badge": _vote_badge_label(row["vote_count"] or 0),
            "streak": streak,
            "last_ago": _fmt_ago(row["last_vote_at"]) if row["last_vote_at"] else "-",
            "avatar_url": _avatar_url(row["user_id"], row["avatar_hash"]),
            "guild_id": row["guild_id"] or 0,
        })

    leaders = [
        {
            "user_id": row["user_id"],
            "name": row["display_name"] or row["username"] or f"Voter {row['user_id']}",
            "streak": row["current_streak"],
            "longest_streak": row["longest_streak"],
            "avatar_url": _avatar_url(row["user_id"], row["avatar_hash"], size=64),
            "guild_id": row["guild_id"] or 0,
        }
        for row in streak_leaders
    ]

    return render_template(
        "voters.html",
        entries=entries,
        podium=entries[:3] if page == 1 else [],
        rest=entries[3:] if page == 1 else entries,
        total=total,
        page=page,
        total_pages=total_pages,
        month=month,
        month_label=month_label,
        months=months,
        is_current=month == current_month,
        find=find,
        find_user_id=find_user_id,
        find_rank=find_rank,
        find_votes=find_votes,
        find_name=find_name,
        find_missing=find_missing,
        streak_leaders=leaders,
        vote_sites=VOTE_SITE_LINKS,
    ), 200

@app.route('/stats')
def botstats():
    history = _load_stats_history()

    latest = history[-1] if history else {}
    total_snapshots = len(history)

    first_ts = history[0]['timestamp'] if history else None
    last_ts = latest.get('timestamp') if latest else None

    week_delta = None
    if total_snapshots >= 2 and last_ts:
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        older = next((s for s in history if s.get('timestamp', '') >= week_ago), None)
        if older and older is not latest:
            week_delta = {
                'users': (latest.get('total_users') or 0) - (older.get('total_users') or 0),
                'xp': (latest.get('total_xp') or 0) - (older.get('total_xp') or 0),
                'messages': (latest.get('total_messages') or 0) - (older.get('total_messages') or 0),
                'vc': (latest.get('total_vc_minutes') or 0) - (older.get('total_vc_minutes') or 0),
            }

    return render_template('botstats.html',
        total_snapshots=total_snapshots,
        first_ts=first_ts,
        last_ts=last_ts,
        guilds=latest.get('total_guilds', 0),
        members=latest.get('total_members', 0),
        users=latest.get('total_users', 0),
        xp=latest.get('total_xp', 0),
        messages=latest.get('total_messages', 0),
        vc_minutes=latest.get('total_vc_minutes', 0),
        avg_level=latest.get('avg_level', 0),
        total_ratings=latest.get('total_ratings', 0),
        avg_rating=latest.get('avg_rating', 0),
        rating_distribution=latest.get('rating_distribution', {}),
        week_delta=week_delta,
    ), 200

_api_history_cache = {'key': None, 'payload': {}}

@app.route('/api/stats/history')
def api_stats_history():
    points = max(50, min(request.args.get('points', 400, type=int) or 400, 1000))
    range_name = request.args.get('range', 'all')
    if range_name not in RANGE_DAYS:
        range_name = 'all'

    history = _load_stats_history()
    total_snapshots = len(history)
    try:
        key = STATS_HISTORY_FILE.stat().st_mtime_ns
    except OSError:
        key = -1
    cache_tag = (key, points)
    payload = None
    if _api_history_cache['key'] == cache_tag:
        payload = _api_history_cache['payload'].get(range_name)

    if payload is None:
        rows = _range_history(history, range_name)
        if not rows:
            payload = {
                'series': {k: [] for k in STORY_KEYS},
                'meta': {'range': range_name, 'points': points, 'snapshots': 0, 'full': total_snapshots, 'last_ts': None},
            }
        else:
            ts = [_snap_ts_ms(s) for s in rows]
            probe = [s.get('total_xp') or 0 for s in rows]
            idxs = _lttb_indices(ts, probe, points)
            series = {}
            for k in STORY_KEYS:
                series[k] = [[ts[i], (rows[i].get(k) or 0)] for i in idxs]
            payload = {
                'series': series,
                'meta': {
                    'range': range_name,
                    'points': len(idxs),
                    'snapshots': len(rows),
                    'full': total_snapshots,
                    'last_ts': rows[-1].get('timestamp'),
                },
            }
        if _api_history_cache['key'] != cache_tag:
            _api_history_cache['key'] = cache_tag
            _api_history_cache['payload'] = {}
        _api_history_cache['payload'][range_name] = payload

    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'public, max-age=120'
    return resp

@app.route('/api/leaderboard/search')
def api_leaderboard_search():
    q = (request.args.get('q') or '').strip()
    guild_id = request.args.get('guild', 0, type=int)
    limit = max(1, min(request.args.get('limit', 5, type=int) or 5, 25))

    if not q:
        return jsonify({'results': []})

    only_username = q.startswith('@')
    term = q[1:] if only_username else q
    if not term:
        return jsonify({'results': []})

    combined = request.args.get('mode') == 'combined'
    period = (request.args.get('period') or 'all').lower()
    if period not in PERIOD_DAYS:
        period = 'all'
    start_day = _period_start_day(period)

    like = f"%{term}%"
    if only_username:
        cond = "LOWER(username) LIKE LOWER(?)"
        order_sql = "CASE WHEN LOWER(username) = LOWER(?) THEN 0 ELSE 1 END, rk"
        search_params = [like, term]
    else:
        cond = "(LOWER(COALESCE(display_name,'')) LIKE LOWER(?) OR LOWER(username) LIKE LOWER(?) OR LOWER(CAST(user_id AS TEXT)) LIKE LOWER(?))"
        order_sql = """CASE
            WHEN LOWER(COALESCE(display_name,'')) = LOWER(?) THEN 0
            WHEN LOWER(username) = LOWER(?) THEN 1
            ELSE 2 END, rk"""
        search_params = [like, like, like, term, term]

    source_params = []
    if start_day is not None and combined:
        source_sql = ("SELECT r.user_id, r.guild_id, r.username, r.display_name, r.avatar_hash, a.value AS total_xp "
                      "FROM (SELECT user_id, guild_id, username, display_name, avatar_hash, "
                      "ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY last_message DESC, rowid DESC) AS rn "
                      "FROM users) AS r "
                      "JOIN (SELECT user_id, SUM(xp) AS value FROM user_stats_daily WHERE day >= ? GROUP BY user_id) AS a "
                      "ON a.user_id = r.user_id WHERE r.rn = 1")
        source_params = [start_day]
        rank_order = "total_xp DESC"
        cache_key = f"lb_search:combined:{only_username}:{term}:{limit}:{start_day}"
    elif start_day is not None:
        where = "WHERE d.guild_id=? AND d.day>=?" if guild_id else "WHERE d.day>=?"
        source_params = [guild_id, start_day] if guild_id else [start_day]
        source_sql = ("SELECT d.user_id, d.guild_id, u.username, u.display_name, u.avatar_hash, "
                      "SUM(d.xp) AS total_xp "
                      "FROM user_stats_daily d "
                      "JOIN users u ON u.guild_id = d.guild_id AND u.user_id = d.user_id "
                      f"{where} GROUP BY d.guild_id, d.user_id")
        rank_order = "total_xp DESC"
        cache_key = f"lb_search:{guild_id}:{only_username}:{term}:{limit}:{start_day}"
    elif combined:
        source_sql = ("SELECT r.user_id, r.guild_id, r.username, r.display_name, r.avatar_hash, a.total_xp "
                      "FROM (SELECT user_id, guild_id, username, display_name, avatar_hash, "
                      "ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY last_message DESC, rowid DESC) AS rn "
                      "FROM users) AS r "
                      "JOIN (SELECT user_id, SUM(total_xp) AS total_xp FROM users GROUP BY user_id) AS a "
                      "ON a.user_id = r.user_id WHERE r.rn = 1")
        rank_order = "total_xp DESC"
        cache_key = f"lb_search:combined:{only_username}:{term}:{limit}"
    else:
        if guild_id:
            source_sql = ("SELECT user_id, guild_id, username, display_name, avatar_hash, level, total_xp "
                          "FROM users WHERE guild_id=?")
            source_params = [guild_id]
        else:
            source_sql = "SELECT user_id, guild_id, username, display_name, avatar_hash, level, total_xp FROM users"
        rank_order = "level DESC"
        cache_key = f"lb_search:{guild_id}:{only_username}:{term}:{limit}"

    sql = f"""
        SELECT user_id, guild_id, username, display_name, avatar_hash, rk, total_xp FROM (
            SELECT user_id, guild_id, username, display_name, avatar_hash, total_xp,
                   ROW_NUMBER() OVER (ORDER BY {rank_order}) AS rk
            FROM ({source_sql}) AS src
        ) AS ranked
        WHERE {cond}
        ORDER BY {order_sql}
        LIMIT ?
    """
    search_params = source_params + search_params + [limit]

    rows = cached_query(
        cache_key,
        sql,
        search_params,
        ttl=30
    )

    # De-duplicate to one suggestion per username
    seen = {}
    for r in rows:
        uname = (r['username'] or '').lower()
        if uname in seen:
            continue
        seen[uname] = r
    deduped = list(seen.values())

    results = []
    for r in deduped:
        ext = 'gif' if (r['avatar_hash'] or '').startswith('a_') else 'png'
        results.append({
            'user_id': r['user_id'],
            'guild_id': 0 if combined else r['guild_id'],
            'username': r['username'],
            'display_name': r['display_name'],
            'avatar': f'https://cdn.discordapp.com/avatars/{r["user_id"]}/{r["avatar_hash"]}.{ext}?size=64' if r['avatar_hash'] else 'https://cdn.discordapp.com/embed/avatars/0.png',
            'rank': r['rk'],
        })
    return jsonify({'results': results})

@app.route('/api/leaderboard')
def api_leaderboard():
    guild_id = request.args.get('guild', 0, type=int)
    sort_by = request.args.get('sort', 'level')
    direction = request.args.get('dir', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    combined = request.args.get('mode') == 'combined'
    period = (request.args.get('period') or 'all').lower()
    if period not in PERIOD_DAYS:
        period = 'all'
    
    per_page = max(1, min(per_page, 100))
    
    entries, total = get_leaderboard(guild_id=guild_id, sort_by=sort_by, direction=direction, page=page, per_page=per_page, combined=combined, period=period)
    
    data = []
    for i, entry in enumerate(entries):
        rank = (page - 1) * per_page + i + 1
        data.append({
            'rank': rank,
            'user_id': entry['user_id'],
            'username': entry['username'],
            'avatar_hash': entry['avatar_hash'],
            'guild_id': entry['guild_id'],
            'level': entry['level'],
            'total_xp': entry['total_xp'],
            'total_messages': entry['total_messages'],
            'vc_minutes': entry['vc_minutes']
        })
    
    return jsonify({
        'leaderboard': data,
        'total': total,
        'page': page,
        'per_page': per_page,
        'period': period,
        'total_pages': max(1, (total + per_page - 1) // per_page)
    })

@app.route('/api/stats')
def api_stats():
    rows = cached_query('agg_stats', """
        SELECT 
            COUNT(*) as total_users,
            SUM(total_xp) as total_xp,
            SUM(total_messages) as total_messages,
            SUM(vc_minutes) as total_vc_minutes
        FROM users
    """)
    r = rows[0]

    bot_rows = cached_query('bot_stats', "SELECT * FROM bot_stats")
    bot = bot_rows[0] if bot_rows else None

    return jsonify({
        'total_guilds': dict(bot)['total_guilds'] if bot else 0,
        'total_members': dict(bot)['total_members'] if bot else 0,
        'total_users': r[0] or 0,
        'total_xp': r[1] or 0,
        'total_messages': r[2] or 0,
        'total_vc_minutes': r[3] or 0
    })

# --- Vote webhooks -------------------------------------------------------
# Rewards for votes from any bot list. The 2x XP boost STACKS: every vote
# extends the expiry instead of overwriting it, so voting on both lists
# in one round (4h each) buys up to 8h of boosted XP.
VOTE_BOOST_MULTIPLIER = 2.0
VOTE_BOOST_DURATION = 14400          # 4h, top.gg weekday vote / any other list
VOTE_BOOST_WEEKEND_DURATION = 21600  # 6h, top.gg weight=2 (weekend) vote
VOTE_SITE_COOLDOWN = 12 * 3600       # per-list cooldown, matches utils.VOTE_SITE_COOLDOWN

# Keep in sync with utils.VOTE_LINKS (web process cannot import utils).
VOTE_SITE_LINKS = (
    ("Top.gg", "https://top.gg/bot/1442229230384709752/vote"),
    ("Discord List", "https://discordlist.gg/bot/1442229230384709752/vote"),
)

# Cosmetic voter badges by lifetime votes; keep in sync with utils.VOTE_BADGES.
VOTE_BADGE_TIERS = (
    (100, "🥇 Gold Voter"),
    (25, "🥈 Silver Voter"),
    (5, "🥉 Bronze Voter"),
)
VOTE_STREAK_MILESTONES = {3, 7, 14, 30, 60, 100, 365}


def _vote_badge_label(vote_count):
    """Badge label for a lifetime vote count, or None below the first tier."""
    for threshold, label in VOTE_BADGE_TIERS:
        if vote_count >= threshold:
            return label
    return None


def _vote_badge_progress(vote_count):
    """Next badge tier as {"label", "threshold", "remaining"}, or None at the top."""
    for threshold, label in reversed(VOTE_BADGE_TIERS):
        if vote_count < threshold:
            return {
                "label": label,
                "threshold": threshold,
                "remaining": threshold - vote_count,
            }
    return None


def _record_vote(user_id, username, source, duration, hours):
    """Upsert one vote arriving from a bot list.

    Stacks the vote duration onto an active 2x XP boost, bumps the lifetime
    vote counter, queues the thanks DM and guild announcement, and refreshes
    the vote reminder of users who opted in via /vote-remind. A repeat from the
    same list inside its cooldown is ignored. Raises on failure so the calling
    route can answer 500.
    """
    now = int(time.time())
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vote_boosts (
            user_id INTEGER PRIMARY KEY,
            multiplier REAL DEFAULT 2.0,
            expires_at INTEGER,
            last_vote_at INTEGER,
            vote_count INTEGER DEFAULT 0
        )
        """)
        for column in ("last_vote_at INTEGER", "vote_count INTEGER DEFAULT 0"):
            try:
                cur.execute(f"ALTER TABLE vote_boosts ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass

        # per-list cooldown timer, one row per (user, list). The guarded upsert
        # is atomic, so retries from a list webhook only reward once.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vote_site_history (
            user_id INTEGER,
            source TEXT,
            voted_at INTEGER,
            PRIMARY KEY (user_id, source)
        )
        """)
        cur.execute("""
        INSERT INTO vote_site_history (user_id, source, voted_at) VALUES (?, ?, ?)
        ON CONFLICT(user_id, source) DO UPDATE SET voted_at = excluded.voted_at
        WHERE excluded.voted_at - COALESCE(vote_site_history.voted_at, 0) >= ?
        """, (int(user_id), source, now, VOTE_SITE_COOLDOWN))
        if cur.rowcount == 0:
            logger.webhook("Ignoring duplicate %s vote from discord user %s", source, user_id)
            return False

        prev_row = cur.execute(
            "SELECT vote_count FROM vote_boosts WHERE user_id = ?", (int(user_id),)
        ).fetchone()
        prev_count = (prev_row["vote_count"] or 0) if prev_row else 0
        new_count = prev_count + 1

        cur.execute("""
        INSERT INTO vote_boosts (user_id, multiplier, expires_at, last_vote_at, vote_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(user_id) DO UPDATE SET
            multiplier = excluded.multiplier,
            expires_at = MAX(COALESCE(vote_boosts.expires_at, 0), excluded.last_vote_at) + ?,
            last_vote_at = excluded.last_vote_at,
            vote_count = COALESCE(vote_boosts.vote_count, 0) + 1
        """, (int(user_id), VOTE_BOOST_MULTIPLIER, now + duration, now, duration))

        # daily voting streak, counted in UTC days (unix day number)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vote_streaks (
            user_id INTEGER PRIMARY KEY,
            current_streak INTEGER DEFAULT 0,
            longest_streak INTEGER DEFAULT 0,
            last_day INTEGER
        )
        """)
        streak_row = cur.execute(
            "SELECT current_streak, longest_streak, last_day FROM vote_streaks WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        today = now // 86400
        if not streak_row:
            streak, streak_incremented = 1, True
        elif streak_row["last_day"] == today:
            streak, streak_incremented = streak_row["current_streak"] or 1, False
        elif streak_row["last_day"] == today - 1:
            streak, streak_incremented = (streak_row["current_streak"] or 0) + 1, True
        else:
            streak, streak_incremented = 1, True
        longest = max((streak_row["longest_streak"] or 0) if streak_row else 0, streak)
        cur.execute("""
        INSERT INTO vote_streaks (user_id, current_streak, longest_streak, last_day)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            current_streak = excluded.current_streak,
            longest_streak = excluded.longest_streak,
            last_day = excluded.last_day
        """, (int(user_id), streak, longest, today))

        # monthly tally used by the voters leaderboard
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vote_monthly (
            user_id INTEGER,
            month TEXT,
            votes INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, month)
        )
        """)
        month = time.strftime("%Y-%m", time.gmtime(now))
        cur.execute("""
        INSERT INTO vote_monthly (user_id, month, votes) VALUES (?, ?, 1)
        ON CONFLICT(user_id, month) DO UPDATE SET votes = votes + 1
        """, (int(user_id), month))

        badge = _vote_badge_label(new_count)
        site_votes = {
            row["source"]: row["voted_at"]
            for row in cur.execute(
                "SELECT source, voted_at FROM vote_site_history WHERE user_id = ?", (int(user_id),)
            ).fetchall()
        }
        other_ready, other_cooling = [], []
        for name, _ in VOTE_SITE_LINKS:
            if name == source:
                continue
            voted_at = site_votes.get(name)
            if voted_at and voted_at + VOTE_SITE_COOLDOWN > now:
                other_cooling.append(name)
            else:
                other_ready.append(name)
        vote_payload = {
            "hours": hours,
            "source": source,
            "vote_count": new_count,
            "badge": badge,
            "unlocked_badge": badge if badge != _vote_badge_label(prev_count) else None,
            "streak": streak,
            "longest_streak": longest,
            "streak_milestone": streak_incremented and streak in VOTE_STREAK_MILESTONES,
            "other_ready": other_ready,
            "other_cooling": other_cooling,
        }

        cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_dms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            kind TEXT,
            payload TEXT,
            created_at INTEGER
        )
        """)
        cur.execute(
            "INSERT INTO pending_dms (user_id, kind, payload, created_at) VALUES (?, 'vote_thanks', ?, ?)",
            (int(user_id), json.dumps(vote_payload), now)
        )

        cur.execute("""
        CREATE TABLE IF NOT EXISTS vote_reminders (
            user_id INTEGER PRIMARY KEY,
            remind_at INTEGER,
            risk_ping_day INTEGER
        )
        """)
        # only refresh reminders for users who opted in via /vote-remind;
        # fire when the soonest list frees up (each list has its own cooldown)
        nexts = [
            row["voted_at"] + VOTE_SITE_COOLDOWN
            for row in cur.execute(
                "SELECT voted_at FROM vote_site_history WHERE user_id = ?", (int(user_id),)
            ).fetchall()
        ]
        remind_at = min(nexts) if nexts else now + VOTE_SITE_COOLDOWN
        cur.execute("UPDATE vote_reminders SET remind_at = ? WHERE user_id = ?", (remind_at, int(user_id)))

        cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_vote_announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            payload TEXT,
            created_at INTEGER
        )
        """)
        cur.execute(
            "INSERT INTO pending_vote_announcements (user_id, username, payload, created_at) VALUES (?, ?, ?, ?)",
            (int(user_id), username, json.dumps({"hours": hours, "source": source}), now)
        )

        conn.commit()
        logger.webhook("%s vote from discord user %s (%sh boost)", source, user_id, hours)
    finally:
        conn.close()


def _hs256_jwt_claims(token, secret):
    """Verify an HS256 JWT with the stdlib only; return its claims or None."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError:
        return None
    expected = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    if not hmac.compare_digest(expected, signature_b64):
        return None
    try:
        header = json.loads(base64.urlsafe_b64decode(header_b64 + "=" * (-len(header_b64) % 4)))
        claims = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    if header.get("alg") != "HS256":
        return None
    try:
        if claims.get("exp") is not None and int(claims["exp"]) < time.time():
            return None
    except (TypeError, ValueError):
        return None
    return claims


@app.route('/webhooks/topgg', methods=['POST'])
def topgg_webhook():
    secret = os.getenv("TOPGG_WEBHOOK_AUTH")
    if not secret:
        return 'Not configured', 500

    raw_body = request.get_data(as_text=True)
    signature = request.headers.get('x-topgg-signature', '')

    if not signature or not raw_body:
        return 'Unauthorized', 401

    try:
        t_part, v1_part = signature.split(',')
        timestamp = t_part.split('=')[1]
        received_sig = v1_part.split('=')[1]
    except (ValueError, IndexError):
        return 'Unauthorized', 401

    expected = hmac.new(secret.encode(), f"{timestamp}.{raw_body}".encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received_sig):
        return 'Unauthorized', 401

    try:
        if abs(int(timestamp) - int(time.time())) > 300:
            return 'Unauthorized', 401
    except ValueError:
        return 'Unauthorized', 401

    data = request.get_json(silent=True) or {}

    if data.get('type') == 'vote.create':
        vote_data = data.get('data') or {}
        user = vote_data.get('user') or {}
        user_id = user.get('platform_id')
        username = user.get('username')

        if not user_id:
            logger.warning("Top.gg vote.create without a Discord user id")
            return 'OK', 200

        weight = vote_data.get('weight', 1)
        duration = VOTE_BOOST_WEEKEND_DURATION if weight == 2 else VOTE_BOOST_DURATION

        try:
            _record_vote(user_id, username, "Top.gg", duration, 6 if weight == 2 else 4)
        except Exception as e:
            logger.error("Top.gg webhook error: %s", e)
            return 'Internal Server Error', 500

    return 'OK', 200


@app.route('/webhooks/discordlist', methods=['POST'])
def discordlist_webhook():
    """discordlist.gg vote webhook.

    Their documented format is an HS256 JWT signed with the Webhook
    Authorization key, sent as the raw body with claims
    {user_id, bot_id, is_test}. Two fallbacks are accepted because delivery
    has been flaky (discordlist-gg/beta-issues#340): the JWT in an
    Authorization: Bearer header, or a plain JSON body with the shared secret
    as the Authorization header.
    """
    secret = os.getenv("DLIST_WEBHOOK_AUTH")
    if not secret:
        logger.error("discordlist.gg webhook hit but DLIST_WEBHOOK_AUTH is not set in .env")
        return 'Not configured', 500

    raw_body = request.get_data(as_text=True).strip()
    claims = None

    if raw_body and not raw_body.startswith('{'):
        claims = _hs256_jwt_claims(raw_body, secret)
    if claims is None:
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            claims = _hs256_jwt_claims(auth[7:], secret)
    if claims is None:
        auth = request.headers.get('Authorization', '')
        if auth and hmac.compare_digest(auth, secret):
            claims = request.get_json(silent=True)
    if not isinstance(claims, dict):
        return 'Unauthorized', 401

    if claims.get('is_test'):
        logger.webhook("discordlist.gg webhook test ping accepted")
        return 'OK', 200

    user_id = claims.get('user_id') or claims.get('id')
    if not user_id:
        logger.warning("discordlist.gg vote without a Discord user id")
        return 'OK', 200

    try:
        _record_vote(user_id, claims.get('username'), "Discord List", VOTE_BOOST_DURATION, 4)
    except Exception as e:
        logger.error("discordlist.gg webhook error: %s", e)
        return 'Internal Server Error', 500

    return 'OK', 200

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8002)
