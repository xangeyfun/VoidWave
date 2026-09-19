import json
import os

import generate_graphs
import purge_stats_hourly


def _snapshot(ts, guilds=10, members=500, users=300, xp=10000, messages=5000,
              msgs_xp=2000, vc_min=360, vc_xp=180, level=4, ratings=10, rating=4.5):
    return {
        "timestamp": ts,
        "total_guilds": guilds,
        "total_members": members,
        "total_users": users,
        "total_xp": xp,
        "total_messages": messages,
        "total_messages_xp": msgs_xp,
        "total_vc_minutes": vc_min,
        "total_vc_xp_minutes": vc_xp,
        "avg_level": level,
        "total_ratings": ratings,
        "avg_rating": rating,
        "rating_distribution": {1: 1, 2: 1, 3: 1, 4: 3, 5: 4},
    }


def test_purge_stats_hourly_collapses_hours():
    entries = [
        _snapshot("2026-09-18T10:15:00", guilds=5),
        _snapshot("2026-09-18T10:45:00", guilds=7),
        _snapshot("2026-09-18T11:05:00", guilds=8),
    ]
    with open("stats_history.json", "w") as f:
        json.dump(entries, f)

    purge_stats_hourly.main()

    with open("stats_history.json") as f:
        cleaned = json.load(f)
    assert len(cleaned) == 2
    assert cleaned[0]["timestamp"] == "2026-09-18T10:45:00"
    assert cleaned[1]["timestamp"] == "2026-09-18T11:05:00"
    assert cleaned[0]["total_guilds"] == 7


def test_generate_graphs_emits_pngs():
    entries = [
        _snapshot("2026-09-01T10:00:00", guilds=2, members=100, users=50, xp=1000,
                  messages=500, msgs_xp=200, vc_min=300, vc_xp=150, level=3),
        _snapshot("2026-09-02T10:00:00", guilds=3, members=150, users=80, xp=2500,
                  messages=900, msgs_xp=400, vc_min=420, vc_xp=200, level=4),
        _snapshot("2026-09-03T10:00:00", guilds=3, members=160, users=100, xp=4000,
                  messages=1300, msgs_xp=600, vc_min=540, vc_xp=260, level=5),
    ]
    with open("stats_history.json", "w") as f:
        json.dump(entries, f)
    os.makedirs(os.path.join("static", "images"), exist_ok=True)

    generate_graphs.main()

    graphs_dir = os.listdir("Graphs")
    graph_pngs = [name for name in graphs_dir if name.endswith(".png")]
    assert len(graph_pngs) == 14
    assert "13_all_stats.png" in graph_pngs
    assert "14_ratios_overview.png" in graph_pngs
    assert os.path.exists(os.path.join("static", "images", "stats.png"))


def test_generate_graphs_skips_when_no_data():
    generate_graphs.main()
    assert not os.path.exists("Graphs")