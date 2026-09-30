"""The rule table must describe the code it sits next to, and the platforms' own examples."""

from __future__ import annotations

import hashlib

import pytest

from preflight import identity as ident
from preflight.core import normalize_and_hash
from preflight.rules import FIELDS, PLATFORMS, RULES, rule_for

EXAMPLES = [(rule, ex) for rule in RULES for ex in rule.doc_examples]
DIGESTS = [(rule, ex) for rule, ex in EXAMPLES if ex.sha256 is not None]


def test_every_platform_field_pair_has_exactly_one_rule():
    keys = [(r.platform, r.field) for r in RULES]
    assert sorted(keys) == sorted((p, f) for p in PLATFORMS for f in FIELDS)


@pytest.mark.parametrize(
    ("rule", "example"), DIGESTS, ids=[f"{r.platform}-{r.field}-{e.input}" for r, e in DIGESTS]
)
def test_published_hash_is_the_hash_of_the_published_normalized_value(rule, example):
    # Guards the transcription: a digest copied wrong from the page fails here,
    # before it can make the code look wrong.
    assert hashlib.sha256(example.normalized.encode("utf-8")).hexdigest() == example.sha256


@pytest.mark.parametrize(
    ("rule", "example"), EXAMPLES, ids=[f"{r.platform}-{r.field}-{e.input}" for r, e in EXAMPLES]
)
def test_code_reproduces_each_documented_example_or_declares_why_not(rule, example):
    result = normalize_and_hash(
        rule.platform, rule.field, example.input, default_region=example.region
    )
    if example.diverges:
        assert rule.divergences, "a diverging example needs a declared reason"
        assert result.status != "ok" or result.normalized != example.normalized
        return
    assert result.status == "ok", result.reason
    assert result.normalized == example.normalized
    if example.sha256 is not None:
        assert result.sha256 == example.sha256


def test_hashed_flag_agrees_with_the_quoted_documentation():
    for rule in RULES:
        says_dont_hash = "Don't hash" in rule.doc_quote
        assert rule.hashed is not says_dont_hash, f"{rule.platform}/{rule.field}"


def test_unimplemented_rules_say_so_and_implemented_ones_do_not():
    for rule in RULES:
        assert rule.implemented is not rule.implementation.startswith("Not implemented")


def test_declared_meta_email_divergence_is_still_the_codes_behaviour():
    # If upstream starts trimming only the ends, this fails and the divergence
    # entry has to be removed from the table rather than left lying.
    assert ident.normalise_email_meta("John Smith@example.com") == "johnsmith@example.com"
    assert "Trim any leading and trailing spaces" in rule_for("meta", "email").doc_quote


def test_declared_meta_phone_divergence_is_still_the_codes_behaviour():
    result = normalize_and_hash("meta", "phone", "650-555-1212 ext 4", default_region="US")
    assert result.status == "needs_review"


def test_declared_meta_state_divergence_is_still_the_codes_behaviour():
    assert normalize_and_hash("meta", "state", "California").normalized == "california"


def test_describe_never_leaks_the_callable():
    for rule in RULES:
        assert "normalise" not in rule.describe()


def test_declared_phone_length_divergence_is_still_the_codes_behaviour():
    # +683 4002 is a 7-digit E.164 number; the code's floor is 8.
    for platform in ("google", "meta"):
        assert normalize_and_hash(platform, "phone", "+683 4002").status == "needs_review"


def test_declared_meta_name_space_divergence_is_still_the_codes_behaviour():
    assert normalize_and_hash("meta", "first_name", "Mary Ann").normalized == "maryann"
    assert normalize_and_hash("meta", "last_name", "Van Der Berg").normalized == "vanderberg"


def test_meta_phone_leading_zero_divergence_is_still_the_codes_behaviour():
    # A national number that keeps a leading 0 in a plan without a trunk 0 is
    # refused, not stripped.
    assert normalize_and_hash("meta", "phone", "0650 555 1212", default_region="US").status == "needs_review"
    assert normalize_and_hash("meta", "phone", "020 7946 0000", default_region="GB").normalized == "442079460000"


def test_meta_names_drop_symbols_but_keep_letters():
    assert normalize_and_hash("meta", "first_name", "Zo\u00eb\u2122").normalized == "zo\u00eb"


def test_declared_google_title_divergence_is_still_the_codes_behaviour():
    assert normalize_and_hash("google", "first_name", "Mrs. Carol").normalized == "mrs. carol"
    assert normalize_and_hash("google", "last_name", "Nguyen Jr.").normalized == "nguyen jr."
