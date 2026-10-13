import time

import utils

G = 7001
U = 8002

import app as webapp  # noqa: E402

client = webapp.app.test_client()


def _seed_user(guild_id, user_id, username, display_name, total_xp=0, total_messages=0, vc_minutes=0):
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO users (guild_id, user_id, username, display_name, avatar_hash, level, "
            "progress, out_of, last_message, total_messages, total_messages_xp, total_xp, vc_minutes, vc_xp_minutes) "
            "VALUES (?, ?, ?, ?, ?, 0, 0, 100, ?, ?, 0, ?, ?, 0)",
            (guild_id, user_id, username, display_name, None, time.time(),
             total_messages, total_xp, vc_minutes),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_daily(guild_id, user_id, day, xp=0, messages=0, vc_minutes=0):
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO user_stats_daily (guild_id, user_id, day, xp, messages, vc_minutes) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, day) DO UPDATE SET "
            "xp = xp + excluded.xp, messages = messages + excluded.messages, "
            "vc_minutes = vc_minutes + excluded.vc_minutes",
            (guild_id, user_id, day, xp, messages, vc_minutes),
        )
        conn.commit()
    finally:
        conn.close()


def _today():
    return int(time.time() // utils.SECONDS_PER_DAY)


def test_api_leaderboard_daily_window_excludes_old_activity():
    _seed_user(G, U, "alice", "Alice")
    _seed_user(G, U + 1, "bob", "Bob")
    today = _today()
    _seed_daily(G, U, today, xp=100)
    _seed_daily(G, U, today - 1, xp=50)
    _seed_daily(G, U, today - 10, xp=9999)
    _seed_daily(G, U + 1, today, xp=10)

    body = client.get(f"/api/leaderboard?guild={G}&period=daily&per_page=50").get_json()
    assert [e["username"] for e in body["leaderboard"]] == ["alice", "bob"]
    assert body["leaderboard"][0]["total_xp"] == 100
    assert body["period"] == "daily"


def test_api_leaderboard_weekly_and_monthly_windows():
    _seed_user(G, U, "alice", "Alice")
    today = _today()
    for d in range(30):
        _seed_daily(G, U, today - d, xp=10)

    weekly = client.get(f"/api/leaderboard?guild={G}&period=weekly&per_page=50").get_json()
    assert weekly["leaderboard"][0]["total_xp"] == 70

    monthly = client.get(f"/api/leaderboard?guild={G}&period=monthly&per_page=50").get_json()
    assert monthly["leaderboard"][0]["total_xp"] == 300


def test_api_leaderboard_combined_period_sums_across_guilds():
    _seed_user(G, U, "alice", "Alice")
    _seed_user(G + 1, U, "alice", "Alice")
    today = _today()
    _seed_daily(G, U, today, xp=100)
    _seed_daily(G + 1, U, today, xp=30)

    body = client.get("/api/leaderboard?mode=combined&period=daily&per_page=50").get_json()
    assert len(body["leaderboard"]) == 1
    assert body["leaderboard"][0]["total_xp"] == 130
    assert body["leaderboard"][0]["guild_id"] == 0


def test_api_leaderboard_all_time_unchanged_without_period():
    _seed_user(G, U, "alice", "Alice", total_xp=10149)
    _seed_daily(G, U, _today(), xp=5)

    body = client.get(f"/api/leaderboard?guild={G}&per_page=50").get_json()
    assert body["leaderboard"][0]["total_xp"] == 10149


def test_api_search_respects_period():
    _seed_user(G, U, "alice", "Alice")
    today = _today()
    _seed_daily(G, U, today, xp=5)

    body = client.get(f"/api/leaderboard/search?q=ali&guild={G}&period=daily&limit=10").get_json()
    assert [r["username"] for r in body["results"]] == ["alice"]


def test_leaderboard_page_carries_period_in_links():
    html = client.get(f"/leaderboard?guild={G}&period=weekly").get_data(as_text=True)
    assert "period=weekly" in html
    assert "Weekly" in html
