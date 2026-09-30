from __future__ import annotations

from preflight.rules import RULES
from preflight.sanity_sync import PROFILE_ID, documents, mutations, rule_document


def test_one_document_per_rule_plus_the_profile_with_stable_ids():
    ids = [d["_id"] for d in documents()]
    assert len(ids) == len(set(ids)) == len(RULES) + 1
    assert ids[-1] == PROFILE_ID
    assert "normalizationRule-google-email" in ids
    assert not any("." in i for i in ids)  # a dotted id is a private path in Sanity
    assert documents() == documents()  # deterministic, so re-running is a no-op


def test_every_array_member_object_has_a_key():
    for doc in documents():
        for value in doc.values():
            if isinstance(value, list):
                for member in value:
                    if isinstance(member, dict):
                        assert member.get("_key"), doc["_id"]


def test_profile_references_every_rule():
    profile = documents()[-1]
    assert [ref["_ref"] for ref in profile["rules"]] == [d["_id"] for d in documents()[:-1]]
    assert profile["globalDivergences"]


def test_rule_document_carries_the_quote_the_source_and_the_examples():
    rule = next(r for r in RULES if (r.platform, r.field) == ("meta", "country"))
    doc = rule_document(rule)
    assert doc["source"]["url"].startswith("https://developers.facebook.com/")
    assert doc["kbEntry"] == "normalization_and_hashing/meta"
    assert doc["docExamples"][0]["diverges"] is True
    assert doc["docQuote"] == rule.doc_quote


def test_writes_are_create_or_replace_only():
    assert all(set(m) == {"createOrReplace"} for m in mutations()["mutations"])
