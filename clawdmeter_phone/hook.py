"""Claude Code hook: append one line per event to the events log. Stdlib only, silent, always exits 0.

Records the event name, session id, and (for Notification / AskUserQuestion) the short message
Claude Code shows. Nothing from prompts or tool inputs is stored otherwise.
"""

import json
import sys
import time
from pathlib import Path

# Inside the project, not AppData: the Claude desktop app is a Store (MSIX) app, and Windows silently
# redirects AppData writes from it (and everything it launches) to a private copy that terminal
# sessions can't see. Paths outside AppData aren't redirected.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOG = DATA_DIR / "events.log"


def record(payload: dict) -> dict:
    ev = payload.get("hook_event_name") or "unknown"
    line = {"t": round(time.time(), 3), "ev": ev, "sid": str(payload.get("session_id") or "-")[:64]}
    if payload.get("cwd"):
        line["dir"] = Path(str(payload["cwd"])).name[:40]
    if ev == "Notification":
        line["m"] = str(payload.get("message") or "")[:200]
        if payload.get("notification_type"):
            line["nt"] = str(payload["notification_type"])[:40]
    elif ev in ("PreToolUse", "PostToolUse"):
        line["tool"] = str(payload.get("tool_name") or "")[:60]
        if payload.get("tool_name") == "AskUserQuestion" and ev == "PreToolUse":
            try:
                line["m"] = str(payload["tool_input"]["questions"][0]["question"])[:200]
            except (KeyError, IndexError, TypeError):
                line["m"] = "Claude has a question"
        elif ev == "PostToolUse" and str(payload.get("tool_name", "")).endswith("__wrap_up"):
            # The desktop app's end-of-turn question box: keep the question and its reply buttons
            # (app-action buttons like "commit" can't be answered by typing, so they're left out).
            ti = payload.get("tool_input") or {}
            if isinstance(ti, dict) and ti.get("ask"):
                line["ask"] = True
                line["m"] = str(ti["ask"])[:200]
                acts = ti.get("actions") or []
                if isinstance(acts, str):
                    try:
                        acts = json.loads(acts)
                    except ValueError:
                        acts = []
                line["opts"] = [str(a["label"])[:30] for a in acts
                                if isinstance(a, dict) and a.get("label") and not a.get("action")][:3]
                # The app highlights actions[0] and answers it with Ctrl+Enter.
                first = acts[0] if acts and isinstance(acts[0], dict) else {}
                line["primary"] = bool(line["opts"]) and not first.get("action")
    return line


def decode(raw: bytes) -> str:
    # Some shells hand the hook UTF-16 or UTF-8 with a BOM.
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(raw) > 1 and raw[1:2] == b"\x00"):
        return raw.decode("utf-16", "replace")
    return raw.decode("utf-8-sig", "replace")


def main():
    raw = b""
    try:
        raw = sys.stdin.buffer.read() if sys.stdin else b""
        payload = json.loads(decode(raw) or "{}")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:  # the daemon rotates it (LogTail)
            f.write(json.dumps(record(payload)) + "\n")
    except Exception as e:
        try:  # never disturb Claude, but leave a trace for debugging
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(DATA_DIR / "hook-errors.log", "a", encoding="utf-8") as f:
                f.write(f"{time.time():.0f} {type(e).__name__}: {e} | stdin={len(raw)}B {raw[:80]!r}\n")
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
