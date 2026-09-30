"""Email normalisation: two documented specifications, one of them surprising.

The anchor of this file, and arguably of the repository, is
``test_the_same_gmail_address_hashes_differently_for_the_two_destinations``.
One shared ``normalise_email`` is the shortcut every integration takes, and it
silently halves the match rate at whichever destination it got wrong.
"""

from __future__ import annotations

import pytest

from preflight.identity import (
    HashEncoding,
    InvalidIdentifier,
    normalise_email_google,
    normalise_email_meta,
    sha256_digest,
)

META_EMAIL_VECTOR = (
    "John_Smith@gmail.com",
    "john_smith@gmail.com",
    "62a14e44f765419d10fea99367361a727c12365e2520f32218d505ed9aa0f62f",
)
"""Straight from Meta's customer-information reference: the input, the
"standardised format" it publishes, and the SHA-256 it says to expect."""

GOOGLE_GMAIL_VECTOR = (
    "cloudy.sanfrancisco+shopping@gmail.com",
    "cloudysanfrancisco@gmail.com",
)
"""Straight from the Data Manager API's "Format user data" guide."""

GOOGLE_OTHER_DOMAIN_VECTOR = ("user.name+NYC@Example.com", "user.name+nyc@example.com")
"""The same guide's counter-example: a non-Google domain keeps both."""


def test_the_meta_reference_vector_reproduces_its_published_hash() -> None:
    raw, normalised, expected = META_EMAIL_VECTOR
    assert normalise_email_meta(raw) == normalised
    assert sha256_digest(normalise_email_meta(raw)) == expected


def test_the_google_guide_gmail_example_reproduces_its_published_form() -> None:
    raw, normalised = GOOGLE_GMAIL_VECTOR
    assert normalise_email_google(raw) == normalised


def test_the_google_guide_other_domain_example_keeps_the_dot_and_the_plus() -> None:
    raw, normalised = GOOGLE_OTHER_DOMAIN_VECTOR
    assert normalise_email_google(raw) == normalised


def test_the_same_gmail_address_hashes_differently_for_the_two_destinations() -> None:
    """The whole doctrine in one assertion.

    Google's guide removes dots and the plus suffix on its own domains and
    warns that failing to do so "will result in different hash values than
    Google expects for these domains, leading to missed matches". Meta's
    reference asks for lowercasing and whitespace removal and nothing else,
    and its own worked example is on a gmail address that keeps its local
    part. So the correct value for one destination is the wrong value for the
    other, and any implementation with a single normaliser is silently losing
    matches at one of them.
    """
    raw = "cloudy.sanfrancisco+shopping@gmail.com"
    assert normalise_email_google(raw) != normalise_email_meta(raw)
    assert sha256_digest(normalise_email_google(raw)) != sha256_digest(
        normalise_email_meta(raw)
    )


def test_on_a_non_google_domain_the_two_agree() -> None:
    """The divergence is domain-specific, not universal. An implementation
    tested only on example.com addresses passes and is still wrong."""
    raw = "Dana.Whitfield@example.com"
    assert normalise_email_google(raw) == normalise_email_meta(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("first.last@googlemail.com", "firstlast@googlemail.com"),
        ("first.last+tag@googlemail.com", "firstlast@googlemail.com"),
        ("F.I.R.S.T@GMAIL.COM", "first@gmail.com"),
        ("first+a+b@gmail.com", "first@gmail.com"),
    ],
)
def test_google_applies_the_rules_to_both_google_domains(raw: str, expected: str) -> None:
    assert normalise_email_google(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("first.last@outlook.example", "first.last@outlook.example"),
        ("first+tag@outlook.example", "first+tag@outlook.example"),
        ("FIRST.LAST@Outlook.Example", "first.last@outlook.example"),
    ],
)
def test_google_leaves_other_domains_alone_apart_from_case(
    raw: str, expected: str
) -> None:
    assert normalise_email_google(raw) == expected


def test_google_trims_intermediate_whitespace_as_the_guide_asks() -> None:
    """The guide says "trim leading, trailing and intermediate whitespace",
    and intermediate is the word most implementations skip."""
    assert normalise_email_google(" dana wh itfield@example.com ") == (
        "danawhitfield@example.com"
    )


def test_meta_removes_whitespace_as_its_reference_asks() -> None:
    assert normalise_email_meta("  Dana Whitfield@example.com ") == (
        "danawhitfield@example.com"
    )


