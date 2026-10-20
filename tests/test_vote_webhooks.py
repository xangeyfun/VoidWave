import base64
import hashlib
import hmac
import json
import time

import app as webapp
import utils

client = webapp.app.test_client()

U = 9911223344556677


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _jwt(claims, secret, *, bad_sig=False, alg="HS256"):
    header = _b64url(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    payload = _b64url(json.dumps(claims).encode())
    sig = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    if bad_sig:
        sig = bytes(len(sig))
    return f"{header}.{payload}.{_b64url(sig)}"


def _boost(user_id=U):
    conn = utils.get_db()
    try:
        return conn.execute("SELECT * FROM vote_boosts WHERE user_id=?", (user_id,)).fetchone()
    finally:
        conn.close()


def _seed_boost(expires_at, vote_count=1, user_id=U):
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO vote_boosts (user_id, multiplier, expires_at, last_vote_at, vote_count) "
            "VALUES (?, 2.0, ?, ?, ?)",
            (user_id, expires_at, int(time.time()), vote_count),
        )
        conn.commit()
    finally:
        conn.close()


def _topgg_post(secret="topgg-secret", *, tamper=False, weight=1):
    payload = json.dumps({
        "type": "vote.create",
        "data": {
            "user": {"platform_id": str(U), "username": "alice"},
            "weight": weight,
        },
    })
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    if tamper:
        sig = "0" * 64
    return client.post(
        "/webhooks/topgg",
        data=payload,
        content_type="application/json",
        headers={"x-topgg-signature": f"t={ts},v1={sig}"},
    )


def _dlist_post(secret="dlist-secret", user_id=U):
    token = _jwt({"user_id": str(user_id), "bot_id": "1", "is_test": False}, secret)
    return client.post("/webhooks/discordlist", data=token, content_type="text/plain")


