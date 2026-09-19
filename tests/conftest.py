import sqlite3

import pytest

import utils
from schema import create_schema


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