import sqlite3
from types import SimpleNamespace

from cogs.music import (
    MusicCog,
    _delete_playlist_track,
    _insert_track_row,
    _move_playlist_track,
    _normalize_query,
    _playlist_dup_check,
    _playlist_track_rows,
    _shuffle_playlist,
    _source_label,
    _track_source,
)


def _make_playable(title, author, uri, length_ms=180_000, source="youtube"):
    return SimpleNamespace(title=title, author=author, uri=uri, length=length_ms, source=source)


def _playlist_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE playlist_tracks ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, playlist_id INTEGER, position INTEGER, "
        "query TEXT, title TEXT, author TEXT, uri TEXT, artwork TEXT, length_ms INTEGER, "
        "source TEXT, added_at INTEGER)"
    )
    return conn


def test_insert_track_row_adds_and_counts_position():
    conn = _playlist_conn()
    try:
        assert _insert_track_row(conn, 1, _make_playable("A", "Me", "a1"), "query", 1000) == ("added", 1)
        assert _insert_track_row(conn, 1, _make_playable("B", "Me", "b2"), "query", 1000) == ("added", 2)
        rows = _playlist_track_rows(conn, 1)
        assert [r["position"] for r in rows] == [1, 2]
        assert [r["uri"] for r in rows] == ["a1", "b2"]
    finally:
        conn.close()


def test_insert_track_row_dedupes_uri_and_title():
    conn = _playlist_conn()
    try:
        _insert_track_row(conn, 1, _make_playable("Hello", "World", "u1"), "q", 1000)
        assert _insert_track_row(conn, 1, _make_playable("Hello 2", "Other", "u1"), "q", 1000)[0] == "dup"
        assert _insert_track_row(conn, 1, _make_playable("hello", "world", "u9"), "q", 1000)[0] == "dup"
        assert _insert_track_row(conn, 1, _make_playable("Different", "World", "u3"), "q", 1000)[0] == "added"
    finally:
        conn.close()


def test_delete_playlist_track_renumbers():
    conn = _playlist_conn()
    try:
        for i in range(3):
            _insert_track_row(conn, 1, _make_playable(f"T{i}", "Me", f"u{i}"), "q", 1000)
        removed = _delete_playlist_track(conn, 1, 1)
        assert removed["title"] == "T1"
        assert [r["position"] for r in _playlist_track_rows(conn, 1)] == [1, 2]
    finally:
        conn.close()


def test_move_playlist_track_persists_order():
    conn = _playlist_conn()
    try:
        for i in range(4):
            _insert_track_row(conn, 1, _make_playable(f"T{i}", "Me", f"u{i}"), "q", 1000)
        assert _move_playlist_track(conn, 1, 3, 0) is True
        assert [r["title"] for r in _playlist_track_rows(conn, 1)] == ["T3", "T1", "T2", "T0"]
        assert _move_playlist_track(conn, 1, 0, 3) is True
        assert [r["title"] for r in _playlist_track_rows(conn, 1)] == ["T0", "T1", "T2", "T3"]
        assert _move_playlist_track(conn, 1, 0, 99) is False
    finally:
        conn.close()


def test_shuffle_playlist_keeps_all_tracks():
    conn = _playlist_conn()
    try:
        for i in range(5):
            _insert_track_row(conn, 1, _make_playable(f"T{i}", "Me", f"u{i}"), "q", 1000)
        count = _shuffle_playlist(conn, 1)
        assert count == 5
        assert sorted(r["title"] for r in _playlist_track_rows(conn, 1)) == ["T0", "T1", "T2", "T3", "T4"]
    finally:
        conn.close()


def test_playlist_dup_check_uri():
    conn = _playlist_conn()
    try:
        assert _playlist_dup_check(conn, 1, "u1", "Hello", "World") is False
        _insert_track_row(conn, 1, _make_playable("Hello", "World", "u1"), "q", 1000)
        assert _playlist_dup_check(conn, 1, "u1", "Hello", "World") is True
    finally:
        conn.close()


def test_normalize_query_empty():
    assert _normalize_query("") is None
    assert _normalize_query("   ") is None
    assert _normalize_query(None) is None


def test_normalize_query_strips_prefixes():
    assert _normalize_query("query:lo-fi beats") == "lo-fi beats"
    assert _normalize_query("/query:hello") == "hello"
    assert _normalize_query("query:") is None


def test_normalize_query_spotify_prefix_kept():
    assert _normalize_query("spsearch:drake") == "spsearch:drake"
    assert _normalize_query("  spsearch:  nedted") == "spsearch:nedted"


def test_normalize_query_other_prefixes_dropped():
    assert _normalize_query("ytsearch:never gonna give you up") == "never gonna give you up"
    assert _normalize_query("scsearch:lo-fi") == "lo-fi"
    assert _normalize_query("ytmsearch:song") == "song"
    assert _normalize_query("ytsearch:") is None


def test_normalize_query_links_passthrough():
    assert _normalize_query("https://www.youtube.com/watch?v=dQw4w9WgXcQ").startswith("https://")
    assert _normalize_query("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT") == "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
    assert _normalize_query("spotify:track:4cOdK2wGLETKBW3PvgPWqT") == "spotify:track:4cOdK2wGLETKBW3PvgPWqT"
    assert _normalize_query("plain text query") == "plain text query"


def test_source_label():
    assert _source_label("youtube") == "YouTube"
    assert _source_label("YouTube") == "YouTube"
    assert _source_label("spotify") == "Spotify"
    assert _source_label("soundcloud") == "SoundCloud"
    assert _source_label("weird") == "Weird"
    assert _source_label("") == "Unknown"
    assert _source_label(None) == "Unknown"


def test_track_source_prefers_requested():
    track = SimpleNamespace(
        extras=SimpleNamespace(requested_source="spotify"),
        source="youtube",
    )
    assert _track_source(track) == "spotify"


def test_track_source_falls_back_to_source():
    track = SimpleNamespace(
        extras=SimpleNamespace(requested_source=None),
        source="youtube",
    )
    assert _track_source(track) == "youtube"


def test_track_source_none():
    assert _track_source(None) == ""


def _make_track(source):
    return SimpleNamespace(source=source)


def _filter(platform, *sources):
    tracks = [_make_track(s) for s in sources]
    return [t.source for t in MusicCog._filter_platform(tracks, platform)]


def test_filter_platform_soundcloud_keeps_only_matching():
    assert _filter("soundcloud", "soundcloud", "youtube", "spotify") == ["soundcloud"]


def test_filter_platform_soundcloud_falls_back_to_all():
    assert _filter("soundcloud", "youtube", "spotify") == ["youtube", "spotify"]


def test_filter_platform_spotify_keeps_only_matching():
    assert _filter("spotify", "youtube", "spotify") == ["spotify"]


def test_filter_platform_youtube_keeps_yt_and_music():
    assert _filter("youtube", "youtube", "youtubemusic", "spotify") == ["youtube", "youtubemusic"]