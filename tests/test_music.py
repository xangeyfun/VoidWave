from types import SimpleNamespace

from cogs.music import MusicCog, _normalize_query, _source_label, _track_source


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