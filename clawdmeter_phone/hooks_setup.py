"""Add or remove this project's hooks in ~/.claude/settings.json.

uv run python -m clawdmeter_phone.hooks_setup show       # print the change, write nothing
uv run python -m clawdmeter_phone.hooks_setup install    # back up settings.json, then add hooks
uv run python -m clawdmeter_phone.hooks_setup uninstall  # remove only our hooks
"""

import copy
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = Path.home() / ".claude" / "settings.json"
MARKER = "iphone-clawdmeter"
EVENTS = [
    ("UserPromptSubmit", None),
    ("PostToolUse", None),
    ("Stop", None),
    ("SessionEnd", None),
    ("Notification", None),
    ("PreToolUse", "AskUserQuestion"),
]


def hook_command() -> str:
    py = (ROOT / ".venv" / "Scripts" / "pythonw.exe").as_posix()
    script = (ROOT / "clawdmeter_phone" / "hook.py").as_posix()
    # Unquoted runs the same in Git Bash, cmd and PowerShell (some Claude Code builds hook
    # through PowerShell, where a leading quoted path is just a string and nothing runs).
    # No quoted form runs in all three, so a path with a space can't be installed.
    if " " in py + script:
        sys.exit(f"can't write the hook command: {ROOT} has a space in its path; move the project folder")
    return f"{py} {script}"


def is_ours(hook: dict) -> bool:
    # The script path too, so hooks are still found if the project folder is renamed.
    cmd = str(hook.get("command", "")).replace("\\", "/")
    return MARKER in cmd or "clawdmeter_phone/hook.py" in cmd


def remove(settings: dict) -> dict:
    s = copy.deepcopy(settings)
    hooks = s.get("hooks", {})
    for ev in list(hooks):
        groups = []
        for g in hooks[ev]:
            kept = [h for h in g.get("hooks", []) if not is_ours(h)]
            if kept:
                groups.append({**g, "hooks": kept})
            elif not g.get("hooks"):
                groups.append(g)
        if groups:
            hooks[ev] = groups
        else:
            del hooks[ev]
    if "hooks" in s and not s["hooks"]:
        del s["hooks"]
    return s


def add(settings: dict, command: str) -> dict:
    s = remove(settings)
    hooks = s.setdefault("hooks", {})
    for ev, matcher in EVENTS:
        group = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
        if matcher:
            group = {"matcher": matcher, **group}
        hooks.setdefault(ev, []).append(group)
    return s


def load() -> dict:
    return json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}


def save(settings: dict):
    if SETTINGS.exists():
        backup = SETTINGS.with_name(f"settings.json.bak-{MARKER}-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(SETTINGS, backup)
        print(f"backup: {backup}")
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {SETTINGS}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    current = load()
    if cmd == "show":
        print(json.dumps(add(current, hook_command()).get("hooks"), indent=2))
    elif cmd == "install":
        save(add(current, hook_command()))
    elif cmd == "uninstall":
        new = remove(current)
        if new == current:
            print("no iphone-clawdmeter hooks found; nothing changed")
        else:
            save(new)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
