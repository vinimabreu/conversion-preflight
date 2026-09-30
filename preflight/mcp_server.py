"""Stdio MCP server exposing the preflight tools to the agent.

Three tools, all deterministic and offline: no network, no model. The only
side effect is preflight_file writing its upload file under runs/uploads/.
What the code declares about its own rules is not served here: it is published
to the Sanity dataset by sanity_sync, and the agent reads it from there.
The Knowledge Base says what each platform documents; these tools say what the
code does and compute the values. Keeping the two in different servers is what
lets the agent notice when they disagree.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer

from .core import normalize_and_hash as _normalize_and_hash
from .core import preflight_batch as _preflight_batch
from .core import preflight_file as _preflight_file

server = MCPServer(
    name="preflight",
    instructions=(
        "Deterministic normalisation and SHA-256 hashing for Google Data Manager "
        "and Meta Conversions API customer data. Copy normalized values and hashes "
        "verbatim; never compute or edit one yourself."
    ),
)


@server.tool()
def normalize_and_hash(
    platform: Literal["google", "meta"],
    field: Literal[
        "email", "phone", "first_name", "last_name", "city", "state", "postal_code", "country"
    ],
    value: str,
    default_region: str | None = None,
    encoding: Literal["HEX", "BASE64"] = "HEX",
) -> dict[str, object]:
    """Normalise one value for one platform and hash it when the platform hashes that field.

    status is ok, needs_review (phone the rules will not guess about), invalid
    (value that cannot be normalised), not_implemented, or unknown_field. On ok,
    `send` is exactly what goes in the payload: the hash for hashed fields, the
    normalised value for fields the platform wants in clear. default_region is an
    ISO 3166-1 alpha-2 code used only for phones without a country code and for
    the US five-digit ZIP rule. BASE64 is accepted for Google only.
    """
    return _normalize_and_hash(
        platform, field, value, default_region=default_region, encoding=encoding
    ).as_dict()


@server.tool()
def preflight_batch(
    records: list[dict[str, str]],
    platforms: list[Literal["google", "meta"]] | None = None,
    default_region: str | None = None,
) -> dict[str, object]:
    """Run a few inline records through both platforms at once (for files, use preflight_file).

    Each record maps canonical field names (email, phone, first_name, last_name,
    city, state, postal_code, country) to raw values. Map CRM column names to
    these before calling; keys that are not canonical come back as `unmapped`.
    A record with its own two-letter country is read in that country for phones
    and the US five-digit ZIP rule; default_region covers records without one.
    Returns per-row, per-platform results plus status totals.
    """
    return _preflight_batch(
        records, platforms=platforms or ("google", "meta"), default_region=default_region
    )


ROOT = Path(os.environ.get("PREFLIGHT_ROOT") or Path(__file__).resolve().parent.parent)


@server.tool()
def preflight_file(
    path: str,
    columns: dict[str, str],
    id_column: str | None = None,
    platforms: list[Literal["google", "meta"]] | None = None,
    default_region: str | None = None,
) -> dict[str, object]:
    """Check a CSV export for both platforms without passing its rows through you.

    path is relative to the project directory. columns maps CSV header names to
    canonical fields (email, phone, first_name, last_name, city, state,
    postal_code, country); leave out columns that are not customer data.
    id_column names the column that identifies a lead, so findings and the upload
    file are keyed by it. The file is read here, the upload file is written
    here, and the reply carries totals, every value that was not accepted, and
    every warning about an accepted value the documentation says will not match.
    """
    return _preflight_file(
        path, columns, root=ROOT, out_dir=ROOT / "runs" / "uploads", id_column=id_column,
        platforms=platforms or ("google", "meta"), default_region=default_region,
    )


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
