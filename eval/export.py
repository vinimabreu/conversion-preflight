"""Export saved runs into transcripts that are safe to publish.

    python -m eval.export runs/eval-<stamp>-kb+tools eval/transcripts/kb+tools
    python -m eval.export runs/<stamp>-audit.jsonl eval/transcripts/audit

A raw stream-json transcript starts with an init event that carries the local
working directory, a socket path, a session id and the names of every agent
and plugin configured on the machine that ran it. None of that is part of the
agent's behaviour, so the export keeps only what is: the prompt, each text
message and tool call, each tool result, and the final answer with its turn
count and token usage. Absolute paths under the project directory are rewritten as
relative ones, and the result is checked for anything that still looks local.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP_RESULT = ("subtype", "is_error", "num_turns", "duration_ms", "result", "usage")
KEEP_BLOCKS = {"text", "tool_use", "tool_result"}
"""Thinking blocks are left out: in these runs they carry no text, only an opaque signature."""
LOCAL = re.compile(r"/Users/|/home/|/private/|/tmp/|\.sock\b")


def _clean(value: object) -> object:
    if isinstance(value, str):
        return value.replace(str(ROOT) + "/", "").replace(str(ROOT), ".")
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


def clean_events(events: list[dict]) -> list[dict]:
    out: list[dict] = []
    for event in events:
        kind = event.get("type")
        if kind == "prompt":
            out.append({"type": "prompt", "text": event.get("text"), "model": event.get("model"),
                        "kb_only": event.get("kb_only", False)})
        elif kind in {"assistant", "user"}:
            message = event.get("message", {})
            blocks = [b for b in message.get("content", [])
                      if isinstance(b, dict) and b.get("type") in KEEP_BLOCKS]
            if blocks:
                out.append({"type": kind, "content": blocks})
        elif kind == "result":
            out.append({"type": "result", **{k: event[k] for k in KEEP_RESULT if k in event}})
    cleaned = _clean(out)
    leftover = LOCAL.search(json.dumps(cleaned))
    if leftover:
        raise ValueError(f"a local path survived the export near {leftover.group(0)!r}")
    return cleaned  # type: ignore[return-value]


def export(source: Path, target_dir: Path) -> list[Path]:
    files = sorted(source.glob("*.jsonl")) if source.is_dir() else [source]
    target_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for path in files:
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        target = target_dir / path.name
        target.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n"
                                  for e in clean_events(events)), encoding="utf-8")
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="a runs/ directory or one .jsonl file")
    parser.add_argument("target", type=Path)
    args = parser.parse_args(argv)
    for path in export(args.source, args.target):
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
