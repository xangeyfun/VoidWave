from cogs.ai import _fmt_duration


def test_fmt_duration_seconds():
    assert _fmt_duration(0.4) == "about 0s"
    assert _fmt_duration(5) == "about 5s"
    assert _fmt_duration(59) == "about 59s"


def test_fmt_duration_minutes():
    assert _fmt_duration(60) == "about 1m"
    assert _fmt_duration(90) == "about 1m 30s"
    assert _fmt_duration(95) == "about 1m 35s"
    assert _fmt_duration(300) == "about 5m"


def test_fmt_duration_negative_clamped():
    assert _fmt_duration(-3) == "about 0s"