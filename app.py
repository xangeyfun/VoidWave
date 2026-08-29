from flask import Flask, render_template, request, redirect, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv
from admin import admin_bp
from pathlib import Path
import sqlite3
import time
import os
import json
import hmac
import hashlib
import subprocess
import re

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
CACHE_TTL = 30

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

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def get_user_stats(user_id: int, guild_id: int):
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
        
        return {
            'username': user['username'],
            'display_name': user['display_name'],
            'level': user['level'],
            'progress': user['progress'],
            'out_of': user['out_of'],
            'total_xp': user['total_xp'],
            'total_messages': user['total_messages'],
            'vc_minutes': user['vc_minutes'],
            'vc_xp_minutes': user['vc_xp_minutes'],
            'avatar_hash': user['avatar_hash'],
            'rank': rank,
            'global_rank': global_rank
        }
    except Exception as e:
        print(f"Error fetching user stats: {e}")
        return None
    finally:
        conn.close()

def get_leaderboard(guild_id: int = 0, sort_by: str = 'level', direction: str = 'desc', page: int = 1, per_page: int = 25):
    valid_sorts = {'level', 'total_xp', 'total_messages', 'vc_minutes'}
    if sort_by not in valid_sorts:
        sort_by = 'level'
    
    dir_sql = 'DESC' if direction == 'desc' else 'ASC'
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
    return render_template('index.html', bot_stats=bot_stats), 200

@app.route('/setup')
def setup():
    return render_template('setup.html'), 200

@app.route('/commands')
def commands():
    return render_template('commands.html'), 200

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

@app.route('/stats/<int:guild_id>/<int:user_id>')
def stats(guild_id: int, user_id: int):
    user_data = get_user_stats(user_id, guild_id)
    
    if not user_data:
        return render_template('stats.html', 
            username='Unknown User',
            level=0,
            progress=0,
            out_of=100,
            total_xp=0,
            total_messages=0,
            rank=0,
            global_rank=0,
            progress_percent=0,
            vc_minutes=0,
            vc_xp_minutes=0,
            guild_id=guild_id,
            user_id=user_id,
            avatar_url='https://cdn.discordapp.com/embed/avatars/0.png'
        ), 200
    
    progress_percent = (user_data['progress'] / user_data['out_of'] * 100) if user_data['out_of'] > 0 else 0
    
    return render_template('stats.html',
        username=user_data['username'],
        level=user_data['level'],
        progress=user_data['progress'],
        out_of=user_data['out_of'],
        total_xp=user_data['total_xp'],
        total_messages=user_data['total_messages'],
        rank=user_data['rank'],
        global_rank=user_data['global_rank'],
        progress_percent=progress_percent,
        vc_minutes=user_data['vc_minutes'],
        vc_xp_minutes=user_data['vc_xp_minutes'],
        guild_id=guild_id,
        user_id=user_id,
        avatar_url=f'https://cdn.discordapp.com/avatars/{user_id}/{user_data["avatar_hash"]}.png?size=128' if user_data['avatar_hash'] else 'https://cdn.discordapp.com/embed/avatars/0.png'
    ), 200

def _lb_find_rank(username_query, guild_id, sort_by, direction):
    valid_sorts = {'level', 'total_xp', 'total_messages', 'vc_minutes'}
    if sort_by not in valid_sorts:
        sort_by = 'level'
    dir_sql = 'DESC' if direction == 'desc' else 'ASC'
    where_sql = 'WHERE guild_id=?' if guild_id else ''
    params = (guild_id,) if guild_id else ()
    base = f"""
        SELECT user_id, guild_id, username, rk FROM (
            SELECT user_id, guild_id, username,
                   ROW_NUMBER() OVER (ORDER BY {sort_by} {dir_sql}) AS rk
            FROM users {where_sql}
        ) AS ranked
    """
    key = f"lb_find:{guild_id}:{sort_by}:{direction}:{username_query}"
    for cond in ("LOWER(username) = LOWER(?)", "LOWER(username) LIKE LOWER(?)"):
        match = '%' if cond.startswith('LOWER(username) LIKE') else ''
        rows = cached_query(
            key + (':exact' if not match else ':like'),
            base + f" WHERE {cond} ORDER BY rk LIMIT 1",
            params + (f"{match}{username_query}{match}",),
            ttl=30
        )
        if rows:
            return {
                'user_id': rows[0]['user_id'],
                'guild_id': rows[0]['guild_id'],
                'username': rows[0]['username'],
                'rank': rows[0]['rk'],
            }
    return None

