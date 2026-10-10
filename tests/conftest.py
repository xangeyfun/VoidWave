import logging
import sqlite3

import pytest

import utils
from schema import create_schema


@pytest.fixture(autouse=True)
def no_discord_alerts(monkeypatch):
    """Keep the suite network-free. Importing app.py calls setup_logging(), which
    attaches a DiscordAlertHandler to the root logger; any ERROR logged by a test
    (for example the intentional "stats_history.json not found" case) would then be
    POSTed to the operator's webhook."""
    monkeypatch.setenv("ERROR_WEBHOOK_URL", "")
    monkeypatch.setenv("ADMIN_WEBHOOK_URL", "")
    try:
        from notify import DiscordAlertHandler
    except Exception:
        return
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, DiscordAlertHandler):
            root.removeHandler(handler)
            handler.close()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point every CWD-relative path (database.db, stats_history.json, ...) at
    a throwaway dir and build the real schema there. The production database.db
    is never touched."""
    monkeypatch.chdir(tmp_path)
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    conn.close()
    utils.last_xp.clear()
    utils.last_vc.clear()
    yield
    utils.last_xp.clear()
    utils.last_vc.clear()