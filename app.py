from flask import Flask, render_template, request, redirect, jsonify
from dotenv import load_dotenv
import sqlite3
import time
import os

load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.getenv('SECRET_KEY')

cache = {}
CACHE_TTL = 10

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

@app.before_request
def remove_trailing_slash():
    if request.path != '/' and request.path.endswith('/'):
        return redirect(request.path[:-1])

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
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
    entries = cached_query(
        cache_key,
        f"SELECT * FROM users {where_sql} ORDER BY {sort_by} {dir_sql} LIMIT ? OFFSET ?",
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

@app.route('/leaderboard')
def leaderboard():
    guild_id = request.args.get('guild', 0, type=int)
    sort_by = request.args.get('sort', 'level')
    direction = request.args.get('dir', 'desc')
    page = request.args.get('page', 1, type=int)
    
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
        agg_vc=agg_vc_str
    ), 200

@app.route('/api/leaderboard')
def api_leaderboard():
    guild_id = request.args.get('guild', 0, type=int)
    sort_by = request.args.get('sort', 'level')
    direction = request.args.get('dir', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    
    per_page = min(per_page, 100)
    
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

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8002)
