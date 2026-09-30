"""Run the preflight agent once, headless, and keep the full transcript.

The agent is Claude Code in print mode with every built-in tool switched off,
so the only things it can do are read the Sanity knowledge base, query the
rule table in the Sanity dataset, and call the preflight tools. Usage:

    python -m agent.run "Does Meta remove the dots in a Gmail address?"
    python -m agent.run --csv examples/leads.csv --region US "Check these rows"
    python -m agent.run --audit

Each run is saved as JSON lines under runs/, one event per line, which is what
the evaluation grades and what the write-up quotes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from preflight.common import load_env, summarize

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
SYSTEM = (ROOT / "agent" / "system.md").read_text(encoding="utf-8")
TOOLS = ("mcp__sanity-context", "mcp__sanity-dataset", "mcp__preflight")
PREVIEW_ROWS = 3
AUDIT_PROMPT = (
    "Audit the implementation against the documentation, for both platforms."
)


def build_prompt(question: str, csv_path: Path | None, region: str | None) -> str:
    """The request, plus, for a file, its header and a few rows so the agent can map columns.

    The rest of the file never enters the prompt: the agent passes the path and
    the column mapping to preflight_file, which reads the file itself.
    """
    parts = [question.strip()]
    if region:
        parts.append(f"The ad accounts are in {region.upper()}; use it as default_region.")
    if csv_path is not None:
        resolved = csv_path.resolve()
        lines = resolved.read_text(encoding="utf-8-sig").splitlines()
        shown = "\n".join(lines[: PREVIEW_ROWS + 1])
        parts.append(
            f"File: {resolved.relative_to(ROOT)} ({max(len(lines) - 1, 0)} data rows). "
            f"Header and the first {PREVIEW_ROWS} rows, for mapping only:\n```csv\n{shown}\n```"
        )
    return "\n\n".join(parts)


def command(prompt: str, model: str, *, kb_only: bool = False) -> list[str]:
    """The claude invocation. kb_only drops the preflight server: the baseline
    the evaluation compares against, same prompt, knowledge base alone."""
    config = ROOT / "agent" / "mcp.kb-only.json" if kb_only else ROOT / ".mcp.json"
    tools = ("mcp__sanity-context",) if kb_only else TOOLS
    return [
        "claude", "-p", prompt,
        "--system-prompt", SYSTEM,
        "--tools", "",
        "--mcp-config", str(config),
        "--strict-mcp-config",
        "--allowedTools", *tools,
        "--disable-slash-commands",
        "--setting-sources", "project",
        "--no-session-persistence",
        "--model", model,
        "--output-format", "stream-json",
        "--verbose",
    ]


def describe_call(block: dict) -> str:
    name = block["name"].split("__")[-1]
    args = block.get("input", {})
    if name == "knowledge_base_read":
        return f"{name} {args.get('paths')}"
    if name == "groq_query":
        return f"{name} {' '.join(str(args.get('query', '')).split())[:90]}"
    if name == "knowledge_base_search":
        return f"{name} {args.get('query')!r}"
    if name == "normalize_and_hash":
        return f"{name} {args.get('platform')}/{args.get('field')} {args.get('value')!r}"
    if name == "preflight_batch":
        return f"{name} {len(args.get('records', []))} rows, region={args.get('default_region')}"
    if name == "preflight_file":
        return f"{name} {args.get('path')} ({len(args.get('columns', {}))} columns mapped, " \
               f"id={args.get('id_column')}, region={args.get('default_region')})"
    return name


def run(prompt: str, *, model: str, label: str, kb_only: bool = False,
        runs_dir: Path = RUNS, quiet: bool = False) -> dict:
    env = {**os.environ, **load_env(ROOT / ".env")}
    env.update(
        CLAUDE_CODE_DISABLE_CLAUDE_MDS="1",
        CLAUDE_CODE_DISABLE_AUTO_MEMORY="1",
        PREFLIGHT_PYTHON=sys.executable,
        PREFLIGHT_ROOT=str(ROOT),
    )
    env.pop("ANTHROPIC_API_KEY", None)  # never switch from the plan to metered billing
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "run"
    out_path = runs_dir / f"{stamp}-{slug}.jsonl"

    final: dict = {}
    events: list[dict] = []
    with out_path.open("w", encoding="utf-8") as sink:
        sink.write(json.dumps({"type": "prompt", "text": prompt, "model": model,
                               "kb_only": kb_only}) + "\n")
        # stderr goes to a file, not a pipe: reading stdout to the end while
        # stderr fills an unread pipe is how a subprocess deadlocks.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err:
            proc = subprocess.Popen(
                command(prompt, model, kb_only=kb_only), cwd=ROOT, env=env, text=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                sink.write(line)
                event = json.loads(line)
                events.append(event)
                if event.get("type") == "assistant":
                    for block in event["message"].get("content", []):
                        if block.get("type") == "tool_use" and not quiet:
                            print(f"  -> {describe_call(block)}", file=sys.stderr, flush=True)
                elif event.get("type") == "result":
                    final = event
            proc.wait()
            err.seek(0)
            stderr = err.read()
    if proc.returncode != 0 and not final:
        raise SystemExit(f"claude exited {proc.returncode}: {stderr.strip()[:500]}")
    final["transcript"] = str(out_path.relative_to(ROOT))
    final.update(summarize(events))
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question", nargs="?", default="")
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--region")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--kb-only", action="store_true",
                        help="baseline: knowledge base only, no preflight tools")
    args = parser.parse_args(argv)
    question = AUDIT_PROMPT if args.audit else args.question
    if not question:
        parser.error("ask a question, pass --csv with a request, or use --audit")
    prompt = build_prompt(question, args.csv, args.region)
    result = run(prompt, model=args.model, label="audit" if args.audit else question,
                 kb_only=args.kb_only)
    print(result.get("result", "").strip())
    usage = result.get("usage", {})
    print(
        f"\n[{result.get('num_turns')} turns, {result.get('duration_ms', 0) / 1000:.1f}s, "
        f"in {usage.get('input_tokens', 0)}+{usage.get('cache_read_input_tokens', 0)} cached, "
        f"out {usage.get('output_tokens', 0)} tokens; transcript {result['transcript']}"
        + "".join(f"; upload file {path}" for path in result.get("upload_files", []))
        + (f"; failed tool calls: {', '.join(result['tool_errors'])}" if result.get("tool_errors") else "")
        + "]",
        file=sys.stderr,
    )
    return 0 if result.get("subtype") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
