from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from preflight.core import normalize_and_hash, preflight_batch

ROOT = Path(__file__).resolve().parent.parent


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_same_gmail_address_hashes_differently_per_platform_and_both_are_right():
    raw = " Jane.Doe+promo@GMAIL.com "
    google = normalize_and_hash("google", "email", raw)
    meta = normalize_and_hash("meta", "email", raw)
    assert google.normalized == "janedoe@gmail.com"
    assert meta.normalized == "jane.doe+promo@gmail.com"
    assert google.send == sha("janedoe@gmail.com")
    assert meta.send == sha("jane.doe+promo@gmail.com")
    assert google.send != meta.send


def test_fields_google_wants_in_clear_are_sent_in_clear():
    result = normalize_and_hash("google", "postal_code", " 94035-1234 ")
    assert result.status == "ok"
    assert result.hashed is False
    assert result.sha256 is None
    assert result.send == "94035-1234"


def test_meta_zip_keeps_five_digits_only_for_the_us():
    assert normalize_and_hash("meta", "postal_code", "94035-1234", default_region="US").normalized == "94035"
    assert normalize_and_hash("meta", "postal_code", "M1 1AE", default_region="GB").normalized == "m11ae"
    # With no region at all, a ZIP+4 is not hashed whole: that digest would
    # silently never match a US customer.
    unknown = normalize_and_hash("meta", "postal_code", "94035-1234")
    assert unknown.status == "needs_review" and unknown.sha256 is None
    assert normalize_and_hash("meta", "postal_code", "75018").normalized == "75018"


def test_phone_without_country_code_is_not_guessed():
    result = normalize_and_hash("meta", "phone", "(650) 555-1212")
    assert result.status == "needs_review"
    assert "guessing the country" in result.reason
    assert result.sha256 is None and result.send is None


def test_phone_spelling_differs_per_platform_from_one_parse():
    google = normalize_and_hash("google", "phone", "(650) 555-1212", default_region="US")
    meta = normalize_and_hash("meta", "phone", "(650) 555-1212", default_region="US")
    assert google.normalized == "+16505551212"
    assert meta.normalized == "16505551212"


def test_base64_is_google_only():
    result = normalize_and_hash("google", "email", "a@example.com", encoding="BASE64")
    raw = hashlib.sha256(b"a@example.com").digest()
    assert result.sha256 == base64.b64encode(raw).decode("ascii")
    with pytest.raises(ValueError, match="Meta"):
        normalize_and_hash("meta", "email", "a@example.com", encoding="BASE64")


def test_invalid_value_names_the_code_point_instead_of_hashing():
    result = normalize_and_hash("meta", "first_name", "Ana​")
    assert result.status == "invalid"
    assert "U+200B" in result.reason


def test_unimplemented_pair_points_at_the_knowledge_base():
    result = normalize_and_hash("google", "city", "Rio de Janeiro")
    assert result.status == "not_implemented"
    assert result.kb_entry == "normalization_and_hashing/google"


def test_unknown_field_and_platform():
    assert normalize_and_hash("meta", "date_of_birth", "1997-02-16").status == "unknown_field"
    with pytest.raises(ValueError):
        normalize_and_hash("tiktok", "email", "a@example.com")


def test_batch_reports_unmapped_columns_and_counts_statuses():
    report = preflight_batch(
        [
            {"email": "a@example.com", "phone": "650 555 1212", "Lead Source": "fair"},
            {"email": "not-an-email", "country": "United States"},
        ],
        default_region="US",
    )
    assert report["rows"][0]["unmapped"] == ["Lead Source"]
    assert "unmapped" not in report["rows"][1]
    assert report["totals"]["meta"] == {
        "ok": 2, "needs_review": 0, "invalid": 2, "not_implemented": 0, "unknown_field": 0,
    }
    assert report["totals"]["google"]["ok"] == 2
    assert report["totals"]["google"]["invalid"] == 2


