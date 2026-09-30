"""Normalise and hash one value for one platform, or say exactly why not.

This is the only place a hash is computed. The agent is told never to produce
a normalised value or a digest itself, and to copy this module's output
verbatim, because a model that "applies the rule" in its head produces a
plausible 64-character string that matches nothing.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from . import identity as ident
from .rules import FIELDS, PLATFORMS, NeedsReview, rule_for

STATUSES = ("ok", "needs_review", "invalid", "not_implemented", "unknown_field")


@dataclass(frozen=True)
class FieldResult:
    platform: str
    field: str
    param: str | None
    input: str
    status: str
    normalized: str | None = None
    hashed: bool = False
    sha256: str | None = None
    send: str | None = None
    reason: str | None = None
    kb_entry: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _platform(name: str) -> str:
    platform = name.strip().lower()
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}; got {name!r}")
    return platform


def _region(region: str | None) -> str | None:
    cleaned = (region or "").strip(ident.ASCII_WHITESPACE).upper()
    return cleaned or None


def _blank(value: object) -> bool:
    # ASCII only on purpose: a cell holding U+00A0 is not empty, it is invalid,
    # and the field rule should say so rather than the row silently losing it.
    return value is None or str(value).strip(ident.ASCII_WHITESPACE) == ""


def normalize_and_hash(
    platform: str,
    field: str,
    value: str,
    *,
    default_region: str | None = None,
    encoding: str = "HEX",
) -> FieldResult:
    platform = _platform(platform)
    default_region = _region(default_region)
    enc = ident.HashEncoding(encoding.strip().upper())
    if platform == "meta" and enc is not ident.HashEncoding.HEX:
        raise ValueError(
            "Meta's published examples are lowercase hex SHA-256; this tool does "
            "not produce Base64 for Meta"
        )

    rule = rule_for(platform, field)
    if rule is None:
        return FieldResult(
            platform=platform,
            field=field,
            param=None,
            input=value,
            status="unknown_field",
            reason=f"no rule for {platform}/{field}; known fields are {', '.join(FIELDS)}",
        )
    base = {"platform": platform, "field": rule.field, "param": rule.param,
            "input": value, "kb_entry": rule.kb_entry}
    if rule.normalise is None:
        return FieldResult(
            **base,
            status="not_implemented",
            hashed=rule.hashed,
            reason=f"the tool has no normaliser for {platform}/{rule.field}; the "
            f"documented rule is in the Knowledge Base entry {rule.kb_entry}",
        )

    try:
        outcome = rule.normalise(value, default_region)
    except ident.InvalidIdentifier as exc:
        return FieldResult(**base, status="invalid", hashed=rule.hashed, reason=str(exc))
    if isinstance(outcome, NeedsReview):
        return FieldResult(**base, status="needs_review", hashed=rule.hashed, reason=outcome.reason)

    digest = ident.sha256_digest(outcome, encoding=enc) if rule.hashed else None
    return FieldResult(
        **base,
        status="ok",
        normalized=outcome,
        hashed=rule.hashed,
        sha256=digest,
        send=digest if rule.hashed else outcome,
    )


def record_region(record: Mapping[str, str], default_region: str | None) -> tuple[str | None, str | None]:
    """The region a record's phone and postal code are read in, and where it came from.

    A record that carries its own two-letter country is read in that country;
    the account-wide default applies only to records without one. A country
    field that is not a two-letter code is not interpreted here (the country
    rule itself reports it), so it falls back to the default instead of being
    guessed from.
    """
    raw = str(record.get("country") or "").strip(ident.ASCII_WHITESPACE)
    if len(raw) == 2 and raw.isascii() and raw.isalpha():
        return raw.upper(), "record"
    region = _region(default_region)
    return (region, "default_region") if region else (None, None)


def preflight_batch(
    records: Iterable[Mapping[str, str]],
    *,
    platforms: Iterable[str] = PLATFORMS,
    default_region: str | None = None,
) -> dict[str, object]:
    """Run every known field of every record through every platform.

    Keys that are not canonical field names are listed per record as
    ``unmapped`` rather than guessed at: mapping a CRM column to a field is a
    decision, and it belongs to whoever called this. Each record is read in
    its own country when it has one (see :func:`record_region`), because a
    US ZIP+4 hashed without the five-digit cut, or a national phone number
    with no country, silently never matches.
    """
    chosen = list(dict.fromkeys(_platform(p) for p in platforms))
    rows: list[dict[str, object]] = []
    totals: dict[str, dict[str, int]] = {p: dict.fromkeys(STATUSES, 0) for p in chosen}
    for index, record in enumerate(records):
        fields: dict[str, dict[str, object]] = {}
        unmapped = sorted(k for k in record if k not in FIELDS)
        region, region_source = record_region(record, default_region)
        for platform in chosen:
            per_platform: dict[str, object] = {}
            for name in FIELDS:
                raw = record.get(name)
                if _blank(raw):
                    continue
                result = normalize_and_hash(platform, name, str(raw), default_region=region)
                totals[platform][result.status] += 1
                per_platform[name] = result.as_dict()
            fields[platform] = per_platform
        row: dict[str, object] = {"row": index, "region": region, "region_source": region_source,
                                  "results": fields}
        if unmapped:
            row["unmapped"] = unmapped
        rows.append(row)
    return {"default_region": default_region, "platforms": chosen, "totals": totals, "rows": rows}


_HONORIFICS = frozenset({"mr", "mrs", "ms", "miss", "dr", "prof", "sr", "sra", "srta"})
_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "phd", "md", "esq"})


def warnings_for(record: Mapping[str, str], platform: str) -> list[dict[str, str]]:
    """Values the rules accept but the documentation says will not match.

    These are the checks a reviewer does by eye, written down so they run on
    every row: a title or suffix left in a Google name field, whitespace inside
    an email address, a Meta record with no country. Each one names the rule
    it comes from; none of them changes a value.
    """
    found: list[dict[str, str]] = []
    if platform == "google":
        for name, words, what in (("first_name", _HONORIFICS, "prefixes such as Mrs."),
                                  ("last_name", _SUFFIXES, "suffixes such as Jr.")):
            raw = str(record.get(name) or "")
            tokens = {t.strip(".,").lower() for t in raw.split()}
            if tokens & words:
                found.append({"field": name, "input": raw,
                              "warning": f"Google's rule for this field says not to include {what}"})
    email = str(record.get("email") or "").strip(ident.ASCII_WHITESPACE)
    if any(ch in ident.ASCII_WHITESPACE for ch in email):
        found.append({"field": "email", "input": email,
                      "warning": "whitespace inside the address was removed; a valid address "
                      "has none, so the source value is probably a typo"})
    if platform == "meta" and _blank(record.get("country")):
        found.append({"field": "country", "input": "",
                      "warning": "Meta asks for the country on every record, even when all "
                      "data is from one country"})
    return found


def _display(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _within(root: Path, candidate: str) -> Path:
    path = (root / candidate).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"{candidate!r} is outside the project directory")
    if path.suffix.lower() != ".csv" or not path.is_file():
        raise ValueError(f"{candidate!r} is not a CSV file in the project directory")
    return path


def preflight_file(
    path: str,
    columns: Mapping[str, str],
    *,
    root: Path,
    out_dir: Path,
    id_column: str | None = None,
    platforms: Iterable[str] = PLATFORMS,
    default_region: str | None = None,
    max_findings: int = 200,
) -> dict[str, object]:
    """Check a CSV export without the rows ever passing through a model.

    The caller supplies only the mapping from CSV headers to canonical fields
    (and, optionally, the column that identifies a lead). The file is read
    here, every row goes through :func:`preflight_batch`, the full result and
    the upload view are written to ``out_dir``, and what comes back is the
    part a person has to act on: the totals, the values that were not
    accepted, and the warnings, capped at ``max_findings`` (the file has all
    of them).
    """
    source = _within(root, path)
    unknown = sorted(set(columns.values()) - set(FIELDS))
    if unknown:
        raise ValueError(f"unknown canonical fields {unknown}; known fields are {', '.join(FIELDS)}")
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        missing = sorted((set(columns) | ({id_column} if id_column else set())) - set(headers))
        if missing:
            raise ValueError(f"columns not in the file header: {missing}")
        rows = list(reader)

    records = [{columns[h]: row.get(h) or "" for h in columns} for row in rows]
    ids = [(row.get(id_column) or "") if id_column else str(i) for i, row in enumerate(rows)]
    report = preflight_batch(records, platforms=platforms, default_region=default_region)

    findings: list[dict[str, object]] = []
    upload: list[dict[str, object]] = []
    for row_id, record, result in zip(ids, records, report["rows"], strict=True):
        entry: dict[str, object] = {"id": row_id, "row": result["row"]}
        for platform, fields in result["results"].items():
            entry[platform] = {r["param"]: r["send"] for r in fields.values() if r["status"] == "ok"}
            for name, r in fields.items():
                if r["status"] != "ok":
                    findings.append({"id": row_id, "platform": platform, "field": name,
                                     "input": r["input"], "status": r["status"],
                                     "reason": r.get("reason", "")})
            for warning in warnings_for(record, platform):
                findings.append({"id": row_id, "platform": platform, "status": "warning", **warning})
        upload.append(entry)

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    upload_path = out_dir / f"{source.stem}-{stamp}.upload.json"
    upload_path.write_text(json.dumps({"source": source.name, "platforms": report["platforms"],
                                       "rows": upload, "findings": findings, "report": report},
                                      indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sources = {}
    for r in report["rows"]:
        sources[r["region_source"] or "none"] = sources.get(r["region_source"] or "none", 0) + 1
    return {
        "file": source.name,
        "rows": len(rows),
        "platforms": report["platforms"],
        "totals": report["totals"],
        "region_sources": sources,
        "findings": findings[:max_findings],
        "findings_total": len(findings),
        "upload_file": _display(upload_path, root),
    }
