from __future__ import annotations

import json

import pytest

from eval.export import ROOT, clean_events

RAW = [
    {"type": "prompt", "text": "Check these rows.", "model": "sonnet", "kb_only": False},
    {"type": "system", "subtype": "init", "cwd": str(ROOT), "session_id": "abc",
     "agents": ["some-private-agent"], "messaging_socket_path": "/tmp/cc-socks/1.sock"},
    {"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": "", "signature": "c2lnbmF0dXJl" * 50},
        {"type": "tool_use", "id": "t1", "name": "mcp__preflight__preflight_file",
         "input": {"path": "examples/leads.csv"}}]}, "session_id": "abc", "uuid": "u1"},
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1",
         "content": [{"type": "text", "text": json.dumps({"upload_file": f"{ROOT}/runs/uploads/x.json"})}]}]}},
    {"type": "result", "subtype": "success", "result": "done", "num_turns": 3, "duration_ms": 10,
     "usage": {"output_tokens": 5}, "session_id": "abc", "total_cost_usd": 0.1},
]


def test_export_drops_the_init_event_and_session_details():
    cleaned = clean_events(RAW)
    text = json.dumps(cleaned)
    assert [e["type"] for e in cleaned] == ["prompt", "assistant", "user", "result"]
    for secretish in ("session_id", "some-private-agent", "sock", "uuid", "total_cost_usd", str(ROOT)):
        assert secretish not in text
    assert "runs/uploads/x.json" in text
    assert "thinking" not in text and "signature" not in text


def test_export_refuses_when_a_local_path_survives():
    raw = RAW[:1] + [{"type": "result", "result": "see /Users/someone/file"}]
    with pytest.raises(ValueError, match="local path"):
        clean_events(raw)


def test_claude_session_is_reduced_to_the_conversation():
    from eval.export import clean_claude_session
    rows = [
        {"type": "attachment", "uuid": "a1", "parentUuid": None,
         "attachment": {"type": "session_context", "context": {"userEmail": "someone@realmail.net"}}},
        {"type": "user", "uuid": "u1", "parentUuid": "a1", "cwd": str(ROOT),
         "message": {"role": "user", "content": "Audit it."}},
        {"type": "assistant", "uuid": "t1", "parentUuid": "u1",
         "message": {"content": [{"type": "thinking", "thinking": "", "signature": "x" * 40}]}},
        {"type": "assistant", "uuid": "r1", "parentUuid": "t1", "cwd": str(ROOT),
         "message": {"content": [{"type": "text", "text": f"see {ROOT}/README.md"}]}},
        {"type": "cost-state", "totalCostUSD": 0.1},
    ]
    cleaned = clean_claude_session(rows)
    assert [r["uuid"] for r in cleaned] == ["u1", "r1"]
    assert cleaned[0]["parentUuid"] is None and cleaned[1]["parentUuid"] == "u1"
    text = json.dumps(cleaned)
    assert "realmail" not in text and "signature" not in text and str(ROOT) not in text
    assert "/workspace/conversion-preflight/README.md" in text


def test_claude_session_export_refuses_a_surviving_email():
    from eval.export import clean_claude_session
    rows = [{"type": "user", "uuid": "u1", "parentUuid": None,
             "message": {"content": "mail me at someone@realmail.net"}}]
    with pytest.raises(ValueError, match="email"):
        clean_claude_session(rows)


def test_documented_example_addresses_are_not_mistaken_for_leaks():
    from eval.export import clean_claude_session
    rows = [{"type": "user", "uuid": "u1", "parentUuid": None,
             "message": {"content": "user.name+NYC@Example.com and John_Smith@gmail.com"}}]
    assert clean_claude_session(rows)