def test_batch_reads_each_record_in_its_own_country():
    report = preflight_batch(
        [
            {"postal_code": "94035-1234", "country": "us"},
            {"phone": "020 7946 0000", "country": "GB"},
            {"phone": "650 555 1212"},
            {"phone": "650 555 1212", "country": "United States"},
        ],
        default_region="CA",
    )
    rows = report["rows"]
    assert (rows[0]["region"], rows[0]["region_source"]) == ("US", "record")
    assert rows[0]["results"]["meta"]["postal_code"]["normalized"] == "94035"
    assert rows[1]["results"]["google"]["phone"]["normalized"] == "+442079460000"
    assert (rows[2]["region"], rows[2]["region_source"]) == ("CA", "default_region")
    assert rows[2]["results"]["meta"]["phone"]["normalized"] == "16505551212"
    # A country that is not a two-letter code is reported by the country rule
    # and does not become the region.
    assert rows[3]["region_source"] == "default_region"
    assert rows[3]["results"]["meta"]["country"]["status"] == "invalid"


def test_batch_without_any_region_leaves_national_phones_for_review():
    report = preflight_batch([{"phone": "650 555 1212"}])
    assert report["rows"][0]["region"] is None
    assert report["rows"][0]["results"]["meta"]["phone"]["status"] == "needs_review"


@pytest.mark.parametrize("value", [
    "+44 (0)20 7946 0958",
    "+49 (0)30 1234567",
    "+44 020 7946 0958",
    "0044 020 7946 0958",
    "+55 021 90000 0001",
])
def test_trunk_zero_inside_an_international_number_is_not_hashed(value):
    for platform in ("google", "meta"):
        result = normalize_and_hash(platform, "phone", value)
        assert result.status == "needs_review", (platform, value, result)
        assert result.sha256 is None


def test_italian_numbers_keep_their_leading_zero():
    # Italy keeps the 0 in E.164, which is why the trunk check is per country.
    assert normalize_and_hash("google", "phone", "+39 06 6982 0000").normalized == "+390669820000"


def test_region_argument_is_cleaned_before_use():
    assert normalize_and_hash("meta", "phone", "650 555 1212", default_region=" us ").normalized == "16505551212"


def test_non_ascii_blank_cell_is_reported_not_dropped():
    report = preflight_batch([{"email": "\u00a0"}], platforms=["meta"])
    assert report["rows"][0]["results"]["meta"]["email"]["status"] == "invalid"


def test_duplicate_platforms_count_once_and_unknown_ones_fail():
    report = preflight_batch([{"email": "a@example.com"}], platforms=["meta", "META", "meta"])
    assert report["platforms"] == ["meta"] and report["totals"]["meta"]["ok"] == 1
    with pytest.raises(ValueError):
        preflight_batch([{"email": "a@example.com"}], platforms=["tiktok"])


def _exchange(messages: list[dict]) -> dict[int, dict]:
    """Send each message and, for requests, wait for the reply before the next.

    Closing stdin early makes the server shut down with a tool call in flight,
    so the pipe stays open until every awaited reply has arrived.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "preflight.mcp_server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=ROOT,
    )
    replies: dict[int, dict] = {}
    try:
        for message in messages:
            proc.stdin.write(json.dumps(message).encode() + b"\n")
            proc.stdin.flush()
            while "id" in message and message["id"] not in replies:
                line = proc.stdout.readline()
                if not line:
                    raise AssertionError("server closed stdout before replying")
                reply = json.loads(line)
                if "id" in reply:
                    replies[reply["id"]] = reply
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)
    return replies


def test_mcp_server_speaks_stdio_and_lists_its_tools():
    replies = _exchange([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "normalize_and_hash",
            "arguments": {"platform": "meta", "field": "email", "value": "John_Smith@gmail.com"}}},
    ])
    names = sorted(t["name"] for t in replies[2]["result"]["tools"])
    assert names == ["normalize_and_hash", "preflight_batch", "preflight_file"]
    text = "".join(c.get("text", "") for c in replies[3]["result"]["content"])
    assert "62a14e44f765419d10fea99367361a727c12365e2520f32218d505ed9aa0f62f" in text


@pytest.mark.parametrize("region", ["USA", "United States", "U.S.", "1A"])
def test_a_region_that_is_not_two_letters_is_an_error_not_a_silent_skip(region):
    with pytest.raises(ValueError, match="two-letter"):
        normalize_and_hash("meta", "postal_code", "94035-1234", default_region=region)
    with pytest.raises(ValueError, match="two-letter"):
        preflight_batch([{"postal_code": "94035-1234"}], default_region=region)


def test_zip_plus_four_with_spaces_is_still_caught_without_a_region():
    assert normalize_and_hash("meta", "postal_code", "94035 - 1234").status == "needs_review"
    assert normalize_and_hash("meta", "postal_code", "94035 - 1234", default_region="US").normalized == "94035"
