import datetime
import time

import pytest

import app as webapp
import utils
from admin import constants as admin_constants

G = 9001
U = 9002


@pytest.fixture
def admin_client(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password")
    webapp.app.config["SECRET_KEY"] = "test-secret"
    webapp.app.config["SESSION_COOKIE_SECURE"] = False
    client = webapp.app.test_client()
    with client.session_transaction() as sess:
        sess["admin"] = True
        sess["_csrf"] = "test-csrf"
    return client


def _seed_user():
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO users (guild_id, user_id, username, display_name, avatar_hash, "
            "level, progress, out_of, last_message, total_messages, total_messages_xp, "
            "total_xp, vc_minutes, vc_xp_minutes) "
            "VALUES (?, ?, 'alice', 'Alice', NULL, 4, 10, 180, ?, 20, 20, 500, 30, 20)",
            (G, U, "2026-01-01 12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_votes():
    now = int(time.time())
    today = now // 86400
    month = time.strftime("%Y-%m", time.gmtime(now))
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO vote_boosts (user_id, multiplier, expires_at, last_vote_at, vote_count) "
            "VALUES (?, 2.0, ?, ?, 30)",
            (U, now + 3600, now - 100),
        )
        conn.execute(
            "INSERT INTO vote_site_history (user_id, source, voted_at) VALUES (?, 'Top.gg', ?)",
            (U, now - 3600),
        )
        conn.execute(
            "INSERT INTO vote_site_history (user_id, source, voted_at) VALUES (?, 'Discord List', ?)",
            (U, now - 13 * 3600),
        )
        conn.execute(
            "INSERT INTO vote_streaks (user_id, current_streak, longest_streak, last_day) "
            "VALUES (?, 6, 9, ?)",
            (U, today - 1),
        )
        conn.execute(
            "INSERT INTO vote_monthly (user_id, month, votes) VALUES (?, ?, 3)",
            (U, month),
        )
        conn.execute(
            "INSERT INTO vote_reminders (user_id, remind_at, risk_ping_day) VALUES (?, ?, ?)",
            (U, now + 600, today - 1),
        )
        conn.commit()
    finally:
        conn.close()


def _url():
    return f"/admin/users/{G}/{U}"


def _post(client, **data):
    return client.post(_url(), data={"csrf_token": "test-csrf", **data})


def test_admin_user_edit_shows_voting_summary(admin_client):
    _seed_user()
    _seed_votes()

    resp = admin_client.get(_url())

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    for text in (
        "Voting",
        "Lifetime Votes",
        "30",
        "Silver Voter",
        "70 more for",
        "Gold Voter",
        "Vote Cooldowns",
        "Top.gg",
        "Discord List",
        "Clear All Cooldowns",
        "Edit Vote Records",
        "Vote Reminder",
        "Reset All Vote Data",
        "Vote Boost",
    ):
        assert text in html


def test_admin_user_edit_saves_vote_records(admin_client):
    _seed_user()
    _seed_votes()
    expires_before = utils.get_db().execute(
        "SELECT expires_at FROM vote_boosts WHERE user_id=?", (U,)
    ).fetchone()["expires_at"]
    day = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    expected_day = int(day.timestamp() // 86400)
    month = time.strftime("%Y-%m", time.gmtime())

    resp = _post(
        admin_client,
        action="save_votes",
        lifetime_votes="42",
        monthly_votes="5",
        current_streak="8",
        longest_streak="3",
        streak_last_day="2026-01-02",
    )

    assert resp.status_code == 200
    assert "Vote records updated." in resp.get_data(as_text=True)
    conn = utils.get_db()
    try:
        boost = conn.execute(
            "SELECT vote_count, multiplier, expires_at FROM vote_boosts WHERE user_id=?", (U,)
        ).fetchone()
        streak = conn.execute(
            "SELECT current_streak, longest_streak, last_day FROM vote_streaks WHERE user_id=?",
            (U,),
        ).fetchone()
        monthly = conn.execute(
            "SELECT votes FROM vote_monthly WHERE user_id=? AND month=?", (U, month)
        ).fetchone()
    finally:
        conn.close()

    assert boost["vote_count"] == 42
    assert boost["multiplier"] == 2.0
    assert boost["expires_at"] == expires_before
    assert streak["current_streak"] == 8
    assert streak["longest_streak"] == 8
    assert streak["last_day"] == expected_day
    assert monthly["votes"] == 5


def test_admin_user_edit_clears_single_site_and_reminder(admin_client):
    _seed_user()
    _seed_votes()

    resp = _post(admin_client, action="clear_vote_site", site="Top.gg")
    assert resp.status_code == 200
    assert "Cleared the Top.gg cooldown." in resp.get_data(as_text=True)

    conn = utils.get_db()
    try:
        sources = [
            row["source"]
            for row in conn.execute(
                "SELECT source FROM vote_site_history WHERE user_id=?", (U,)
            ).fetchall()
        ]
    finally:
        conn.close()
    assert sources == ["Discord List"]

    resp = _post(admin_client, action="save_vote_reminder", remind_at="off")
    assert "Vote reminder cleared." in resp.get_data(as_text=True)

    conn = utils.get_db()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM vote_reminders WHERE user_id=?", (U,)
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_admin_user_edit_reset_all_keeps_boost(admin_client):
    _seed_user()
    _seed_votes()
    conn = utils.get_db()
    try:
        before = conn.execute(
            "SELECT multiplier, expires_at FROM vote_boosts WHERE user_id=?", (U,)
        ).fetchone()
    finally:
        conn.close()

    resp = _post(admin_client, action="reset_vote_data")

    assert resp.status_code == 200
    assert "Vote history reset." in resp.get_data(as_text=True)
    conn = utils.get_db()
    try:
        boost = conn.execute(
            "SELECT vote_count, multiplier, expires_at FROM vote_boosts WHERE user_id=?", (U,)
        ).fetchone()
        counts = {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (U,)
            ).fetchone()[0]
            for table in ("vote_site_history", "vote_streaks", "vote_monthly", "vote_reminders")
        }
    finally:
        conn.close()

    assert boost["vote_count"] == 0
    assert boost["multiplier"] == before["multiplier"]
    assert boost["expires_at"] == before["expires_at"]
    assert counts == {
        "vote_site_history": 0,
        "vote_streaks": 0,
        "vote_monthly": 0,
        "vote_reminders": 0,
    }


def test_admin_vote_constants_match_utils_and_app():
    assert admin_constants.ADMIN_VOTE_SITES == tuple(name for name, _url, _emoji in utils.VOTE_LINKS)
    assert admin_constants.ADMIN_VOTE_SITES == tuple(name for name, _ in webapp.VOTE_SITE_LINKS)
    assert admin_constants.ADMIN_VOTE_SITE_COOLDOWN == utils.VOTE_SITE_COOLDOWN
    assert admin_constants.ADMIN_VOTE_SITE_COOLDOWN == webapp.VOTE_SITE_COOLDOWN
    assert admin_constants.ADMIN_VOTE_BADGES == utils.VOTE_BADGES
    assert admin_constants.ADMIN_VOTE_BADGES == webapp.VOTE_BADGE_TIERS
