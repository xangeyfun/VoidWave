import time

import utils

U = 8811223344556677


def _seed_history(source, voted_at):
    conn = utils.get_db()
    try:
        conn.execute(
            "INSERT INTO vote_site_history (user_id, source, voted_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, source) DO UPDATE SET voted_at = excluded.voted_at",
            (U, source, voted_at),
        )
        conn.commit()
    finally:
        conn.close()


def test_nudge_offered_to_brand_new_user():
    nudge = utils.vote_nudge(U)
    assert nudge is not None
    assert nudge["site"] == "Top.gg"
    assert nudge["url"].startswith("https://top.gg/")
    assert nudge["emoji"] == ("topgg", 1562055047422935040)


def test_nudge_offered_when_only_one_list_ready():
    now = int(time.time())
    _seed_history("Top.gg", now)

    nudge = utils.vote_nudge(U, now)
    assert nudge is not None
    assert nudge["site"] == "Discord List"
    assert nudge["emoji"] == ("discordlist", 1562055045984424056)


def test_nudge_skipped_while_every_list_is_cooling_down():
    now = int(time.time())
    _seed_history("Top.gg", now)
    _seed_history("Discord List", now - 60)

    assert utils.vote_nudge(U, now) is None


def test_nudge_offered_again_after_cooldown_expires():
    now = int(time.time())
    _seed_history("Top.gg", now - utils.VOTE_SITE_COOLDOWN)
    _seed_history("Discord List", now - 60)

    nudge = utils.vote_nudge(U, now)
    assert nudge is not None
    assert nudge["site"] == "Top.gg"


def test_nudge_command_allowlist_excludes_button_commands():
    for name in ("tictactoe", "leaderboard", "help", "music", "vote", "vote-remind"):
        assert name not in utils.VOTE_NUDGE_COMMANDS
    for name in ("8ball", "ai", "profile", "ping"):
        assert name in utils.VOTE_NUDGE_COMMANDS
