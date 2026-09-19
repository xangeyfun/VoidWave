#!/usr/bin/env python3
"""One-time cleanup: collapse stats_history.json to one snapshot per hour.

Keeps the most recent snapshot in each hour bucket, preserving order.
Run once (stats_history.json.bak already exists as a backup).
"""
import datetime
import json
import sys

FILE = "stats_history.json"


def hour_key(ts):
    try:
        return datetime.datetime.fromisoformat(ts).strftime("%Y-%m-%dT%H")
    except (ValueError, TypeError):
        return None


def main():
    with open(FILE, "r") as f:
        history = json.load(f)
    before = len(history)

    seen = set()
    cleaned = []
    for s in reversed(history):
        k = hour_key(s.get("timestamp", ""))
        if k:
            if k in seen:
                continue
            seen.add(k)
        cleaned.append(s)
    cleaned.reverse()

    with open(FILE, "w") as f:
        json.dump(cleaned, f, indent=2)

    print(f"{before} -> {len(cleaned)} snapshots ({before - len(cleaned)} removed)")


if __name__ == "__main__":
    sys.exit(main())