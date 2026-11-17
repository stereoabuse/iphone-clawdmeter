"""Session and weekly usage from Claude Code's own OAuth usage endpoint (undocumented; same one Clawdmeter uses)."""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CREDENTIALS = Path.home() / ".claude" / ".credentials.json"
USER_AGENT = "iphone-clawdmeter/0.1"


def read_token() -> tuple[str | None, float | None]:
    try:
        oauth = json.loads(CREDENTIALS.read_text(encoding="utf-8"))["claudeAiOauth"]
        exp = oauth.get("expiresAt")
        return oauth.get("accessToken") or None, (exp / 1000 if exp else None)
    except (OSError, KeyError, ValueError, TypeError):
        return None, None


def _epoch(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse(body: dict, now: float) -> dict:
    five = body.get("five_hour") or {}
    week = body.get("seven_day") or {}
    sr_at = _epoch(five.get("resets_at"))
    if sr_at is not None and sr_at <= now:
        sr_at = None
    s = five.get("utilization")
    return {
        "ok": True,
        "s": round(s) if s is not None and sr_at else 0,
        "sr_at": sr_at,
        "w": round(week["utilization"]) if week.get("utilization") is not None else None,
        "wr_at": _epoch(week.get("resets_at")),
    }


class UsagePoller:
    def __init__(self, interval: float = 180):
        self.interval = interval
        self.next_at = 0.0
        self.last: dict = {"ok": False, "err": "No usage data yet…"}

    def due(self, now: float) -> bool:
        return now >= self.next_at

    def poll(self, now: float | None = None) -> dict:
        now = now or time.time()
        self.next_at = now + self.interval
        token, exp = read_token()
        if not token:
            return self._fail("Not signed in to Claude Code")
        if exp and exp <= now + 60:
            return self._fail("Login expired; run claude to refresh")
        req = urllib.request.Request(USAGE_URL, headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                self.last = parse(json.loads(r.read()), now)
                return self.last
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    self.next_at = now + max(60, int(e.headers.get("retry-after", "300")))
                except ValueError:
                    self.next_at = now + 300
                return self._fail("Rate limited; retrying later", keep=True)
            if e.code in (401, 403):
                return self._fail("Login refused; run claude to refresh")
            return self._fail(f"Usage endpoint HTTP {e.code}", keep=True)
        except (urllib.error.URLError, TimeoutError, OSError):
            self.next_at = now + 60
            return self._fail("Offline", keep=True)
        except (ValueError, KeyError, TypeError, AttributeError):
            return self._fail("Unexpected usage response", keep=True)

    def _fail(self, msg: str, keep: bool = False) -> dict:
        if keep and self.last.get("ok"):
            self.last = {**self.last, "stale": True}
        else:
            self.last = {"ok": False, "err": msg}
        return self.last