def test_topgg_vote_grants_boost_and_queues_side_effects(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")
    resp = _topgg_post()
    assert resp.status_code == 200

    row = _boost()
    assert row is not None
    assert row["multiplier"] == 2.0
    assert abs(row["expires_at"] - (int(time.time()) + 14400)) <= 5
    assert row["vote_count"] == 1

    conn = utils.get_db()
    try:
        dm = conn.execute("SELECT payload FROM pending_dms WHERE kind='vote_thanks'").fetchone()
        payload = json.loads(dm["payload"])
        assert payload["hours"] == 4
        assert payload["source"] == "Top.gg"
        ann = conn.execute("SELECT username, payload FROM pending_vote_announcements").fetchone()
        assert ann["username"] == "alice"
        assert json.loads(ann["payload"])["source"] == "Top.gg"
    finally:
        conn.close()


def test_topgg_weekend_weight_gets_6h(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")
    resp = _topgg_post(weight=2)
    assert resp.status_code == 200
    row = _boost()
    assert abs(row["expires_at"] - (int(time.time()) + 21600)) <= 5

    conn = utils.get_db()
    try:
        dm = conn.execute("SELECT payload FROM pending_dms WHERE kind='vote_thanks'").fetchone()
        assert json.loads(dm["payload"])["hours"] == 6
    finally:
        conn.close()


def test_votes_on_both_lists_stack_duration(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")
    monkeypatch.setenv("DLIST_WEBHOOK_AUTH", "dlist-secret")

    assert _topgg_post().status_code == 200
    first_expiry = _boost()["expires_at"]
    assert _dlist_post().status_code == 200

    row = _boost()
    assert row["vote_count"] == 2
    assert row["expires_at"] == first_expiry + 14400


def test_vote_restarts_expired_boost_from_now(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")
    _seed_boost(int(time.time()) - 3600, vote_count=3)

    assert _topgg_post().status_code == 200

    row = _boost()
    assert row["vote_count"] == 4
    assert abs(row["expires_at"] - (int(time.time()) + 14400)) <= 5


def test_repeated_same_list_vote_is_ignored(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")

    assert _topgg_post().status_code == 200
    first = dict(_boost())
    assert _topgg_post().status_code == 200

    row = _boost()
    assert row["vote_count"] == first["vote_count"]
    assert row["expires_at"] == first["expires_at"]

    conn = utils.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM pending_dms WHERE kind='vote_thanks'").fetchone()[0] == 1
        assert conn.execute("SELECT votes FROM vote_monthly WHERE user_id=?", (U,)).fetchone()["votes"] == 1
    finally:
        conn.close()


def test_same_list_vote_after_cooldown_rewards(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")
    now = int(time.time())

    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO vote_site_history (user_id, source, voted_at) VALUES (?, 'Top.gg', ?)",
            (U, now - 12 * 3600),
        )
        conn.commit()
    finally:
        conn.close()

    assert _topgg_post().status_code == 200
    row = _boost()
    assert row["vote_count"] == 1
    assert abs(row["expires_at"] - (now + 14400)) <= 5


def test_topgg_bad_signature_rejected(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")
    resp = _topgg_post(tamper=True)
    assert resp.status_code == 401
    assert _boost() is None


def test_topgg_refreshes_opted_in_reminder(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")
    conn = utils.get_db()
    try:
        conn.execute("INSERT INTO vote_reminders (user_id, remind_at) VALUES (?, ?)", (U, 123))
        conn.commit()
    finally:
        conn.close()

    assert _topgg_post().status_code == 200

    conn = utils.get_db()
    try:
        remind_at = conn.execute("SELECT remind_at FROM vote_reminders WHERE user_id=?", (U,)).fetchone()["remind_at"]
    finally:
        conn.close()
    assert abs(remind_at - (int(time.time()) + 12 * 3600)) <= 5


def test_discordlist_jwt_body_grants_boost(monkeypatch):
    monkeypatch.setenv("DLIST_WEBHOOK_AUTH", "dlist-secret")
    token = _jwt({"user_id": str(U), "bot_id": "1", "is_test": False}, "dlist-secret")
    resp = client.post("/webhooks/discordlist", data=token, content_type="text/plain")
    assert resp.status_code == 200

    row = _boost()
    assert row is not None
    assert abs(row["expires_at"] - (int(time.time()) + 14400)) <= 5
    assert row["vote_count"] == 1

    conn = utils.get_db()
    try:
        ann = conn.execute("SELECT payload FROM pending_vote_announcements").fetchone()
        assert json.loads(ann["payload"])["source"] == "Discord List"
    finally:
        conn.close()


def test_discordlist_bearer_jwt_grants_boost(monkeypatch):
    monkeypatch.setenv("DLIST_WEBHOOK_AUTH", "dlist-secret")
    token = _jwt({"user_id": str(U)}, "dlist-secret")
    resp = client.post(
        "/webhooks/discordlist",
        data="{}",
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert _boost() is not None


def test_discordlist_json_with_secret_header_grants_boost(monkeypatch):
    monkeypatch.setenv("DLIST_WEBHOOK_AUTH", "dlist-secret")
    resp = client.post(
        "/webhooks/discordlist",
        data=json.dumps({"user_id": str(U)}),
        content_type="application/json",
        headers={"Authorization": "dlist-secret"},
    )
    assert resp.status_code == 200
    assert _boost() is not None


def test_discordlist_test_ping_rewards_nothing(monkeypatch):
    monkeypatch.setenv("DLIST_WEBHOOK_AUTH", "dlist-secret")
    token = _jwt({"user_id": str(U), "is_test": True}, "dlist-secret")
    resp = client.post("/webhooks/discordlist", data=token, content_type="text/plain")
    assert resp.status_code == 200
    assert _boost() is None
    conn = utils.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM pending_dms").fetchone()[0] == 0
    finally:
        conn.close()


def test_discordlist_bad_signature_rejected(monkeypatch):
    monkeypatch.setenv("DLIST_WEBHOOK_AUTH", "dlist-secret")
    token = _jwt({"user_id": str(U)}, "wrong-secret")
    resp = client.post("/webhooks/discordlist", data=token, content_type="text/plain")
    assert resp.status_code == 401
    assert _boost() is None


def test_discordlist_unconfigured(monkeypatch):
    monkeypatch.delenv("DLIST_WEBHOOK_AUTH", raising=False)
    resp = client.post("/webhooks/discordlist", data="x", content_type="text/plain")
    assert resp.status_code == 500


def test_votes_track_each_list_separately(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")
    monkeypatch.setenv("DLIST_WEBHOOK_AUTH", "dlist-secret")

    assert _topgg_post().status_code == 200
    token = _jwt({"user_id": str(U)}, "dlist-secret")
    assert client.post("/webhooks/discordlist", data=token, content_type="text/plain").status_code == 200

    conn = utils.get_db()
    try:
        rows = conn.execute(
            "SELECT source, voted_at FROM vote_site_history WHERE user_id=? ORDER BY source", (U,)
        ).fetchall()
    finally:
        conn.close()
    assert [row["source"] for row in rows] == ["Discord List", "Top.gg"]
    assert _boost()["vote_count"] == 2


def test_reminder_fires_at_soonest_list(monkeypatch):
    monkeypatch.setenv("DLIST_WEBHOOK_AUTH", "dlist-secret")
    old_vote = int(time.time()) - 3600

    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO vote_site_history (user_id, source, voted_at) VALUES (?, 'Top.gg', ?)",
            (U, old_vote),
        )
        conn.execute("INSERT INTO vote_reminders (user_id, remind_at) VALUES (?, ?)", (U, 123))
        conn.commit()
    finally:
        conn.close()

    token = _jwt({"user_id": str(U)}, "dlist-secret")
    assert client.post("/webhooks/discordlist", data=token, content_type="text/plain").status_code == 200

    conn = utils.get_db()
    try:
        remind_at = conn.execute(
            "SELECT remind_at FROM vote_reminders WHERE user_id=?", (U,)
        ).fetchone()["remind_at"]
    finally:
        conn.close()
    # Top.gg (voted an hour ago) frees up first, so the reminder is ~11h out,
    # not 12h out from this Discord List vote.
    assert abs(remind_at - (old_vote + 12 * 3600)) <= 5


def test_vote_site_status_reports_each_timer(monkeypatch):
    now = int(time.time())
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO vote_site_history (user_id, source, voted_at) VALUES (?, 'Top.gg', ?)",
            (U, now - 3600),
        )
        conn.commit()
    finally:
        conn.close()

    status = {name: ready for name, _, ready in utils.vote_site_status(U, now)}
    assert abs(status["Top.gg"] - (now + 11 * 3600)) <= 5
    assert status["Discord List"] is None
    assert abs(utils.vote_next_ready_at(U, now) - (now + 11 * 3600)) <= 5


def test_discordlist_non_object_payload_rejected(monkeypatch):
    monkeypatch.setenv("DLIST_WEBHOOK_AUTH", "dlist-secret")
    resp = client.post(
        "/webhooks/discordlist",
        data=json.dumps([1, 2, 3]),
        content_type="application/json",
        headers={"Authorization": "dlist-secret"},
    )
    assert resp.status_code == 401
    assert _boost() is None


def test_vote_player_info_badge_and_streak():
    today = int(time.time() // 86400)
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO vote_boosts (user_id, multiplier, expires_at, last_vote_at, vote_count) "
            "VALUES (?, 2.0, ?, ?, 30)",
            (U, int(time.time()) + 60, int(time.time())),
        )
        conn.execute(
            "INSERT INTO vote_streaks (user_id, current_streak, longest_streak, last_day) VALUES (?, 6, 9, ?)",
            (U, today),
        )
        conn.commit()
    finally:
        conn.close()

    info = utils.vote_player_info(U)
    assert info["badge"] == "🥈 Silver Voter"
    assert info["streak"] == 6
    assert info["longest_streak"] == 9

    # a streak that stopped more than a day ago reads as broken
    conn = utils.get_db()
    try:
        conn.execute("UPDATE vote_streaks SET last_day=? WHERE user_id=?", (today - 5, U))
        conn.commit()
    finally:
        conn.close()
    assert utils.vote_player_info(U)["streak"] == 0


def test_streak_increments_resets_and_tracks_longest():
    today = int(time.time() // 86400)

    webapp._record_vote(U, "alice", "Top.gg", 14400, 4)
    conn = utils.get_db()
    try:
        row = conn.execute(
            "SELECT current_streak, longest_streak FROM vote_streaks WHERE user_id=?", (U,)
        ).fetchone()
    finally:
        conn.close()
    assert (row["current_streak"], row["longest_streak"]) == (1, 1)

    # a vote yesterday extends the streak
    conn = utils.get_db()
    try:
        conn.execute(
            "UPDATE vote_streaks SET current_streak=4, longest_streak=4, last_day=? WHERE user_id=?",
            (today - 1, U),
        )
        conn.commit()
    finally:
        conn.close()
    webapp._record_vote(U, "alice", "Discord List", 14400, 4)
    conn = utils.get_db()
    try:
        row = conn.execute(
            "SELECT current_streak, longest_streak, last_day FROM vote_streaks WHERE user_id=?", (U,)
        ).fetchone()
    finally:
        conn.close()
    assert (row["current_streak"], row["longest_streak"], row["last_day"]) == (5, 5, today)

    # a second vote the same day does not double count
    webapp._record_vote(U, "alice", "Third List", 14400, 4)
    conn = utils.get_db()
    try:
        row = conn.execute("SELECT current_streak FROM vote_streaks WHERE user_id=?", (U,)).fetchone()
    finally:
        conn.close()
    assert row["current_streak"] == 5

    # skipping days resets the current streak but keeps the record
    conn = utils.get_db()
    try:
        conn.execute(
            "UPDATE vote_streaks SET current_streak=9, longest_streak=9, last_day=? WHERE user_id=?",
            (today - 5, U),
        )
        conn.commit()
    finally:
        conn.close()
    webapp._record_vote(U, "alice", "Fourth List", 14400, 4)
    conn = utils.get_db()
    try:
        row = conn.execute(
            "SELECT current_streak, longest_streak FROM vote_streaks WHERE user_id=?", (U,)
        ).fetchone()
    finally:
        conn.close()
    assert (row["current_streak"], row["longest_streak"]) == (1, 9)


def test_monthly_tally_and_badge_unlock_payload():
    month = time.strftime("%Y-%m", time.gmtime())
    _seed_boost(int(time.time()) + 60, vote_count=4)

    webapp._record_vote(U, "alice", "Discord List", 14400, 4)

    conn = utils.get_db()
    try:
        votes = conn.execute(
            "SELECT votes FROM vote_monthly WHERE user_id=? AND month=?", (U, month)
        ).fetchone()["votes"]
        dm = json.loads(
            conn.execute("SELECT payload FROM pending_dms WHERE kind='vote_thanks'").fetchone()["payload"]
        )
    finally:
        conn.close()
    assert votes == 1
    assert dm["vote_count"] == 5
    assert dm["badge"] == "🥉 Bronze Voter"
    assert dm["unlocked_badge"] == "🥉 Bronze Voter"


def test_voters_leaderboard_ranks_monthly_votes():
    from cogs import leveling

    month = time.strftime("%Y-%m", time.gmtime())
    now = int(time.time())
    conn = utils.get_db()
    try:
        for uid, votes, count, last in ((1, 3, 3, now - 100), (2, 5, 8, now - 50)):
            conn.execute(
                "INSERT INTO vote_boosts (user_id, multiplier, expires_at, last_vote_at, vote_count) "
                "VALUES (?, 2.0, ?, ?, ?)",
                (uid, now + 60, last, count),
            )
            conn.execute(
                "INSERT INTO vote_monthly (user_id, month, votes) VALUES (?, ?, ?)", (uid, month, votes)
            )
        conn.commit()
    finally:
        conn.close()

    rows, total = leveling._fetch_leaderboard(0, "Voters", False, 1)
    assert total == 2
    assert [row["user_id"] for row in rows] == [2, 1]
    assert rows[0]["value"] == 5


def test_voters_page_lists_monthly_top():
    month = time.strftime("%Y-%m", time.gmtime())
    now = int(time.time())
    conn = utils.get_db()
    try:
        for uid, votes, count in ((2, 5, 12), (1, 3, 1)):
            conn.execute(
                "INSERT INTO vote_boosts (user_id, multiplier, expires_at, last_vote_at, vote_count) "
                "VALUES (?, 2.0, ?, ?, ?)",
                (uid, now + 60, now, count),
            )
            conn.execute(
                "INSERT INTO vote_monthly (user_id, month, votes) VALUES (?, ?, ?)", (uid, month, votes)
            )
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/voters")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Vote for" in body
    assert "Monthly top voters" in body
    assert "Bronze Voter" in body
    assert body.index("Voter 2") < body.index("Voter 1")


def test_voters_page_month_picker_loads_previous_months():
    old = "2020-01"
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO vote_monthly (user_id, month, votes) VALUES (?, ?, ?)", (7, old, 9)
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.get(f"/voters?month={old}")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "January 2020" in body
    assert "Voter 7" in body
    assert 'value="2020-01" selected' in body

    fallback = client.get("/voters?month=not-a-month")
    assert fallback.status_code == 200
    assert "(current)" in fallback.data.decode()


def _seed_monthly_voters(count):
    month = time.strftime("%Y-%m", time.gmtime())
    now = int(time.time())
    conn = utils.get_db()
    try:
        for i in range(1, count + 1):
            uid = 1000 + i
            conn.execute(
                "INSERT INTO users (guild_id, user_id, display_name, username, total_xp) "
                "VALUES (?, ?, ?, ?, ?)",
                (1, uid, f"Voter {i}", f"voter{i}", 1000 - i),
            )
            conn.execute(
                "INSERT INTO vote_boosts (user_id, multiplier, expires_at, last_vote_at, vote_count) "
                "VALUES (?, 2.0, ?, ?, ?)",
                (uid, now + 60, now, i),
            )
            conn.execute(
                "INSERT INTO vote_monthly (user_id, month, votes) VALUES (?, ?, ?)",
                (uid, month, 100 - i),
            )
        conn.commit()
    finally:
        conn.close()


def test_voters_page_find_jumps_to_page_and_highlights():
    _seed_monthly_voters(30)

    resp = client.get("/voters?find=Voter%2028")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Page 2 of 2" in body
    assert "Voter 28</strong> is" in body
    assert "#28" in body
    assert "voters-row--found" in body


def test_voters_page_paginates_and_clamps():
    _seed_monthly_voters(30)

    resp = client.get("/voters?page=2")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Page 2 of 2" in body
    assert "#26" in body
    assert "#30" in body
    assert "voters-podium" not in body

    clamped = client.get("/voters?page=99")
    assert "Page 2 of 2" in clamped.data.decode()

    explicit = client.get("/voters?find=Voter%2028&page=1")
    assert "Page 1 of 2" in explicit.data.decode()


def test_voters_page_streak_leaders():
    today = int(time.time() // 86400)
    conn = utils.get_db()
    try:
        for uid, name, current, longest, last_day in (
            (2001, "Alpha", 10, 12, today),
            (2002, "Beta", 7, 7, today - 1),
            (2003, "Gamma", 3, 3, today),
            (2004, "Ghost", 50, 50, today - 5),
        ):
            conn.execute(
                "INSERT INTO users (guild_id, user_id, display_name, username) VALUES (1, ?, ?, ?)",
                (uid, name, name.lower()),
            )
            conn.execute(
                "INSERT INTO vote_streaks (user_id, current_streak, longest_streak, last_day) "
                "VALUES (?, ?, ?, ?)",
                (uid, current, longest, last_day),
            )
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/voters")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Streak leaders" in body
    assert body.index("Alpha") < body.index("Beta") < body.index("Gamma")
    assert "Ghost" not in body


def test_vote_badge_progress_tiers():
    assert utils.vote_badge_progress(0) == {
        "label": "🥉 Bronze Voter", "threshold": 5, "remaining": 5,
    }
    assert utils.vote_badge_progress(4)["remaining"] == 1
    assert utils.vote_badge_progress(5)["label"] == "🥈 Silver Voter"
    assert utils.vote_badge_progress(5)["remaining"] == 20
    assert utils.vote_badge_progress(25)["remaining"] == 75
    assert utils.vote_badge_progress(99)["remaining"] == 1
    assert utils.vote_badge_progress(100) is None


def test_disable_vote_reminders():
    conn = utils.get_db()
    try:
        conn.execute("INSERT INTO vote_reminders (user_id, remind_at) VALUES (?, ?)", (U, 123))
        conn.commit()
    finally:
        conn.close()

    assert utils.disable_vote_reminders(U) is True
    assert utils.disable_vote_reminders(U) is False

    conn = utils.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM vote_reminders WHERE user_id=?", (U,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_vote_info_reports_per_site_timers(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")
    assert _topgg_post().status_code == 200

    info = webapp._vote_info(U)
    sites = {site["name"]: site for site in info["sites"]}
    assert sites["Top.gg"]["ready_minutes"] > 0
    assert sites["Discord List"]["ready_minutes"] is None
    assert info["badge_progress"]["remaining"] == 4


def test_thanks_payload_nudges_the_other_list(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")
    assert _topgg_post().status_code == 200

    conn = utils.get_db()
    try:
        payload = json.loads(
            conn.execute(
                "SELECT payload FROM pending_dms WHERE kind='vote_thanks' ORDER BY id DESC LIMIT 1"
            ).fetchone()["payload"]
        )
    finally:
        conn.close()
    assert payload["other_ready"] == ["Discord List"]
    assert payload["other_cooling"] == []


def test_thanks_payload_stops_nudging_once_both_are_cooling(monkeypatch):
    monkeypatch.setenv("TOPGG_WEBHOOK_AUTH", "topgg-secret")
    monkeypatch.setenv("DLIST_WEBHOOK_AUTH", "dlist-secret")
    assert _topgg_post().status_code == 200
    token = _jwt({"user_id": str(U)}, "dlist-secret")
    assert client.post("/webhooks/discordlist", data=token, content_type="text/plain").status_code == 200

    conn = utils.get_db()
    try:
        payload = json.loads(
            conn.execute(
                "SELECT payload FROM pending_dms WHERE kind='vote_thanks' ORDER BY id DESC LIMIT 1"
            ).fetchone()["payload"]
        )
    finally:
        conn.close()
    assert payload["other_ready"] == []
    assert payload["other_cooling"] == ["Top.gg"]


def test_streak_risk_candidates_only_opted_in_and_unvoted():
    from cogs import events

    day = int(time.time() // 86400)
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO vote_streaks (user_id, current_streak, longest_streak, last_day) VALUES (1, 4, 6, ?)",
            (day - 1,),
        )
        conn.execute("INSERT INTO vote_reminders (user_id, remind_at) VALUES (1, 0)")
        conn.execute(
            "INSERT INTO vote_streaks (user_id, current_streak, longest_streak, last_day) VALUES (2, 5, 5, ?)",
            (day,),
        )
        conn.execute("INSERT INTO vote_reminders (user_id, remind_at) VALUES (2, 0)")
        conn.execute(
            "INSERT INTO vote_streaks (user_id, current_streak, longest_streak, last_day) VALUES (3, 3, 3, ?)",
            (day - 1,),
        )
        conn.commit()

        cur = conn.cursor()
        assert [row["user_id"] for row in events.streak_risk_candidates(cur, day)] == [1]

        conn.execute("UPDATE vote_reminders SET risk_ping_day = ? WHERE user_id = 1", (day,))
        conn.commit()
        assert events.streak_risk_candidates(cur, day) == []
    finally:
        conn.close()


def test_votes_stack_instead_of_overwriting(monkeypatch):
    monkeypatch.setenv("DLIST_WEBHOOK_AUTH", "dlist-secret")

    # A longer boost from earlier votes survives, and the new duration stacks on top.
    seeded = int(time.time()) + 20000
    _seed_boost(seeded, vote_count=4)
    assert _dlist_post().status_code == 200
    row = _boost()
    assert row["expires_at"] == seeded + 14400
    assert row["vote_count"] == 5

    # An expired boost restarts from now + 4h (via the other list, since the
    # same list is still inside its own 12h cooldown).
    conn = utils.get_db()
    try:
        conn.execute(
            "UPDATE vote_boosts SET expires_at = ? WHERE user_id=?",
            (int(time.time()) - 60, U),
        )
        conn.commit()
    finally:
        conn.close()
    webapp._record_vote(U, "alice", "Top.gg", 14400, 4)
    row = _boost()
    assert abs(row["expires_at"] - (int(time.time()) + 14400)) <= 5
    assert row["vote_count"] == 6
