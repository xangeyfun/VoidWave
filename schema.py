"""Main database schema for VoidWave.

The Discord bot applies this on startup (`bot.py` `__main__`) and tests use it
to build an identical schema in a temp location. Column additions follow the
same pattern as the interactive fixes below: `ALTER TABLE ... ADD COLUMN`
wrapped in `try/except sqlite3.OperationalError`.
"""

import sqlite3


def create_schema(conn):
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        guild_id INTEGER,
        user_id INTEGER,
        display_name TEXT,
        username TEXT,
        level INTEGER,
        progress INTEGER,
        out_of INTEGER,
        last_message TEXT,
        total_messages INTEGER,
        total_messages_xp INTEGER,
        total_xp INTEGER,
        vc_minutes INTEGER,
        vc_xp_minutes INTEGER,
        avatar_hash TEXT,
        PRIMARY KEY (guild_id, user_id)
    )
    """)
    conn.commit()

    for column in ("command_uses INTEGER DEFAULT 0", "rated INTEGER DEFAULT 0", "prompt_sent INTEGER DEFAULT 0"):
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass
    conn.commit()

    cur.execute("""
        UPDATE users SET
            level = COALESCE(level, 0),
            progress = COALESCE(progress, 0),
            out_of = COALESCE(out_of, 100),
            last_message = COALESCE(last_message, ''),
            total_messages = COALESCE(total_messages, 0),
            total_messages_xp = COALESCE(total_messages_xp, 0),
            total_xp = COALESCE(total_xp, 0),
            vc_minutes = COALESCE(vc_minutes, 0),
            vc_xp_minutes = COALESCE(vc_xp_minutes, 0)
        WHERE level IS NULL OR progress IS NULL OR out_of IS NULL
           OR last_message IS NULL OR total_messages IS NULL
           OR total_messages_xp IS NULL OR total_xp IS NULL
           OR vc_minutes IS NULL OR vc_xp_minutes IS NULL
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        rating INTEGER,
        feedback TEXT,
        guild_name TEXT,
        created_at INTEGER
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_stats (
        total_guilds INTEGER DEFAULT 0,
        total_members INTEGER DEFAULT 0
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id INTEGER PRIMARY KEY,
        level_channel_id INTEGER,
        level_channel_enabled BOOLEAN DEFAULT 0,
        qotd_enabled BOOLEAN DEFAULT 0,
        qotd_channel INTEGER,
        qotd_role_id INTEGER,
        last_qotd_id INTEGER,
        last_qotd_thread_id INTEGER
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS level_roles (
        guild_id INTEGER,
        level INTEGER,
        role_id INTEGER,
        UNIQUE(guild_id, level)
    )
    """)
    conn.commit()

    for column in (
        "qotd_queue TEXT",
        "delete_old_qotd BOOLEAN DEFAULT 1",
        "qotd_time TEXT DEFAULT '16:00'",
        "qotd_tz TEXT",
        "last_qotd_date TEXT",
    ):
        try:
            cur.execute(f"ALTER TABLE guild_settings ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vote_boosts (
        user_id INTEGER PRIMARY KEY,
        multiplier REAL DEFAULT 2.0,
        expires_at INTEGER,
        last_vote_at INTEGER
    )
    """)
    conn.commit()

    try:
        cur.execute("ALTER TABLE vote_boosts ADD COLUMN last_vote_at INTEGER")
    except sqlite3.OperationalError:
        pass
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vote_reminders (
        user_id INTEGER PRIMARY KEY,
        remind_at INTEGER
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pending_dms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kind TEXT,
        payload TEXT,
        created_at INTEGER
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pending_vote_announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        payload TEXT,
        created_at INTEGER
    )
    """)
    conn.commit()

    for column in ("vote_announce_enabled BOOLEAN DEFAULT 1", "ai_enabled BOOLEAN DEFAULT 1"):
        try:
            cur.execute(f"ALTER TABLE guild_settings ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_prefs (
        user_id INTEGER PRIMARY KEY,
        ai_enabled BOOLEAN DEFAULT 1
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        trigger_at INTEGER NOT NULL,
        recurring TEXT,
        tz TEXT NOT NULL DEFAULT 'UTC',
        created_at INTEGER NOT NULL,
        channel_id INTEGER
    )
    """)
    conn.commit()

    cur.execute("CREATE INDEX IF NOT EXISTS idx_reminders_trigger_at ON reminders(trigger_at)")
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS giveaways (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        message_id INTEGER,
        host_id INTEGER NOT NULL,
        prize TEXT NOT NULL,
        winners_count INTEGER DEFAULT 1,
        required_role_id INTEGER,
        ends_at INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        ended INTEGER DEFAULT 0,
        winner_ids TEXT
    )
    """)
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS giveaway_entries (
        giveaway_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        entered_at INTEGER NOT NULL,
        PRIMARY KEY (giveaway_id, user_id)
    )
    """)
    conn.commit()

    cur.execute("CREATE INDEX IF NOT EXISTS idx_giveaways_ends_at ON giveaways(ends_at)")
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS playlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        name_lower TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )
    """)
    conn.commit()

    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_playlists ON playlists(user_id, name_lower)")
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS playlist_tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        playlist_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        query TEXT NOT NULL,
        title TEXT,
        author TEXT,
        uri TEXT,
        artwork TEXT,
        length_ms INTEGER,
        source TEXT,
        added_at INTEGER NOT NULL
    )
    """)
    conn.commit()

    cur.execute("CREATE INDEX IF NOT EXISTS idx_playlist_tracks ON playlist_tracks(playlist_id, position)")
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS music_controller (
        guild_id INTEGER PRIMARY KEY,
        channel_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """)
    conn.commit()

    try:
        cur.execute("ALTER TABLE reminders ADD COLUMN channel_id INTEGER")
    except sqlite3.OperationalError:
        pass
    conn.commit()

    try:
        cur.execute("ALTER TABLE user_prefs ADD COLUMN remind_tz TEXT DEFAULT 'UTC'")
    except sqlite3.OperationalError:
        pass
    conn.commit()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_blocks (
        user_id INTEGER,
        feature TEXT,
        blocked_at INTEGER,
        expires_at INTEGER,
        note TEXT,
        PRIMARY KEY (user_id, feature)
    )
    """)
    conn.commit()

    for column in ("expires_at INTEGER", "note TEXT"):
        try:
            cur.execute(f"ALTER TABLE user_blocks ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass
    conn.commit()