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
discord.py or flask. Run `python outage.py` to print the ready to paste bio,
`python outage.py set --label "..." --hours 2` to announce one, and
`python outage.py clear` to end it early.
"""

import argparse
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


def write(data):
    """Persist outage.json. A trailing newline keeps the file diff friendly."""
    with open(OUTAGE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    _cache['key'] = None
    _cache['data'] = None


def cmd_show():
    """Print the active announcement and how long is left."""
    item = announcement()
    if item is None:
        print('No active outage announcement.')
        return
    print(f'{item["label"]}: {item["message"]}')
    print(f'  {OUTAGE_FILE}: start {item["start"]}, end {item["end"]} ({countdown()} left)')


def cmd_set(args):
    """Create or update the announcement, keeping any field not passed in."""
    data = load() or {}
    now = int(time.time())
    window = (args.hours or 0) * 3600 + (args.minutes or 0) * 60
    if window <= 0:
        end = int(data.get('end') or 0)
        window = end - now if end > now else 2 * 3600
    for key in ('label', 'message', 'tz'):
        value = getattr(args, key)
        if value is not None:
            data[key] = value
    data['start'] = now
    data['end'] = now + int(window)
    write(data)
    item = announcement() or {}
    print(f'Announcement set, {countdown()} from now:')
    print(f'  {item.get("label")}: {item.get("message")}')
    print('\nPaste the bio:')
    print(bio_text())


def cmd_clear():
    """End the announcement now by deleting outage.json."""
    try:
        os.remove(OUTAGE_FILE)
    except FileNotFoundError:
        print('No outage.json to clear.')
        return
    _cache['key'] = None
    _cache['data'] = None
    print('Cleared. The banner and presence are gone on the next read.')
    print('\nRestore the bio to bot_bio.txt on its own:')
    print(bio_text())


def main(argv=None):
    parser = argparse.ArgumentParser(prog='outage.py', description='Outage announcement helper.')
    sub = parser.add_subparsers(dest='cmd')
    sub.add_parser('bio', help='print the ready to paste Discord bio (default)')
    sub.add_parser('show', help='print the active announcement and time left')
    setter = sub.add_parser('set', help='create or update the announcement')
    setter.add_argument('--label', default=None, help=f'default: {DEFAULT_LABEL}')
    setter.add_argument('--hours', type=float, default=None, help='window length from now')
    setter.add_argument('--minutes', type=float, default=None, help='extra minutes on the window')
    setter.add_argument('--message', default=None, help='supports {start} and {end}')
    setter.add_argument('--tz', default=None, help=f'default: {DEFAULT_TZ}')
    sub.add_parser('clear', help='end the announcement now')
    args = parser.parse_args(argv)

    cmd = args.cmd or 'bio'
    if cmd == 'show':
        cmd_show()
    elif cmd == 'set':
        cmd_set(args)
    elif cmd == 'clear':
        cmd_clear()
    else:
        print(bio_text())


if __name__ == '__main__':
    main()