from datetime import date, timezone
from types import SimpleNamespace

from utils import (
    block_reply,
    extract_options,
    format_minutes,
    format_seconds,
    get_command_path,
    get_db,
    holiday_key,
    holiday_qotd,
    prune_user_text_logs,
    purge_user_data,
    qotd_minutes,
    qotd_now,
    qotd_tz_label,
    reapply_user_deletions,
)


def test_format_seconds():
    assert format_seconds(0) == "0s"
    assert format_seconds(59) == "59s"
    assert format_seconds(60) == "1m"
    assert format_seconds(61) == "1m 1s"
    assert format_seconds(3600) == "1h"
    assert format_seconds(3661) == "1h 1m 1s"


def test_format_minutes():
    assert format_minutes(0) == "0m"
    assert format_minutes(30) == "30m"
    assert format_minutes(90) == "1h 30m"
    assert format_minutes(1440) == "1d"


def test_qotd_minutes():
    assert qotd_minutes("16:00") == 960
    assert qotd_minutes("00:00") == 0
    assert qotd_minutes("23:59") == 1439
    assert qotd_minutes("") is None
    assert qotd_minutes("25:00") is None
    assert qotd_minutes("ab:cd") is None
    assert qotd_minutes(None) is None


def test_qotd_now_utc():
    now = qotd_now(None)
    assert now.tzinfo is not None
    assert now.utcoffset() == timezone.utc.utcoffset(None)


def test_qotd_now_named_tz():
    now = qotd_now("Europe/Amsterdam")
    assert now.tzinfo is not None


def test_qotd_tz_label_fallback():
    label = qotd_tz_label()
    assert isinstance(label, str)
    assert len(label) > 0


def test_holiday_key_fixed_and_moving_dates():
    assert holiday_key(date(2026, 10, 31)) == "10-31"
    assert holiday_key(date(2026, 11, 26)) == "thanksgiving"
    assert holiday_key(date(2026, 4, 5)) == "easter"
    assert holiday_key(date(2026, 7, 15)) == "07-15"


def test_holiday_qotd_reads_themed_questions():
    with open("holiday_questions.json", "w", encoding="utf-8") as f:
        f.write('{"10-31": ["Boo?"]}')
    assert holiday_qotd(day=date(2026, 10, 31)) == "Boo?"
    assert holiday_qotd(day=date(2026, 10, 30)) is None


def test_get_command_path_subcommand():
    interaction = SimpleNamespace(data={"name": "music", "options": [{"name": "play", "type": 1, "options": [{"name": "query", "type": 3, "value": "x"}]}]})
    assert get_command_path(interaction) == "/music play"


def test_get_command_path_plain():
    interaction = SimpleNamespace(data={"name": "help"})
    assert get_command_path(interaction) == "/help"


def test_extract_options_flattens_groups():
    options = [{"name": "play", "type": 1, "options": [{"name": "query", "type": 3, "value": "song"}]}]
    assert extract_options(options) == {"query": "song"}


def test_extract_options_empty():
    assert extract_options(None) == {}
    assert extract_options([]) == {}


def test_block_reply_no_block():
    assert block_reply(999999, "commands", "using VoidWave commands") == "You are blocked from using VoidWave commands."


def test_block_reply_with_expiry_and_note():
    import time

    import utils as u

    conn = u.get_db()
    try:
        expires = int(time.time()) + 3600
        conn.execute(
            "INSERT INTO user_blocks (user_id, feature, blocked_at, expires_at, note) VALUES (?, ?, ?, ?, ?)",
            (12345, "leveling", int(time.time()), expires, "test reason"),
        )
        conn.commit()
    finally:
        conn.close()

    reply = block_reply(12345, "leveling", "earning XP")
    assert "You are blocked from earning XP." in reply
    assert "test reason" in reply


def test_purge_user_data_and_reapply_after_restore():
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (guild_id, user_id) VALUES (1, 42)")
        conn.execute("INSERT INTO vote_boosts (user_id) VALUES (42)")
        conn.execute("INSERT INTO user_prefs (user_id) VALUES (42)")
        conn.execute(
            "INSERT INTO playlists (user_id, name, name_lower, created_at) VALUES (42, 'p', 'p', 0)"
        )
        playlist_id = conn.execute("SELECT id FROM playlists WHERE user_id=42").fetchone()[0]
        conn.execute(
            "INSERT INTO playlist_tracks (playlist_id, position, query, added_at) VALUES (?, 1, 'q', 0)",
            (playlist_id,),
        )
        conn.commit()
    finally:
        conn.close()

    counts = purge_user_data(42)
    assert counts["users"] == 1
    assert counts["playlist_tracks"] == 1

    conn = get_db()
    try:
        for table in ("users", "vote_boosts", "user_prefs", "playlists", "playlist_tracks"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert conn.execute("SELECT deleted_at FROM deleted_users WHERE user_id=42").fetchone()
    finally:
        conn.close()

    conn = get_db()
    try:
        conn.execute("INSERT INTO users (guild_id, user_id) VALUES (1, 42)")
        conn.commit()
    finally:
        conn.close()

    reapply_user_deletions()
    conn = get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE user_id=42").fetchone()[0] == 0
    finally:
        conn.close()


def test_prune_user_text_logs():
    with open("command_logs.txt", "w", encoding="utf-8") as f:
        f.write("2020-01-01 00:00:00 COMMAND old\n")
        f.write("2099-01-01 00:00:00 COMMAND new\n")

    prune_user_text_logs()

    with open("command_logs.txt", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    assert "2099-01-01" in lines[0]