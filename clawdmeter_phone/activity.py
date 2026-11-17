"""Turn the hook events log into what the phone shows: sessions, working, latest event, alert."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

WORKING_EVENTS = {"UserPromptSubmit", "PreToolUse", "PostToolUse"}
CLEARING_EVENTS = {"UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd"}
WORKING_FRESH = 10 * 60
SESSION_FRESH = 5 * 60  # same window as Clawdmeter
ALERT_MAX_AGE = 30 * 60


@dataclass
class Activity:
    sessions: dict = field(default_factory=dict)  # sid -> (ev, t)
    alerts: dict = field(default_factory=dict)  # sid -> {"id", "m", "t"}
    dismissed: set = field(default_factory=set)
    dirs: dict = field(default_factory=dict)  # sid -> project folder name
    es: int = 0
    e: str | None = None

    def ingest(self, line: dict):
        ev, sid, t = line.get("ev"), line.get("sid", "-"), float(line.get("t", 0))
        if sid == "-" or ev == "unknown":
            return  # the hook ran without event data; nothing to attribute it to
        if line.get("dir"):
            self.dirs[sid] = "scratch" if line["dir"].startswith("scratch-") else line["dir"]
        prev_ev = self.sessions.get(sid, ("", 0))[0]
        if ev == "SessionEnd":
            self.sessions.pop(sid, None)
        elif ev == "Notification" and prev_ev in WORKING_EVENTS and line.get("nt") != "idle_prompt":
            self.sessions[sid] = (prev_ev, t)  # a mid-turn prompt; the turn is still running
        else:
            self.sessions[sid] = (ev, t)
        is_alert = (ev == "Notification" or (ev == "PreToolUse" and line.get("tool") == "AskUserQuestion")
                    or line.get("ask"))
        waiting = self.alerts.get(sid, {})
        if ev == "Notification" and (waiting.get("question") or waiting.get("sticky")):
            pass  # keep the question itself; the notice about it says less
        elif is_alert:
            self.alerts[sid] = {"id": f"{sid}:{t}", "m": line.get("m") or "Claude needs you", "t": t,
                                "title": title_for(line), "opts": line.get("opts") or [],
                                "primary": bool(line.get("primary")), "dir": self.dirs.get(sid, ""),
                                "sticky": bool(line.get("ask")), "question": ev == "PreToolUse"}
        elif ev in CLEARING_EVENTS:
            a = self.alerts.get(sid)
            # A question is answered by its own tool finishing, not by a parallel subagent's.
            if a and a["question"] and ev == "PostToolUse" and line.get("tool") != "AskUserQuestion":
                pass
            # An end-of-turn question outlives the turn's own Stop; only your next prompt answers it.
            elif a and (not a["sticky"] or ev in ("UserPromptSubmit", "SessionEnd")):
                del self.alerts[sid]
        if ev == "UserPromptSubmit":
            self.e, self.es = "p", self.es + 1
        elif ev == "Stop":
            self.e, self.es = "s", self.es + 1

    def dismiss(self, alert_id: str | None):
        if alert_id:
            self.dismissed.add(alert_id)
        else:
            self.dismissed.update(a["id"] for a in self.alerts.values())

    def interrupt(self):
        """Esc was sent from the phone. An interrupt fires no Stop hook, so stop counting busy
        sessions as working; any that carry on say so with their next event."""
        for sid, (ev, t) in self.sessions.items():
            if ev in WORKING_EVENTS:
                self.sessions[sid] = ("Interrupted", t)

    def snapshot(self, now: float) -> dict:
        busy = {s for s, (ev, t) in self.sessions.items() if ev in WORKING_EVENTS and now - t < WORKING_FRESH}
        live = {s for s, (ev, t) in self.sessions.items() if now - t < SESSION_FRESH} | busy
        working = bool(busy)
        alerts = [a for a in self.alerts.values() if a["id"] not in self.dismissed and now - a["t"] < ALERT_MAX_AGE]
        alert = max(alerts, key=lambda a: a["t"]) if alerts else None
        return {"n": len(live), "working": working, "e": self.e, "es": self.es,
                "alert": {k: alert[k] for k in ("id", "m", "title", "opts", "primary", "dir", "question")} if alert else None}


def title_for(line: dict) -> str:
    if line.get("ev") == "PreToolUse" or line.get("ask"):
        return "Question for you"
    nt = line.get("nt") or ""
    if nt == "idle_prompt":
        return "Waiting for you"
    if "permission" in nt or "permission" in (line.get("m") or "").lower():
        return "Permission needed"
    return "Claude needs you"


class LogTail:
    """Follow events.log from where we left off, rotating it once it is large."""

    def __init__(self, path: Path, backlog_bytes: int = 64 * 1024, max_bytes: int = 256 * 1024):
        self.path = path
        self.pos = None
        self.backlog = backlog_bytes
        self.max_bytes = max_bytes

    def read(self) -> list[dict]:
        if not self.path.exists():
            self.pos = 0
            return []
        size = self.path.stat().st_size
        if self.pos is None:
            self.pos = max(0, size - self.backlog)
        elif size < self.pos:
            self.pos = 0  # truncated or replaced
        src = self.path
        if size > self.max_bytes:
            # Rotated here, not by the hook: only the reader knows what is unread, and it finishes
            # the old file below. The rename fails while a hook is writing; the next read retries.
            old = self.path.with_suffix(".log.1")
            try:
                os.replace(self.path, old)
                src = old
            except OSError:
                pass
        with open(src, "rb") as f:
            f.seek(self.pos)
            data = f.read()
        end = data.rfind(b"\n") + 1
        self.pos = self.pos + end if src is self.path else 0
        out = []
        for raw in data[:end].splitlines():
            try:
                out.append(json.loads(raw))
            except ValueError:  # bad JSON, or bytes that aren't UTF-8
                continue
        return out