@pytest.mark.parametrize(
    "raw",
    [
        " dana@example.com",
        "dana@example.com ",
        "\tdana@example.com\n",
        "\r\vdana@example.com\f",
    ],
)
def test_ascii_whitespace_is_trimmed_by_both(raw: str) -> None:
    assert normalise_email_google(raw) == "dana@example.com"
    assert normalise_email_meta(raw) == "dana@example.com"


def test_lowercase_is_str_lower_and_not_casefold() -> None:
    """``casefold`` maps U+00DF SHARP S onto ``ss``, which is a
    transliteration and not a lowercasing. Both vendors say "convert to
    lowercase", so both normalisers use ``str.lower``, and this pins it: if
    somebody swaps in ``casefold`` for tidiness, every German address in the
    system starts hashing to a different value.
    """
    raw = "straße@example.com"
    assert normalise_email_google(raw) == "straße@example.com"
    assert normalise_email_meta(raw) == "straße@example.com"
    assert raw.casefold() == "strasse@example.com"


def test_the_kelvin_sign_lowercases_the_way_the_instruction_says() -> None:
    """U+212A KELVIN SIGN lowercases to ASCII k under ``str.lower``.

    Recorded rather than fought. In a CRM deduplication key this fold is a
    disaster because it merges two records irreversibly. Here the output is a
    hash that either matches the platform's or does not, and the platforms
    say "lowercase", so the documented instruction wins and the behaviour is
    pinned instead of assumed.
    """
    assert normalise_email_meta("Kelvin@example.com") == "kelvin@example.com"


@pytest.mark.parametrize(
    "raw",
    ["dana@example.com ", "　dana@example.com", "da​na@example.com"],
)
def test_exotic_whitespace_and_invisibles_are_refused_loudly(raw: str) -> None:
    """Neither vendor documents what it does with U+00A0, U+3000 or a
    zero-width space, and silently dropping one produces a hash for an
    address nobody typed."""
    with pytest.raises(InvalidIdentifier, match="U\\+"):
        normalise_email_google(raw)
    with pytest.raises(InvalidIdentifier, match="U\\+"):
        normalise_email_meta(raw)


def test_the_refusal_names_the_code_point_rather_than_printing_it() -> None:
    with pytest.raises(InvalidIdentifier, match="U\\+200B"):
        normalise_email_meta("da​na@example.com")


@pytest.mark.parametrize(
    "raw", ["danaexample.com", "dana@@example.com", "dana@ex@ample.com"]
)
def test_an_address_without_exactly_one_at_sign_is_refused(raw: str) -> None:
    with pytest.raises(InvalidIdentifier, match="exactly one @"):
        normalise_email_google(raw)


def test_an_empty_local_part_is_refused() -> None:
    with pytest.raises(InvalidIdentifier, match="empty local part"):
        normalise_email_meta("@example.com")


@pytest.mark.parametrize("domain", ["example", ".example.com", "example.com."])
def test_an_implausible_domain_is_refused(domain: str) -> None:
    with pytest.raises(InvalidIdentifier, match="plausible mail domain"):
        normalise_email_google(f"dana@{domain}")


def test_a_gmail_local_part_that_the_rules_empty_is_refused() -> None:
    """``+tag@gmail.com`` has a local part that the documented rules delete
    entirely. Hashing an empty string would produce a perfectly valid looking
    identifier that matches nobody."""
    with pytest.raises(InvalidIdentifier, match="no address left to hash"):
        normalise_email_google("+tag@gmail.com")


def test_hex_is_the_default_encoding() -> None:
    digest = sha256_digest("dana@example.com")
    assert len(digest) == 64
    assert digest == digest.lower()


def test_base64_encoding_is_available_and_different() -> None:
    """The API's ``Encoding`` enum offers both, and notes that hex case does
    not matter while Base64 case does."""
    hex_digest = sha256_digest("dana@example.com", encoding=HashEncoding.HEX)
    b64_digest = sha256_digest("dana@example.com", encoding=HashEncoding.BASE64)
    assert hex_digest != b64_digest
    assert len(b64_digest) == 44


def test_the_hash_function_does_no_normalising_of_its_own() -> None:
    """A hash that quietly normalises can be called with the wrong dialect and
    still look like it worked."""
    assert sha256_digest("DANA@EXAMPLE.COM") != sha256_digest("dana@example.com")
