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
