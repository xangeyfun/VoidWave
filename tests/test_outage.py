import json

import pytest

import outage

START = 1790848800
END = 1790874000


class OutageFiles:
    """Throwaway outage.json plus bot_bio.txt for a single test."""

    def __init__(self, path, bio_path):
        self.path = path
        self.bio_path = bio_path

    def write(self, data):
        self.path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        self.reset_cache()

    def write_bio(self, text):
        self.bio_path.write_text(text, encoding="utf-8")

    @staticmethod
    def reset_cache():
        outage._cache["key"] = None
        outage._cache["data"] = None


@pytest.fixture
def outage_files(tmp_path, monkeypatch):
    files = OutageFiles(tmp_path / "outage.json", tmp_path / "bot_bio.txt")
    monkeypatch.setattr(outage, "OUTAGE_FILE", str(files.path))
    monkeypatch.setattr(outage, "BIO_FILE", str(files.bio_path))
    files.reset_cache()
    return files


def _announcement(**overrides):
    data = {
        "label": "Planned power outage",
        "message": "I may be offline briefly between {start} and {end}.",
        "start": START,
        "end": END,
        "tz": "Europe/Amsterdam",
    }
    data.update(overrides)
    return data


def test_announcement_fills_placeholders(outage_files):
    outage_files.write(_announcement())

    item = outage.announcement(now=START + 3600)

    assert item["label"] == "Planned power outage"
    assert "Thu 01 Oct, 12:00" in item["message"]
    assert "Thu 01 Oct, 19:00" in item["message"]
    assert item["discord_message"] == "I may be offline briefly between <t:1790848800:t> and <t:1790874000:t>."


def test_announcement_defaults_when_label_and_message_missing(outage_files):
    outage_files.write({"start": START, "end": END})

    item = outage.announcement(now=START)

    assert item["label"] == outage.DEFAULT_LABEL
    assert "{start}" not in item["message"]


def test_announcement_expired(outage_files):
    outage_files.write(_announcement())

    assert outage.announcement(now=END) is None
    assert outage.announcement(now=END + 1) is None
    assert outage.countdown(now=END + 1) is None
    assert outage.status_text(now=END + 1) is None


def test_announcement_ignored_without_end(outage_files):
    outage_files.write(_announcement(end=0))
    assert outage.announcement(now=START) is None

    outage_files.write({"start": START})
    assert outage.announcement(now=START) is None


def test_announcement_missing_file(outage_files):
    outage_files.write(_announcement())
    outage_files.path.unlink()
    outage_files.reset_cache()

    assert outage.load() is None
    assert outage.announcement(now=START) is None


def test_announcement_corrupt_file(outage_files):
    outage_files.write("{not json")

    assert outage.load() is None
    assert outage.announcement(now=START) is None


def test_bad_placeholders_do_not_raise(outage_files):
    outage_files.write(_announcement(message="down until {nope}"))

    assert outage.announcement(now=START)["message"] == "down until {nope}"


def test_countdown_formats(outage_files):
    outage_files.write(_announcement())

    assert outage.countdown(now=END - 5 * 3600 - 30 * 60) == "5h 30m"
    assert outage.countdown(now=END - 20 * 60) == "20m"
    assert outage.countdown(now=END - 30) == "1m"


def test_status_text_during_and_before_window(outage_files):
    outage_files.write(_announcement(label="Scheduled maintenance"))

    assert outage.status_text(now=START + 10 * 60) == "/help • scheduled maintenance • back by 6h 50m"
    assert outage.status_text(now=START - 60 * 60) == "/help • scheduled maintenance • starts in 8h 0m"


def test_bio_text_prepends_outage_line_to_base_bio(outage_files):
    outage_files.write(_announcement())
    outage_files.write_bio("VoidWave is free.\n")

    bio = outage.bio_text(now=START)

    assert bio.startswith("Planned power outage: I may be offline briefly between <t:1790848800:t>")
    assert bio.endswith("VoidWave is free.")


def test_bio_text_falls_back_to_base_bio_when_no_outage(outage_files):
    outage_files.write(_announcement(end=0))
    outage_files.write_bio("VoidWave is free.\n")

    assert outage.bio_text() == "VoidWave is free."