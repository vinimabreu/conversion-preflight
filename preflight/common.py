"""Small helpers shared by the runner, the evaluation, the sync command and the probe."""

from __future__ import annotations

import json
import re
from pathlib import Path

HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
"""A SHA-256 hex digest as it appears in text (matched on lowercased text)."""


def load_env(path: Path) -> dict[str, str]:
    """KEY=value lines; comments and blank lines skipped, one pair of surrounding quotes removed."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def tool_calls(events: list[dict]) -> list[dict]:
    """Every tool call in a stream-json transcript, paired with its result.

    Each item has the tool's short name, its input, whether the result was an
    error, the result text, and the result parsed as JSON when it is JSON. A
    call whose result is an error counts as a call that did not happen, for
    grading and for anything read out of its output.
    """
    calls: dict[str, dict] = {}
    order: list[str] = []
    for event in events:
        # Raw stream-json nests content under "message"; exported transcripts do not.
        content = event.get("message", {}).get("content") or event.get("content") or []
        if event.get("type") == "assistant":
            for block in content:
                if block.get("type") == "tool_use":
                    calls[block["id"]] = {"name": block["name"].split("__")[-1],
                                          "input": block.get("input", {}), "is_error": None,
                                          "text": "", "json": None}
                    order.append(block["id"])
        elif event.get("type") == "user":
            for block in content:
                if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                    continue
                call = calls.get(block.get("tool_use_id"))
                if call is None:
                    continue
                raw = block.get("content")
                text = raw if isinstance(raw, str) else "".join(
                    part.get("text", "") for part in raw or [] if isinstance(part, dict))
                call["text"], call["is_error"] = text, bool(block.get("is_error"))
                try:
                    call["json"] = json.loads(text)
                except ValueError:
                    call["json"] = None
    return [calls[i] for i in order]


def summarize(events: list[dict]) -> dict[str, list]:
    """What the grader and the runner need from a transcript."""
    calls = tool_calls(events)
    ok = [c for c in calls if c["is_error"] is False]
    return {
        "tools_called": [c["name"] for c in ok],
        "tool_errors": [c["name"] for c in calls if c["is_error"]],
        "tool_digests": sorted({d for c in ok for d in HEX64.findall(c["text"].lower())}),
        "upload_files": [c["json"]["upload_file"] for c in ok
                         if c["name"] == "preflight_file" and isinstance(c["json"], dict)
                         and "upload_file" in c["json"]],
    }
