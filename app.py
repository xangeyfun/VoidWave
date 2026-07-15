from flask import Flask, render_template, request, redirect, jsonify
from dotenv import load_dotenv
import sqlite3
import time
import os

load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.getenv('SECRET_KEY')

cache = {}
CACHE_TTL = 30

def cached_query(key, query, params=(), ttl=CACHE_TTL):
    now = time.time()
    if key in cache and now - cache[key]['time'] < ttl:
        return cache[key]['data']
    conn = get_db()
    cur = conn.cursor()
    result = cur.execute(query, params).fetchall()
    conn.close()
    cache[key] = {'data': result, 'time': now}
    return result

@app.before_request
def remove_trailing_slash():
    if request.path != '/' and request.path.endswith('/'):
        return redirect(request.path[:-1])

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_user_stats(user_id: int, guild_id: int):
    try:
        conn = get_db()
        cur = conn.cursor()
        
        user = cur.execute(
            "SELECT * FROM users WHERE user_id=? AND guild_id=?",
            (user_id, guild_id)
        ).fetchone()
        
        if not user:
            conn.close()
            return None
        
        rank = cur.execute(
            "SELECT COUNT(*) + 1 FROM users WHERE guild_id=? AND total_xp > ?",
            (guild_id, user['total_xp'])
        ).fetchone()[0]
        
        conn.close()
        
        return {
            'username': user['username'],
            'display_name': user['display_name'],
            'level': user['level'],
            'progress': user['progress'],
            'out_of': user['out_of'],
            'total_xp': user['total_xp'],
            'total_messages': user['total_messages'],
            'avatar_hash': user['avatar_hash'],
            'rank': rank
        }
    except Exception as e:
        print(f"Error fetching user stats: {e}")
        return None

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
    conn = get_db()
    cur = conn.cursor()
    bot_stats = cur.execute("SELECT * FROM bot_stats").fetchone()
    conn.close()
    
    return render_template('index.html', bot_stats=bot_stats), 200

@app.route('/setup')
def setup():
    return render_template('setup.html'), 200

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
            progress_percent=0,
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
        progress_percent=progress_percent,
        guild_id=guild_id,
        user_id=user_id,
        avatar_url=f'https://cdn.discordapp.com/avatars/{user_id}/{user_data["avatar_hash"]}.png' if user_data['avatar_hash'] else 'https://cdn.discordapp.com/embed/avatars/0.png'
    ), 200

@app.route('/leaderboard')
def leaderboard():
    guild_id = request.args.get('guild', 0, type=int)
    sort_by = request.args.get('sort', 'level')
    direction = request.args.get('dir', 'desc')
    page = request.args.get('page', 1, type=int)
    
    entries, total = get_leaderboard(guild_id=guild_id, sort_by=sort_by, direction=direction, page=page, per_page=25)
    
    leaderboard_list = []
    for i, entry in enumerate(entries):
        rank = (page - 1) * 25 + i + 1
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
    
    total_pages = max(1, (total + 24) // 25)
    
    guild_rows = cached_query('guilds', "SELECT DISTINCT guild_id FROM users ORDER BY guild_id")
    guilds = [r[0] for r in guild_rows]
    
    return render_template('leaderboard.html',
        leaderboard=leaderboard_list,
        total=total,
        guild_id=guild_id,
        sort_by=sort_by,
        direction=direction,
        page=page,
        total_pages=total_pages,
        guilds=guilds
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

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8002)
