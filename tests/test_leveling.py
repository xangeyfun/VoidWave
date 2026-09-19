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