import concurrent.futures
import json
import logging
import os
import threading
import time
import urllib.request

MAX_ALERTS_PER_MINUTE = 10
DEDUP_WINDOW = 60
MAX_TEXT_LEN = 1024
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

NOISE_LOGGERS = ("aiohttp", "urllib3", "notify", "discord.http")

_log = logging.getLogger("notify")


class DiscordAlertHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="alert"
        )
        self._lock = threading.Lock()
        self._last_seen = {}
        self._window = []

    def _webhook_url(self):
        return os.getenv("ERROR_WEBHOOK_URL") or os.getenv("ADMIN_WEBHOOK_URL") or ""

    def _allowed(self, record):
        name = record.name
        if any(name == noise or name.startswith(noise + ".") for noise in NOISE_LOGGERS):
            return False
        if record.levelno < logging.ERROR:
            return False
        return True

    def _rate_ok(self, record):
        now = time.monotonic()
        with self._lock:
            self._window = [ts for ts in self._window if now - ts < 60]
            if len(self._window) >= MAX_ALERTS_PER_MINUTE:
                return False
            key = (record.name, record.getMessage())
            last = self._last_seen.get(key)
            if last is not None and now - last < DEDUP_WINDOW:
                return False
            if len(self._last_seen) > 512:
                cutoff = now - 300
                self._last_seen = {k: ts for k, ts in self._last_seen.items() if ts >= cutoff}
            self._last_seen[key] = now
            self._window.append(now)
        return True

    def emit(self, record):
        try:
            if not self._allowed(record):
                return
            if not self._rate_ok(record):
                return
            url = self._webhook_url()
            if not url:
                return
            payload = self._build_payload(record)
            self._executor.submit(self._post, url, payload)
        except Exception:
            self.handleError(record)

    def _build_payload(self, record):
        text = self.format(record)[:MAX_TEXT_LEN]
        payload = {
            "embeds": [
                {
                    "title": f"⚠️ {record.levelname} · {record.name}",
                    "description": f"```{text}```",
                    "color": 0xE74C3C,
                    "footer": {"text": time.strftime(TIME_FORMAT)},
                }
            ]
        }
        if record.levelno >= logging.CRITICAL:
            owner = os.getenv("ALLOWED_USER_ID")
            if owner:
                payload["content"] = f"<@{owner}>"
        return payload

    def _post(self, url, payload):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "DiscordBot (https://github.com/xangey/VoidWave, 1.0) Python/3.11",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as e:
            _log.debug("Failed to send alert webhook: %s", e)