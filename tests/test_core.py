import json

from clawdmeter_phone.activity import Activity, LogTail
from clawdmeter_phone.hook import record
from clawdmeter_phone.hooks_setup import add, remove
from clawdmeter_phone.usage import parse

CMD = '"C:/x/iphone-clawdmeter/.venv/Scripts/pythonw.exe" "C:/x/iphone-clawdmeter/clawdmeter_phone/hook.py"'


def test_hooks_roundtrip_preserves_other_settings():
    original = {
        "statusLine": {"type": "command", "command": "node x.js"},
        "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "prettier"}]}]},
    }
    installed = add(original, CMD)
    assert len(installed["hooks"]["PostToolUse"]) == 2
    assert installed["hooks"]["PreToolUse"][0]["matcher"] == "AskUserQuestion"
    assert add(installed, CMD) == installed  # idempotent
    assert remove(installed) == original


def test_remove_drops_empty_hooks_key():
    assert remove(add({"a": 1}, CMD)) == {"a": 1}


def test_record_keeps_only_short_fields():
    line = record({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "secret"})
    assert "secret" not in str(line) and line["ev"] == "UserPromptSubmit"
    q = record({"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "Pick one?"}]}})
    assert q["m"] == "Pick one?"


def test_activity_alert_lifecycle():
    a = Activity()
    a.ingest({"t": 100, "ev": "UserPromptSubmit", "sid": "s1"})
    snap = a.snapshot(110)
    assert snap["working"] and snap["n"] == 1 and snap["e"] == "p" and snap["alert"] is None
    a.ingest({"t": 120, "ev": "Notification", "sid": "s1", "m": "Claude needs your permission to use Bash",
              "nt": "permission_prompt"})
    alert = a.snapshot(121)["alert"]
    assert alert["title"] == "Permission needed"
    a.ingest({"t": 130, "ev": "PostToolUse", "sid": "s1", "tool": "Bash"})
    assert a.snapshot(131)["alert"] is None
    a.ingest({"t": 140, "ev": "Notification", "sid": "s1", "m": "Waiting", "nt": "idle_prompt"})
    a.dismiss(a.snapshot(141)["alert"]["id"])
    assert a.snapshot(142)["alert"] is None
    a.ingest({"t": 150, "ev": "Stop", "sid": "s1"})
    snap = a.snapshot(151)
    assert not snap["working"] and snap["e"] == "s"
    assert a.snapshot(151 + 3600)["n"] == 0


def test_session_count_window():
    a = Activity()
    a.ingest({"t": 100, "ev": "Stop", "sid": "idle", "dir": "x"})
    a.ingest({"t": 100, "ev": "PostToolUse", "sid": "busy", "dir": "y", "tool": "Bash"})
    assert a.snapshot(200)["n"] == 2
    snap = a.snapshot(100 + 6 * 60)  # idle one drops after 5 min; a long tool call still counts
    assert snap["n"] == 1 and snap["working"]
    assert a.snapshot(100 + 11 * 60)["n"] == 0


def test_end_of_turn_question_alert():
    line = record({"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "mcp__ccd_turn__wrap_up",
                   "tool_input": {"recap": "r", "ask": "Commit this?",
                                  "actions": [{"action": "commit", "label": "Commit"}, {"label": "Not yet"}]}})
    assert line["ask"] and line["m"] == "Commit this?" and line["opts"] == ["Not yet"]
    assert line["primary"] is False  # the highlighted button was the app action, not a reply
    q = record({"hook_event_name": "PostToolUse", "session_id": "s9", "tool_name": "mcp__ccd_turn__wrap_up",
                "cwd": "C:\\x\\scratch-2026-11-16-efcd08",
                "tool_input": {"ask": "Search F:?", "actions": [{"label": "Skip it"}, {"label": "Yes, search F:"}]}})
    assert q["primary"] is True and q["opts"] == ["Skip it", "Yes, search F:"]
    b = Activity()
    b.ingest({**q, "t": 1})
    assert b.snapshot(2)["alert"]["dir"] == "scratch" and b.snapshot(2)["alert"]["primary"] is True
    assert "ask" not in record({"hook_event_name": "PostToolUse", "session_id": "s1",
                                "tool_name": "mcp__ccd_turn__wrap_up", "tool_input": {"recap": "r"}})
    a = Activity()
    a.ingest({**line, "t": 100})
    a.ingest({"t": 101, "ev": "Stop", "sid": "s1"})
    alert = a.snapshot(102)["alert"]
    assert alert["title"] == "Question for you" and alert["opts"] == ["Not yet"]
    a.ingest({"t": 110, "ev": "UserPromptSubmit", "sid": "s1"})
    assert a.snapshot(111)["alert"] is None


def test_hook_decodes_other_encodings():
    from clawdmeter_phone.hook import decode
    j = '{"hook_event_name": "Stop"}'
    for raw in (j.encode(), j.encode("utf-8-sig"), j.encode("utf-16"), j.encode("utf-16-le")):
        assert decode(raw) == j


def test_hook_records_folder_name_only():
    line = record({"hook_event_name": "Stop", "session_id": "s", "cwd": "C:\\Users\\x\\Documents\\code\\my-proj"})
    assert line["dir"] == "my-proj"


def test_usage_parse_expired_session_window():
    body = {"five_hour": {"utilization": 40.0, "resets_at": "2026-01-01T00:00:00Z"},
            "seven_day": {"utilization": 12.4, "resets_at": "2026-01-05T00:00:00Z"}}
    from datetime import datetime, timezone
    now = datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp()
    u = parse(body, now)
    assert u["s"] == 0 and u["sr_at"] is None and u["w"] == 12


def test_question_survives_its_permission_notice():
    a = Activity()
    a.ingest({"t": 100, "ev": "UserPromptSubmit", "sid": "s"})
    a.ingest({"t": 105, "ev": "PreToolUse", "sid": "s", "tool": "AskUserQuestion", "m": "Pick a name?"})
    a.ingest({"t": 110, "ev": "Notification", "sid": "s", "nt": "permission_prompt",
              "m": "Claude needs your permission to use AskUserQuestion"})
    alert = a.snapshot(111)["alert"]
    assert alert["m"] == "Pick a name?" and alert["title"] == "Question for you"
    a.ingest({"t": 120, "ev": "PostToolUse", "sid": "s", "tool": "AskUserQuestion"})
    assert a.snapshot(121)["alert"] is None


def test_permission_prompt_keeps_session_working():
    a = Activity()
    a.ingest({"t": 100, "ev": "UserPromptSubmit", "sid": "s"})
    a.ingest({"t": 110, "ev": "Notification", "sid": "s", "nt": "permission_prompt", "m": "permission to use Bash"})
    assert a.snapshot(111)["working"]
    a.ingest({"t": 200, "ev": "Notification", "sid": "s", "nt": "idle_prompt", "m": "Waiting"})
    assert not a.snapshot(201)["working"]


def test_interrupt_from_phone_stops_working():
    a = Activity()
    a.ingest({"t": 100, "ev": "UserPromptSubmit", "sid": "s"})
    a.interrupt()
    snap = a.snapshot(101)
    assert not snap["working"] and snap["n"] == 1
    a.ingest({"t": 102, "ev": "PostToolUse", "sid": "s", "tool": "Bash"})  # it carried on after all
    assert a.snapshot(103)["working"]


def test_hooks_found_after_folder_rename():
    renamed = "C:/x/new-name/.venv/Scripts/pythonw.exe C:/x/new-name/clawdmeter_phone/hook.py"
    installed = add({"a": 1}, renamed)
    assert add(installed, renamed) == installed
    assert remove(installed) == {"a": 1}


def test_odd_usage_response_does_not_raise(monkeypatch):
    import io
    from clawdmeter_phone import usage
    monkeypatch.setattr(usage, "read_token", lambda: ("t", None))
    monkeypatch.setattr(usage.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"[1]"))
    assert usage.UsagePoller().poll(1000.0) == {"ok": False, "err": "Unexpected usage response"}


def test_end_of_turn_question_survives_idle_notice():
    q = record({"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "mcp__ccd_turn__wrap_up",
                "tool_input": {"ask": "Commit this?", "actions": [{"label": "Yes"}, {"label": "Not yet"}]}})
    a = Activity()
    a.ingest({**q, "t": 100})
    a.ingest({"t": 101, "ev": "Stop", "sid": "s"})
    a.ingest({"t": 161, "ev": "Notification", "sid": "s", "nt": "idle_prompt", "m": "Claude is waiting for your input"})
    alert = a.snapshot(162)["alert"]
    assert alert["m"] == "Commit this?" and alert["opts"] == ["Yes", "Not yet"]
    a.ingest({"t": 170, "ev": "Stop", "sid": "s"})  # still only your next prompt answers it
    assert a.snapshot(171)["alert"] is not None


def test_question_outlasts_other_tools_finishing():
    a = Activity()
    a.ingest({"t": 100, "ev": "PreToolUse", "sid": "s", "tool": "AskUserQuestion", "m": "Pick a name?"})
    a.ingest({"t": 105, "ev": "PostToolUse", "sid": "s", "tool": "Read"})  # a background subagent's tool
    alert = a.snapshot(106)["alert"]
    assert alert["m"] == "Pick a name?" and alert["question"]
    a.ingest({"t": 110, "ev": "PostToolUse", "sid": "s", "tool": "AskUserQuestion"})
    assert a.snapshot(111)["alert"] is None


def test_tail_rotates_without_losing_unread_lines(tmp_path):
    log = tmp_path / "events.log"
    tail = LogTail(log, max_bytes=100)
    log.write_text('{"n": 1}\n')
    assert tail.read() == [{"n": 1}]
    with open(log, "a") as f:  # written after the last read, and it takes the file over the limit
        f.write(json.dumps({"n": 2, "pad": "x" * 100}) + "\n")
    assert [e["n"] for e in tail.read()] == [2]
    assert not log.exists() and (tmp_path / "events.log.1").exists()
    log.write_text('{"n": 3}\n')
    assert tail.read() == [{"n": 3}]


def test_tail_skips_lines_it_cannot_decode(tmp_path):
    log = tmp_path / "events.log"
    log.write_bytes(b'\x80 not utf-8\n{"n": 1}\n')
    assert LogTail(log).read() == [{"n": 1}]
