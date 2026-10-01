"""Reusable outage announcement for the bot presence and the website banner.

The announcement lives in `outage.json` at the repo root so a future outage is
one small edit. Both processes re-read the file whenever its mtime changes, so
there is no restart and no shared cache to clear:

    {
      "label": "Planned power outage",
      "message": "I may be offline briefly at some point today between {start} and {end}.",
      "start": 1790848800,
      "end": 1790874000,
      "tz": "Europe/Amsterdam"
    }

`label` and `message` are optional (defaults: "Scheduled downtime" and a generic
sentence). `message` may use the `{start}` and `{end}` placeholders. `start` and
`end` are unix seconds and `end` is what expires the announcement, so setting
`"end": 0`, `"end": null`, or deleting the file clears everything. The Discord
bio helper fills `{start}` and `{end}` with `<t:...:t>` timestamps so each reader
sees the window in their own timezone.

Stdlib only, so bot.py and app.py can both import it without pulling in
discord.py or flask. Run `python outage.py` to print the ready to paste bio.
"""

import datetime
import json
import os
import time
from zoneinfo import ZoneInfo

OUTAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outage.json')
BIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_bio.txt')
DEFAULT_TZ = 'Europe/Amsterdam'
DEFAULT_LABEL = 'Scheduled downtime'
DEFAULT_MESSAGE = 'VoidWave may be unavailable between {start} and {end}.'

_cache = {'key': None, 'data': None}


def _tz(name=None):
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def load():
    """Parsed outage.json, or None when absent, empty, or unreadable."""
    try:
        stat = os.stat(OUTAGE_FILE)
    except OSError:
        _cache['key'] = None
        _cache['data'] = None
        return None
    key = (stat.st_mtime_ns, stat.st_size)
    if _cache['key'] != key:
        try:
            with open(OUTAGE_FILE, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict):
            data = None
        _cache['key'] = key
        _cache['data'] = data
    return _cache['data']


def announcement(now=None):
    """The active announcement with both message flavours filled in, else None."""
    data = load()
    if not data or not data.get('end'):
        return None
    end = int(data['end'])
    now = time.time() if now is None else now
    if now >= end:
        return None
    start = int(data.get('start') or end)
    tz = _tz(data.get('tz'))
    fmt = '%a %d %b, %H:%M'
    try:
        local = {
            'start': datetime.datetime.fromtimestamp(start, tz).strftime(fmt),
            'end': datetime.datetime.fromtimestamp(end, tz).strftime(fmt),
        }
    except (OverflowError, OSError, ValueError):
        local = {'start': '', 'end': ''}
    discord_stamps = {'start': f"<t:{start}:t>", 'end': f"<t:{end}:t>"}
    template = data.get('message') or DEFAULT_MESSAGE
    try:
        message = template.format(**local)
        discord_message = template.format(**discord_stamps)
    except (IndexError, KeyError, ValueError):
        message = template
        discord_message = template
    return {
        'label': data.get('label') or DEFAULT_LABEL,
        'message': message,
        'discord_message': discord_message,
        'start': start,
        'end': end,
    }


def _fmt_left(seconds):
    hours, mins = divmod(max(int(seconds), 0) // 60, 60)
    return f"{hours}h {mins}m" if hours else f"{max(mins, 1)}m"


def countdown(now=None):
    """Human readable time left like '5h 57m' or '20m', None once the window closed."""
    item = announcement(now)
    if item is None:
        return None
    return _fmt_left(item['end'] - (time.time() if now is None else now))


def status_text(now=None):
    """Presence line for rotate_status, e.g. '/help • outage • back by 4h 10m'."""
    item = announcement(now)
    if item is None:
        return None
    now = time.time() if now is None else now
    when = 'back by' if item['start'] <= now else 'starts in'
    return f"/help • {item['label'].lower()} • {when} {_fmt_left(item['end'] - now)}"


def bio_text(item=None, now=None):
    """Ready to paste Discord bio: the outage line on top of the saved base bio."""
    item = item if item is not None else announcement(now)
    try:
        with open(BIO_FILE, encoding='utf-8') as f:
            base = f.read().strip()
    except OSError:
        base = ''
    if not item:
        return base
    label = item.get('label') or DEFAULT_LABEL
    discord_msg = item.get('discord_message') or item.get('message') or ''
    line = f"{label}: {discord_msg}"
    return f"{line}\n{base}".strip() if base else line


if __name__ == '__main__':
    print(bio_text())