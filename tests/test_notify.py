import logging

from notify import DiscordAlertHandler


def _record(name, level, message="boom"):
    return logging.LogRecord(name, level, __file__, 1, message, (), None)


def test_track_exception_errors_do_not_alert():
    handler = DiscordAlertHandler()
    try:
        assert not handler._allowed(_record("TrackException", logging.ERROR))
    finally:
        handler.close()


def test_other_errors_still_alert():
    handler = DiscordAlertHandler()
    try:
        assert handler._allowed(_record("cogs.music", logging.ERROR))
    finally:
        handler.close()
