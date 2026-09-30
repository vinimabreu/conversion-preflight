"""Run every case through the agent and grade the answers by code.

    python -m eval.run_eval                 # agent with the knowledge base and the tools
    python -m eval.run_eval --kb-only       # baseline: knowledge base alone
    python -m eval.run_eval --only V1 K4    # a subset, by id prefix
    python -m eval.run_eval --regrade runs/eval-<stamp>-<mode>   # grade saved transcripts again

Writes eval/results/<stamp>[-kb-only].json and prints one line per case.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from agent.run import run
from eval.cases import CASES, GRADER_VERSION, Case
from preflight.common import HEX64, summarize

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"


def grade(case: Case, answer: str, tools_called: list[str], *, kb_only: bool,
          tool_digests: frozenset[str] = frozenset()) -> dict:
    """Pass or fail, with every reason.

    The digest rule is about provenance: every 64-character hex string in the
    answer must be an expected value or must appear in a tool result from the
    same run. Anything else was written by the model, and a digest written by
    the model is the failure this project exists to prevent.
    """
    failures: list[str] = []
    found = set(HEX64.findall(answer.lower()))
    expected = set(case.expect_hashes)
    allowed = expected | set(case.extra.get("allow_hashes", ())) | set(tool_digests)
    for digest in sorted(expected - found):
        failures.append(f"missing digest {digest[:12]}...")
    for digest in sorted(found - allowed):
        failures.append(f"invented digest {digest[:12]}...")
    if case.kind == "refusal":
        for digest in sorted(found - set(case.extra.get("allow_hashes", ()))):
            failures.append(f"digest in a refusal {digest[:12]}...")
    for pattern in case.must:
        if not re.search(pattern, answer, flags=re.IGNORECASE):
            failures.append(f"missing /{pattern}/")
    for pattern in case.must_not:
        if re.search(pattern, answer, flags=re.IGNORECASE):
            failures.append(f"forbidden /{pattern}/")
    for path in case.cite:
        if f"[{path}]" not in answer:
            failures.append(f"no citation [{path}]")
    for alternatives in case.tools:
        options = alternatives.split("|")
        if kb_only and not {"knowledge_base_read", "knowledge_base_search"} & set(options):
            continue  # the baseline has no preflight tools to call
        if not set(options) & set(tools_called):
            failures.append(f"did not call {alternatives}")
    return {"pass": not failures, "failures": failures}


def replay(transcript: Path) -> dict:
    """What run() returns, rebuilt from a saved transcript, without calling the model."""
    events = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines()]
    final = next((e for e in events if e.get("type") == "result"), {})
    final["transcript"] = str(transcript.relative_to(ROOT))
    final.update(summarize(events))
    final["kb_only"] = bool(events and events[0].get("kb_only"))
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kb-only", action="store_true")
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--regrade", type=Path, help="grade the transcripts in this runs/ directory")
    args = parser.parse_args(argv)

    wanted = [p.lower() for p in args.only]
    cases = [c for c in CASES if not wanted or any(c.id.lower().startswith(p) for p in wanted)]
    if not cases:
        parser.error(f"no case id starts with {args.only}")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    mode = "kb-only" if args.kb_only else "kb+tools"
    runs_dir = ROOT / "runs" / f"eval-{stamp}-{mode}"
    rows = []
    saved: dict[str, Path] = {}
    if args.regrade:
        runs_dir = args.regrade.resolve()
        mode = "kb-only" if runs_dir.name.endswith("kb-only") else "kb+tools"
        args.kb_only = mode == "kb-only"
        # Runs live in runs/eval-<stamp>-<mode>/, published transcripts in
        # eval/transcripts/<mode>/; the regrade gets a stamp of its own.
        for path in sorted(runs_dir.glob("*.jsonl")):
            saved[path.stem.split("-", 2)[2]] = path
    for case in cases:
        if args.regrade:
            path = saved.get(case.id.lower())
            if path is None:
                print(f"SKIP  {case.id:<24} no transcript")
                continue
            result = replay(path)
        else:
            result = run(case.prompt, model=args.model, label=case.id, kb_only=args.kb_only,
                         runs_dir=runs_dir, quiet=True)
        answer = result.get("result", "") or ""
        verdict = grade(case, answer, result.get("tools_called", []), kb_only=args.kb_only,
                        tool_digests=frozenset(result.get("tool_digests", [])))
        rows.append({
            "id": case.id, "kind": case.kind, **verdict,
            "tools_called": result.get("tools_called", []),
            "tool_errors": result.get("tool_errors", []),
            "seconds": round(result.get("duration_ms", 0) / 1000, 1),
            "turns": result.get("num_turns"),
            "transcript": result.get("transcript"),
        })
        mark = "PASS" if verdict["pass"] else "FAIL"
        print(f"{mark}  {case.id:<24} {rows[-1]['seconds']:>5}s  {'; '.join(verdict['failures'])}",
              flush=True)

    passed = sum(r["pass"] for r in rows)
    summary = {"mode": mode, "model": args.model, "stamp": stamp, "grader": GRADER_VERSION,
               "regraded": bool(args.regrade), "passed": passed, "total": len(rows), "cases": rows}
    RESULTS.mkdir(parents=True, exist_ok=True)
    suffix = "-regraded" if args.regrade else ""
    subset = "-subset" if args.only else ""
    out = RESULTS / f"{stamp}-{mode}{subset}{suffix}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n{mode}: {passed}/{len(rows)} passed -> {out.relative_to(ROOT)}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
