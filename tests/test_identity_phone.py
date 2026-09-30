"""Phone normalisation: E.164 for one destination, digits for the other, or a refusal."""

from __future__ import annotations

import pytest

from preflight.identity import NormalisedPhone, PhoneNeedsReview, normalise_phone, sha256_digest

META_PHONE_VECTOR = (
    "(650)555-1212",
    "16505551212",
    "e323ec626319ca94ee8bff2e4c87cf613be6ea19919ed1364124e16807ab3176",
)
"""From Meta's customer-information reference: a US number, the standardised
form it publishes, and the SHA-256 it says to expect."""

GOOGLE_PHONE_VECTOR = ("(800)555-0100", "+18005550100")
"""From the Data Manager API's formatting guide, verbatim."""


def resolved(value: str, *, region: str | None = None) -> NormalisedPhone:
    result = normalise_phone(value, default_region=region)
    assert isinstance(result, NormalisedPhone), result
    return result


def test_the_meta_reference_vector_reproduces_its_published_hash() -> None:
    raw, normalised, expected = META_PHONE_VECTOR
    assert resolved(raw, region="US").for_meta() == normalised
    assert sha256_digest(resolved(raw, region="US").for_meta()) == expected


def test_the_google_guide_example_reproduces_its_published_form() -> None:
    raw, normalised = GOOGLE_PHONE_VECTOR
    assert resolved(raw, region="US").for_google() == normalised


def test_the_two_spellings_differ_by_exactly_the_plus() -> None:
    """Google documents E.164, which carries the ``+``. Meta documents digits
    only. One normalisation, two renderings, so the two destinations can never
    disagree about which country a number belongs to."""
    phone = resolved("(650) 555-1212", region="US")
    assert phone.for_google() == f"+{phone.for_meta()}"


@pytest.mark.parametrize(
    "raw",
    [
        "+1 650 555 1212",
        "+1 (650) 555-1212",
        "+1.650.555.1212",
        "+1-650-555-1212",
        "  +16505551212  ",
    ],
)
def test_formatting_characters_carry_presentation_not_identity(raw: str) -> None:
    assert resolved(raw).e164 == "+16505551212"


def test_an_e164_number_needs_no_region() -> None:
    assert resolved("+442071838750").e164 == "+442071838750"


def test_the_international_prefix_becomes_a_plus() -> None:
    assert resolved("00442071838750").e164 == "+442071838750"


@pytest.mark.parametrize(
    ("raw", "region", "expected"),
    [
        ("6505551212", "US", "+16505551212"),
        ("416 555 0142", "CA", "+14165550142"),
        ("020 7183 8750", "GB", "+442071838750"),
        ("02 9374 4000", "AU", "+61293744000"),
        ("21 3030 4040", "BR", "+552130304040"),
        ("030 12345678", "DE", "+493012345678"),
    ],
)
def test_a_national_number_resolves_through_the_account_region(
    raw: str, region: str, expected: str
) -> None:
    assert resolved(raw, region=region).e164 == expected


def test_a_trunk_zero_is_dropped_where_the_plan_carries_one() -> None:
    assert resolved("020 7183 8750", region="GB").e164 == "+442071838750"


def test_the_brazilian_mobile_nine_is_handled_by_name() -> None:
    """Eleven digits in a plan listed at ten. Named explicitly rather than
    absorbed by a length heuristic, because a heuristic that accepts eleven
    digits everywhere accepts wrong numbers everywhere."""
    assert resolved("21 99999 8888", region="BR").e164 == "+5521999998888"


def test_a_number_already_carrying_its_country_code_is_not_doubled() -> None:
    assert resolved("16505551212", region="US").e164 == "+16505551212"


def test_a_bare_number_with_no_region_is_refused_not_guessed() -> None:
    """The anchor of this file. Ten digits are a real subscriber in several
    countries, and the wrong guess hashes a stranger."""
    result = normalise_phone("6505551212")
    assert isinstance(result, PhoneNeedsReview)
    assert "guessing the country" in result.reason


def test_the_refusal_is_a_value_and_not_an_exception() -> None:
    """A deal with a good email and an unparseable phone is still a deal that
    should be attributed, so the refusal has to be something the caller can
    route rather than something that aborts the conversion."""
    result = normalise_phone("not a number", default_region="US")
    assert isinstance(result, PhoneNeedsReview)
    assert result.raw == "not a number"


def test_a_region_outside_the_table_is_refused_with_the_region_named() -> None:
    result = normalise_phone("912345678", default_region="PT")
    assert isinstance(result, PhoneNeedsReview)
    assert "'PT'" in result.reason
    assert "rather than guessing" in result.reason


def test_a_digit_count_the_plan_does_not_admit_is_refused() -> None:
    result = normalise_phone("650555", default_region="US")
    assert isinstance(result, PhoneNeedsReview)
    assert "numbering plan" in result.reason


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_an_empty_number_is_refused(raw: str) -> None:
    result = normalise_phone(raw, default_region="US")
    assert isinstance(result, PhoneNeedsReview)
    assert "empty" in result.reason


def test_a_plus_with_no_digits_is_refused() -> None:
    result = normalise_phone("+", default_region="US")
    assert isinstance(result, PhoneNeedsReview)
    assert "no digits" in result.reason


def test_no_country_calling_code_starts_with_zero() -> None:
    result = normalise_phone("+06505551212")
    assert isinstance(result, PhoneNeedsReview)
    assert "starts with 0" in result.reason


@pytest.mark.parametrize("digits", ["+1234567", "+1234567890123456"])
def test_e164_admits_eight_to_fifteen_digits(digits: str) -> None:
    result = normalise_phone(digits)
    assert isinstance(result, PhoneNeedsReview)
    assert "E.164 admits 8 to 15" in result.reason


def test_a_letter_inside_a_number_is_refused_with_the_code_point_named() -> None:
    result = normalise_phone("650-555-121X", default_region="US")
    assert isinstance(result, PhoneNeedsReview)
    assert "U+0058" in result.reason


def test_an_extension_marker_is_refused_rather_than_truncated() -> None:
    """``x1234`` is common in CRM data and there is no documented way to carry
    it. Truncating to the main number would be a guess that the extension does
    not identify a different person, which in a shared office is wrong."""
    result = normalise_phone("650-555-1212 x77", default_region="US")
    assert isinstance(result, PhoneNeedsReview)


def test_a_placeholder_phone_does_not_become_a_number() -> None:
    result = normalise_phone("N/A", default_region="US")
    assert isinstance(result, PhoneNeedsReview)


def test_two_strangers_with_the_same_unparseable_phone_stay_apart() -> None:
    """Both refusals carry their own raw input, so a review queue shows two
    rows and never one merged record."""
    first = normalise_phone("N/A", default_region="US")
    second = normalise_phone("n/a", default_region="US")
    assert isinstance(first, PhoneNeedsReview)
    assert isinstance(second, PhoneNeedsReview)
    assert first.raw != second.raw


def test_the_region_argument_is_case_insensitive() -> None:
    assert resolved("6505551212", region="us").e164 == "+16505551212"
