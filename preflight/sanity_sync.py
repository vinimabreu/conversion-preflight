"""Publish the implementation's rule table to a Sanity dataset as structured documents.

The code stays the source of truth: :mod:`preflight.rules` is what the tests
pin. This module writes the same table into Sanity, one ``normalizationRule``
document per (platform, field) and one ``implementationProfile`` document
that references them, so an agent can query the declared behaviour through a
Sanity Context endpoint and join it, by platform, field and knowledge base
entry, with what the platforms document.

    python -m preflight.sanity_sync            # dry run: print the mutations
    python -m preflight.sanity_sync --apply    # write them (needs SANITY_PROJECT_TOKEN)
    python -m preflight.sanity_sync --check    # compare the dataset with the code

Document ids are deterministic (``normalizationRule-google-email``) and use
hyphens, not dots: Sanity treats a dotted id as a path, which keeps it out of
public reads. The write is createOrReplace, plus a delete for any document of
these two types that the code no longer has, so running it twice leaves the
dataset unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from .common import load_env
from .rules import GLOBAL_DIVERGENCES, RULES, Rule

ROOT = Path(__file__).resolve().parent.parent
API_VERSION = "v2025-02-19"
PROFILE_ID = "implementationProfile-preflight"
UPSTREAM = "github.com/vinimabreu/revenue-loop, src/revenue_loop/identity.py at 265d1c9"


def _key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]


def rule_id(rule: Rule) -> str:
    return f"normalizationRule-{rule.platform}-{rule.field}"


def _source(text: str) -> dict[str, str]:
    url, _, note = text.partition(" (")
    return {"url": url, "note": note.rstrip(")")}


def rule_document(rule: Rule) -> dict[str, object]:
    return {
        "_id": rule_id(rule),
        "_type": "normalizationRule",
        "platform": rule.platform,
        "field": rule.field,
        "param": rule.param,
        "hashed": rule.hashed,
        "implemented": rule.implemented,
        "implementation": rule.implementation,
        "docQuote": rule.doc_quote,
        "source": _source(rule.source),
        "kbEntry": rule.kb_entry,
        "docExamples": [
            {
                "_key": _key(rule_id(rule), ex.input),
                "_type": "docExample",
                "input": ex.input,
                "normalized": ex.normalized,
                **({"sha256": ex.sha256} if ex.sha256 else {}),
                **({"region": ex.region} if ex.region else {}),
                "diverges": ex.diverges,
            }
            for ex in rule.doc_examples
        ],
        "divergences": list(rule.divergences),
    }


def profile_document() -> dict[str, object]:
    return {
        "_id": PROFILE_ID,
        "_type": "implementationProfile",
        "name": "conversion-preflight normaliser",
        "upstream": UPSTREAM,
        "globalDivergences": list(GLOBAL_DIVERGENCES),
        "rules": [
            {"_key": _key(rule_id(r)), "_type": "reference", "_ref": rule_id(r)} for r in RULES
        ],
    }


def documents() -> list[dict[str, object]]:
    return [*(rule_document(r) for r in RULES), profile_document()]


def mutations() -> dict[str, list[dict[str, object]]]:
    return {"mutations": [{"createOrReplace": doc} for doc in documents()]}


def _env() -> dict[str, str]:
    return load_env(ROOT / ".env")


def _request(url: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data else "GET",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _strip_system(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if not k.startswith("_") or k in {"_id", "_type", "_key", "_ref"}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if not (args.apply or args.check):
        json.dump(mutations(), sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0

    env = _env()
    project, dataset = env.get("SANITY_PROJECT_ID"), env.get("SANITY_DATASET", "production")
    token = env.get("SANITY_PROJECT_TOKEN")
    if not (project and token):
        print("SANITY_PROJECT_ID and SANITY_PROJECT_TOKEN must be set in .env", file=sys.stderr)
        return 2
    base = f"https://{project}.api.sanity.io/{API_VERSION}/data"

    query = urllib.parse.quote('*[_type in ["normalizationRule", "implementationProfile"]]')
    stored = {d["_id"]: _strip_system(d)
              for d in _request(f"{base}/query/{dataset}?query={query}", token)["result"]}
    stale = sorted(set(stored) - {d["_id"] for d in documents()})

    if args.apply:
        body = mutations()
        body["mutations"] += [{"delete": {"id": doc_id}} for doc_id in stale]
        result = _request(f"{base}/mutate/{dataset}?returnIds=true&visibility=sync", token, body)
        if stale:
            print(f"deleted {len(stale)} stale document(s): {', '.join(stale)}")
        print(f"wrote {len(documents())} documents, transaction {result.get('transactionId')}")
        return 0

    drift = 0
    for doc in documents():
        if stored.get(doc["_id"]) != doc:
            drift += 1
            print(f"differs: {doc['_id']}")
    for extra in stale:
        drift += 1
        print(f"not in code: {extra}")
    print("dataset matches the code" if not drift else f"{drift} document(s) differ")
    return 0 if not drift else 1


if __name__ == "__main__":
    raise SystemExit(main())
