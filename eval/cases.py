"""Evaluation cases, graded by code.

Expected digests come from two places and never from a model: the tested
normaliser in :mod:`preflight`, and, where a platform publishes one, the
platform's own worked example (the Meta phone, first-name and country
vectors). A case passes only if every expected digest appears verbatim and
every other 64-character hex string in the answer came out of a tool result in
the same run, so a digest the model wrote itself fails the case even when the
expected one is also present. Refusal cases allow no digest at all, not even
one a tool produced, and rule cases are graded on the claim that answers the
question, not on the presence of a "no".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from preflight.common import HEX64  # noqa: F401  (re-exported for the grader and tests)
from preflight.core import normalize_and_hash

GRADER_VERSION = 2
"""1: no digest other than the expected ones. 2: provenance rule, refusal cases
forbid every digest, rule cases check the central claim (after the first
graded run, see the README)."""

NEG = r"(?<!not )(?<!n't )(?<!never )"
"""Put in front of a verb so that "do not send X" does not count as "send X"."""


def sent(platform: str, field_name: str, value: str, region: str | None = None) -> str:
    result = normalize_and_hash(platform, field_name, value, default_region=region)
    assert result.status == "ok" and result.send, (platform, field_name, value, result)
    return result.send


@dataclass(frozen=True)
class Case:
    id: str
    kind: str  # value | refusal | rule
    prompt: str
    expect_hashes: tuple[str, ...] = ()
    must: tuple[str, ...] = ()  # regexes that must match (case-insensitive)
    must_not: tuple[str, ...] = ()  # regexes that must not match
    cite: tuple[str, ...] = ()  # entry paths that must be cited
    tools: tuple[str, ...] = ()  # tools that must have been called
    notes: str = ""
    extra: dict = field(default_factory=dict)


META_PUBLISHED_PHONE = "e323ec626319ca94ee8bff2e4c87cf613be6ea19919ed1364124e16807ab3176"
META_PUBLISHED_VALERY = "08e1996b5dd49e62a4b4c010d44e4345592a863bb9f8e3976219bac29417149c"
META_PUBLISHED_US = "79adb2a2fce5c6ba215fe5f27f532d4e7edbac4b6a5e09e1ef3a08084a904621"

CASES: tuple[Case, ...] = (
    Case(
        id="V1-gmail-both",
        kind="value",
        prompt="What exactly do I send to Google and to Meta for the email ' Jane.Doe+promo@GMAIL.com '?",
        expect_hashes=(
            sent("google", "email", " Jane.Doe+promo@GMAIL.com "),
            sent("meta", "email", " Jane.Doe+promo@GMAIL.com "),
        ),
        cite=("normalization_and_hashing/google", "normalization_and_hashing/meta"),
        tools=("normalize_and_hash|preflight_batch",),
    ),
    Case(
        id="V2-meta-phone-published",
        kind="value",
        prompt="Our Meta pixel is on a US account. What is the hashed ph value for the phone (650)555-1212?",
        expect_hashes=(META_PUBLISHED_PHONE,),
        cite=("normalization_and_hashing/meta",),
        tools=("normalize_and_hash|preflight_batch",),
        notes="Meta publishes this digest on its own page.",
    ),
    Case(
        id="V3-meta-fn-accent",
        kind="value",
        prompt="What is the fn hash for the first name 'Valéry' for the Conversions API?",
        expect_hashes=(META_PUBLISHED_VALERY,),
        cite=("normalization_and_hashing/meta",),
        tools=("normalize_and_hash|preflight_batch",),
        notes="Published by Meta; a model that strips the accent gets a different digest.",
    ),
    Case(
        id="V4-google-phone",
        kind="value",
        prompt="Give me the phone_number hash for Google Data Manager for the US number (800)555-0100.",
        expect_hashes=(sent("google", "phone", "(800)555-0100", "US"),),
        cite=("normalization_and_hashing/google",),
        tools=("normalize_and_hash|preflight_batch",),
    ),
    Case(
        id="V5-zip-plus-four",
        kind="value",
        prompt=(
            "The customer's ZIP is 94035-1234 in the US. What goes in Google's postal_code "
            "and what goes in Meta's zp?"
        ),
        expect_hashes=(sent("meta", "postal_code", "94035-1234", "US"),),
        must=(r"94035-1234",),
        cite=("normalization_and_hashing/google", "normalization_and_hashing/meta"),
        tools=("normalize_and_hash|preflight_batch",),
        notes="Google takes ZIP+4 in clear; Meta hashes the first five digits.",
    ),
    Case(
        id="V6-meta-country",
        kind="value",
        prompt="What is Meta's country hash for a customer in the US (code 'US')?",
        expect_hashes=(META_PUBLISHED_US,),
        cite=("normalization_and_hashing/meta",),
        tools=("normalize_and_hash|preflight_batch",),
    ),
    Case(
        id="R1-phone-no-country",
        kind="refusal",
        prompt="Hash the phone 555-0199 for Meta. We don't know which country the lead is in.",
        must=(r"country",),
        tools=("normalize_and_hash|preflight_batch",),
        notes="No digest may appear: the number cannot be completed without a country.",
    ),
    Case(
        id="R2-invisible-char",
        kind="refusal",
        prompt="Hash this email for Google: 'tom​.reyes@example.com' (copied from our CRM export).",
        must=(r"U\+200B",),
        tools=("normalize_and_hash|preflight_batch",),
    ),
    Case(
        id="R3-country-name",
        kind="refusal",
        prompt="Our CRM stores the country as 'United States'. Hash it for Meta as-is, please.",
        must=(r"two-letter|2-letter|ISO", r"\bUS\b|\bus\b"),
        tools=("normalize_and_hash|preflight_batch",),
        notes="The code refuses names; a digest of 'us' is fine only if computed by the tool.",
        extra={"allow_hashes": (META_PUBLISHED_US,)},
    ),
    Case(
        id="K1-meta-gmail-dots",
        kind="rule",
        prompt=(
            "Does Meta want the dots and the +suffix removed from 'Jane.Doe+promo@gmail.com' "
            "before hashing, like Google does?"
        ),
        must=(r"jane\.doe\+promo@gmail\.com",),
        must_not=(r"^\W*yes\b", r"NEG\b(meta )?(also )?(removes|strips|drops) the dots".replace("NEG", NEG)),
        extra={"allow_hashes": (sent("meta", "email", "Jane.Doe+promo@gmail.com"),
                                sent("google", "email", "Jane.Doe+promo@gmail.com"))},
        cite=("normalization_and_hashing/meta",),
        tools=("knowledge_base_read|knowledge_base_search",),
    ),
    Case(
        id="K2-google-base64",
        kind="rule",
        prompt="Can I send Base64-encoded SHA-256 hashes to the Google Data Manager API, or only hex?",
        must=(r"base64",),
        must_not=(r"base64 (encoding )?is not (used|accepted|supported)", r"(?<!not )\bonly hex\b"),
        cite=("normalization_and_hashing/google",),
        tools=("knowledge_base_read|knowledge_base_search",),
        notes="A rebuild of the entry once said 'Base64 encoding is not used'. The page says hex or Base64.",
    ),
    Case(
        id="K3-google-unhashed",
        kind="rule",
        prompt="Which address fields does Google want in clear text, not hashed?",
        must=(r"postal|zip", r"region_code|country", r"city", r"administrative_area|state"),
        must_not=(r"NEG\bhash(ed)? (the )?(city|state|country|region|postal|zip)".replace("NEG", NEG),),
        cite=("normalization_and_hashing/google",),
        tools=("knowledge_base_read|knowledge_base_search",),
    ),
    Case(
        id="K4-brazil-cep",
        kind="rule",
        prompt="A Brazilian customer's CEP is 24020-005. What do I send as Google's postal_code?",
        must=(r"(?<!whether to )NEG\bsend\s+`?24020-005".replace("NEG", NEG),),
        must_not=(r"NEG\bsend (only )?`?24020`?(?![-\d])".replace("NEG", NEG),
                  r"wants `?24020`?(?![-\d])", r"drop (the )?`?-?005",
                  r"(cut|truncate)[^.\n]{0,30}24020(?!-)"),
        cite=("normalization_and_hashing/google",),
        notes="An earlier knowledge base entry invented '5-digit equivalents only' and the agent told me to cut the CEP to 24020.",
    ),
    Case(
        id="K5-non-gmail-dots",
        kind="rule",
        prompt=(
            "Some sample code strips the dots from every email before hashing for Google. "
            "Should first.last@company.com become firstlast@company.com?"
        ),
        must=(r"first\.last@company\.com",),
        must_not=(r"^\W*yes\b", r"NEG\bshould become `?firstlast".replace("NEG", NEG),
                  r"`?firstlast@company\.com`? is (correct|right)"),
        cite=("normalization_and_hashing/google",),
        extra={"allow_hashes": (sent("google", "email", "first.last@company.com"),)},
        notes=(
            "Google's own Python sample on the Manage offline conversions page does exactly this; "
            "the documented rule keeps dots outside gmail.com and googlemail.com."
        ),
    ),
)
