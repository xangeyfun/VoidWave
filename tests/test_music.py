import sqlite3
from types import SimpleNamespace

import wavelink

from cogs.music import (
    MusicCog,
    VoidWavePlayer,
    _current_line,
    _delete_playlist_track,
    _insert_track_row,
    _is_link,
    _move_playlist_track,
    _normalize_query,
    _parse_lrc,
    _parse_seek,
    _playlist_dup_check,
    _playlist_track_rows,
    _progress_bar,
    _short,
    _shuffle_playlist,
    _source_icon,
    _source_label,
    _spotify_link,
    _track_source,
    fmt,
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

def test_fmt_handles_none_and_zero():
    assert fmt(None) == "0:00"
    assert fmt(0) == "0:00"
    assert fmt(5000) == "0:05"
    assert fmt(65000) == "1:05"
    assert fmt(3_600_000) == "1h 0m 0s"
    assert fmt(3_723_000) == "1h 2m 3s"


def test_parse_seek_variants():
    assert _parse_seek("1:30") == 90_000
    assert _parse_seek("90") == 90_000
    assert _parse_seek("0") == 0
    assert _parse_seek("1h") == 3_600_000
    assert _parse_seek("1m30s") == 90_000
    assert _parse_seek("1h30m") == 5_400_000
    assert _parse_seek("1:2:3") == 3_723_000


def test_parse_seek_invalid():
    assert _parse_seek("") is None
    assert _parse_seek("   ") is None
    assert _parse_seek("1:2:3:4") is None
    assert _parse_seek("-5") is None
    assert _parse_seek("abc") is None


def test_progress_bar_zero_length_has_no_marker():
    bar = _progress_bar(50, 0)
    assert len(bar) == 18
    assert "●" not in bar
    assert set(bar) == {"░"}


def test_progress_bar_midpoint_places_marker():
    bar = _progress_bar(90_000, 180_000)
    assert len(bar) == 18
    assert bar.count("●") == 1
    assert bar.count("▓") == 8
    assert bar.index("●") == 8


def test_parse_lrc_fractional_ms():
    assert _parse_lrc("[00:20.50]World") == [(20_500, "World")]
    assert _parse_lrc("[00:10.500]X") == [(10_500, "X")]


def test_parse_lrc_multiple_timestamps_per_line():
    assert _parse_lrc("[00:10][00:30]Chorus") == [(10_000, "Chorus"), (30_000, "Chorus")]


def test_parse_lrc_dedupes_identical_timestamps():
    assert _parse_lrc("[00:10]A\n[00:10]B") == [(10_000, "A")]


def test_parse_lrc_sorts_entries():
    assert _parse_lrc("[01:00]b\n[00:10]a") == [(10_000, "a"), (60_000, "b")]


def test_parse_lrc_without_timestamps_is_empty():
    assert _parse_lrc("just plain text") == []
    assert _parse_lrc("") == []


def test_current_line_boundaries():
    entries = [(1000, "a"), (2000, "b"), (3000, "c")]
    assert _current_line(entries, 1000) == 0
    assert _current_line(entries, 2000) == 1
    assert _current_line(entries, 9999) == 2
    assert _current_line(entries, 500) == 0
    assert _current_line([], 500) is None


def test_short_truncates_with_ellipsis():
    assert _short("abc", 5) == "abc"
    assert _short("abcdefghij", 5) == "abcd…"
    assert len(_short("abcdefghij", 5)) == 5


def test_is_link():
    assert _is_link("https://example.com") is True
    assert _is_link("http://example.com") is True
    assert _is_link("plain text") is False
    assert _is_link("") is False
    assert _is_link(None) is False


def test_spotify_link_normalizes_uri_and_passthrough():
    assert _spotify_link("spotify:track:4cOdK2wGLETKBW3PvgPWqT") == "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
    url = "https://open.spotify.com/intl-de/track/4cOdK2wGLETKBW3PvgPWqT"
    assert _spotify_link(url) == url
    assert _spotify_link("not a link") is None
    assert _spotify_link("") is None


def test_source_icon_falls_back_to_note():
    assert _source_icon("zzz") == "🎵"
    assert _source_icon(None) == "🎵"
    assert _source_icon("youtube") != "🎵"


def test_autoplay_required_attrs_still_exist_on_wavelink_player():
    import inspect

    source = inspect.getsource(wavelink.Player)
    assert VoidWavePlayer._AUTOPLAY_REQUIRED_ATTRS
    for attr in VoidWavePlayer._AUTOPLAY_REQUIRED_ATTRS:
        source_name = attr.removeprefix("_Player")
        assert source_name in source, f"wavelink.Player no longer references {attr}"
