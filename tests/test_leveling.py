import time

import utils

G = 1001
U = 2002


def _call_xp(content_len=50, display="Alice", username="alice"):
    return utils._do_message_xp(G, U, display, username, None, content_len)


def _fetch_user():
    conn = utils.get_db()
    try:
        return dict(conn.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (G, U)).fetchone())
    finally:
        conn.close()


def _seed_user(**overrides):
    conn = utils.get_db()
    try:
        defaults = {
            "guild_id": G, "user_id": U, "display_name": "Bob", "username": "bob",
            "level": 0, "progress": 0, "out_of": 100, "last_message": "",
            "total_messages": 0, "total_messages_xp": 0, "total_xp": 0,
            "vc_minutes": 0, "vc_xp_minutes": 0, "avatar_hash": None,
        }
        defaults.update(overrides)
        cols = ", ".join(defaults)
        marks = ", ".join(["?"] * len(defaults))
        conn.execute(f"INSERT INTO users ({cols}) VALUES ({marks})", tuple(defaults.values()))
        conn.commit()
    finally:
        conn.close()


def test_new_user_gets_xp(monkeypatch):
    monkeypatch.setattr("random.randint", lambda a, b: 5)
    result = _call_xp()
    assert result is None
    row = _fetch_user()
    assert row["total_messages"] == 1
    assert row["total_messages_xp"] == 1
    assert row["total_xp"] == 5
    assert row["progress"] == 5


def test_short_message_gets_no_xp(monkeypatch):
    monkeypatch.setattr("random.randint", lambda a, b: 5)
    result = _call_xp(content_len=3)
    assert result is None
    row = _fetch_user()
    assert row["total_messages"] == 1
    assert row["total_messages_xp"] == 0
    assert row["progress"] == 0


def test_cooldown_blocks_xp(monkeypatch):
    monkeypatch.setattr("random.randint", lambda a, b: 7)
    _call_xp()
    before = _fetch_user()["progress"]
    utils.last_xp[(G, U)] = time.time()
    _call_xp()
    after = _fetch_user()["progress"]
    assert after == before


def test_vote_boost_doubles_xp(monkeypatch):
    monkeypatch.setattr("random.randint", lambda a, b: 10)
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO vote_boosts (user_id, multiplier, expires_at, last_vote_at) VALUES (?, ?, ?, ?)",
            (U, 2.0, int(time.time()) + 14400, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()
    _call_xp()
    assert _fetch_user()["progress"] == 20


def test_level_up_math(monkeypatch):
    monkeypatch.setattr("random.randint", lambda a, b: 5)
    _seed_user(progress=98, out_of=100)
    payload = _call_xp()
    assert payload is not None
    assert payload["level"] == 1
    assert payload["progress"] == 3
    assert payload["out_of"] == 120
    row = _fetch_user()
    assert row["level"] == 1
    assert row["progress"] == 3
    assert row["out_of"] == 120


def test_blocked_leveling_gets_no_xp(monkeypatch):
    monkeypatch.setattr("random.randint", lambda a, b: 5)
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO user_blocks (user_id, feature, blocked_at, expires_at, note) VALUES (?, ?, ?, NULL, ?)",
            (U, "leveling", int(time.time()), "test"),
        )
        conn.commit()
    finally:
        conn.close()
    result = _call_xp()
    assert result is None
    conn = utils.get_db()
    try:
        row = conn.execute("SELECT 1 FROM users WHERE guild_id=? AND user_id=?", (G, U)).fetchone()
    finally:
        conn.close()
    assert row is None


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


def test_message_xp_writes_daily_bucket(monkeypatch):
    monkeypatch.setattr("random.randint", lambda a, b: 5)
    _call_xp()
    conn = utils.get_db()
    try:
        row = conn.execute(
            "SELECT * FROM user_stats_daily WHERE guild_id=? AND user_id=?", (G, U)
        ).fetchone()
    finally:
        conn.close()
    assert row["messages"] == 1
    assert row["xp"] == 5
    assert row["day"] == int(time.time() // utils.SECONDS_PER_DAY)


def test_short_message_daily_bucket_counts_message_only(monkeypatch):
    monkeypatch.setattr("random.randint", lambda a, b: 5)
    _call_xp(content_len=3)
    conn = utils.get_db()
    try:
        row = conn.execute(
            "SELECT * FROM user_stats_daily WHERE guild_id=? AND user_id=?", (G, U)
        ).fetchone()
    finally:
        conn.close()
    assert row["messages"] == 1
    assert row["xp"] == 0


def test_period_leaderboard_uses_daily_buckets():
    from cogs import leveling

    today = int(time.time() // utils.SECONDS_PER_DAY)
    _seed_user()
    _seed_daily(G, U, today, xp=5, messages=1)
    _seed_daily(G, U, today - 1, xp=100, messages=50)

    rows, total = leveling._fetch_leaderboard(G, "Total Messages", False, 1, 10, False, "Daily")
    assert total == 1
    assert rows[0]["user_id"] == U
    assert rows[0]["value"] == 1

    rows, total = leveling._fetch_leaderboard(G, "Total Messages", False, 1, 10, False, "Weekly")
    assert rows[0]["value"] == 51

    rank, rank_total = leveling._fetch_rank(G, U, "Total Messages", False, False, "Daily")
    assert rank == 1
    assert rank_total == 1

    all_rows, _ = leveling._fetch_leaderboard(G, "Total Messages", False, 1, 10, False, "All Time")
    assert all_rows[0]["value"] == 0


def test_period_multirow_sums_without_duplicating_users():
    from cogs import leveling

    g2 = G + 1
    other = U + 1
    today = int(time.time() // utils.SECONDS_PER_DAY)
    _seed_user()
    _seed_user(guild_id=g2, user_id=U, display_name="Alice2", username="alice")
    _seed_user(guild_id=g2, user_id=other, display_name="Carol", username="carol")

    for d in range(30):
        _seed_daily(G, U, today - d, xp=10, messages=10)
    for d in range(5):
        _seed_daily(g2, U, today - d, xp=100, messages=5)
    _seed_daily(g2, other, today, xp=50, messages=50)

    rows, total = leveling._fetch_leaderboard(G, "Total XP", False, 1, 10, False, "Monthly")
    assert total == 1
    assert rows[0]["value"] == 300

    rows, total = leveling._fetch_leaderboard(0, "Total XP", True, 1, 10, True, "Daily")
    got = {r["user_id"]: r["value"] for r in rows}
    assert got[U] == 110
    assert got[other] == 50

    conn = utils.get_db()
    try:
        lifetime_rows = conn.execute("SELECT COUNT(*) FROM users WHERE user_id=?", (U,)).fetchone()[0]
        daily_rows = conn.execute(
            "SELECT COUNT(*) FROM user_stats_daily WHERE guild_id=? AND user_id=?", (G, U)
        ).fetchone()[0]
    finally:
        conn.close()
    assert lifetime_rows == 2
    assert daily_rows == 30