@app.route('/leaderboard')
def leaderboard():
    guild_id = request.args.get('guild', 0, type=int)
    sort_by = request.args.get('sort', 'level')
    direction = request.args.get('dir', 'desc')
    page = request.args.get('page', 1, type=int)

    find_query = (request.args.get('find') or '').strip()
    find_user_id = None
    find_guild_id = None
    find_rank = None
    find_username = None

    if find_query:
        found = _lb_find_rank(find_query, guild_id, sort_by, direction)
        if found:
            find_user_id = found['user_id']
            find_guild_id = found['guild_id']
            find_username = found['username']
            find_rank = found['rank']
            page = max(1, (find_rank + 49) // 50)
    
    entries, total = get_leaderboard(guild_id=guild_id, sort_by=sort_by, direction=direction, page=page, per_page=50)
    
    leaderboard_list = []
    for i, entry in enumerate(entries):
        rank = (page - 1) * 50 + i + 1
        leaderboard_list.append({
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
    
    total_pages = max(1, (total + 49) // 50)

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
        sort_by=sort_by,
        direction=direction,
        page=page,
        total_pages=total_pages,
        agg_xp=f"{agg_xp:,}",
        agg_messages=f"{agg_messages:,}",
        agg_vc=agg_vc_str,
        find_query=find_query,
        find_user_id=find_user_id,
        find_guild_id=find_guild_id,
        find_rank=find_rank,
        find_username=find_username
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

@app.route('/api/leaderboard')
def api_leaderboard():
    guild_id = request.args.get('guild', 0, type=int)
    sort_by = request.args.get('sort', 'level')
    direction = request.args.get('dir', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    
    per_page = max(1, min(per_page, 100))
    
    entries, total = get_leaderboard(guild_id=guild_id, sort_by=sort_by, direction=direction, page=page, per_page=per_page)
    
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
        user_id = (vote_data.get('user') or {}).get('platform_id')

        if not user_id:
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} WARN  Top.gg vote.create without a Discord user id")
            return 'OK', 200

        weight = vote_data.get('weight', 1)
        duration = 10800 if weight == 2 else 7200

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS vote_boosts (
                user_id INTEGER PRIMARY KEY,
                multiplier REAL DEFAULT 2.0,
                expires_at INTEGER,
                last_vote_at INTEGER
            )
            """)
            try:
                cur.execute("ALTER TABLE vote_boosts ADD COLUMN last_vote_at INTEGER")
            except sqlite3.OperationalError:
                pass
            cur.execute("""
            INSERT INTO vote_boosts (user_id, multiplier, expires_at, last_vote_at) VALUES (?, 2.0, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET multiplier = excluded.multiplier, expires_at = excluded.expires_at, last_vote_at = excluded.last_vote_at
            """, (int(user_id), int(time.time()) + duration, int(time.time())))

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
                (int(user_id), json.dumps({"hours": 3 if weight == 2 else 2}), int(time.time()))
            )

            cur.execute("""
            CREATE TABLE IF NOT EXISTS vote_reminders (
                user_id INTEGER PRIMARY KEY,
                remind_at INTEGER
            )
            """)
            # only refresh reminders for users who opted in via /vote-remind
            cur.execute("UPDATE vote_reminders SET remind_at = ? WHERE user_id = ?", (int(time.time()) + 12 * 3600, int(user_id)))

            conn.commit()
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} WEBHOOK  Top.gg vote from discord user {user_id} ({'3h weekend' if weight == 2 else '2h'} boost)")
        except Exception as e:
            print(f"Top.gg webhook error: {e}")
            return 'Internal Server Error', 500
        finally:
            conn.close()

    return 'OK', 200

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8002)
