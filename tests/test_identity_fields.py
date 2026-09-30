"""The rest of the customer fields, and the second documented divergence."""

from __future__ import annotations

import pytest

from preflight.identity import (
    InvalidIdentifier,
    normalise_country_meta,
    normalise_name_google,
    normalise_name_meta,
    normalise_postal_code_google,
    normalise_region_code_google,
    normalise_state_meta,
    sha256_digest,
    us_zip_five,
)

META_NAME_VECTORS = [
    ("Mary", "mary", "6915771be1c5aa0c886870b6951b03d7eafc121fea0e80a5ea83beb7c449f4ec"),
    ("정", "정", "8fa8cd9c440be61d0151429310034083132b35975c4bea67fdd74158eb51db14"),
    (
        "Valéry",
        "valéry",
        "08e1996b5dd49e62a4b4c010d44e4345592a863bb9f8e3976219bac29417149c",
    ),
]
"""Three worked examples from Meta's reference, with the hashes it publishes.

The last two are the ones that matter: an implementation that strips
non-ASCII characters "to be safe" produces a different hash for both and
loses every non-English customer in the account.
"""

META_COUNTRY_VECTOR = (
    "US",
    "us",
    "79adb2a2fce5c6ba215fe5f27f532d4e7edbac4b6a5e09e1ef3a08084a904621",
)
"""Meta's reference gives the United States as the input, ``us`` as the
standardised form, and this SHA-256 as the expected output."""


@pytest.mark.parametrize(("raw", "normalised", "expected"), META_NAME_VECTORS)
def test_the_meta_name_vectors_reproduce_their_published_hashes(
    raw: str, normalised: str, expected: str
) -> None:
    assert normalise_name_meta(raw) == normalised
    assert sha256_digest(normalise_name_meta(raw)) == expected


def test_the_meta_country_vector_reproduces_its_published_hash() -> None:
    raw, normalised, expected = META_COUNTRY_VECTOR
    assert normalise_country_meta(raw) == normalised
    assert sha256_digest(normalise_country_meta(raw)) == expected


def test_a_hyphenated_family_name_diverges_between_the_two_destinations() -> None:
    """The second documented divergence, and a quieter one than the email.

    Google's formatting guide asks for lowercase and a trim on ``familyName``
    and says nothing about punctuation. Meta's reference asks for "lowercase,
    no punctuation". So Smith-Jones is two different hashes, and both are
    right.
    """
    raw = "Smith-Jones"
    assert normalise_name_google(raw) == "smith-jones"
    assert normalise_name_meta(raw) == "smithjones"
    assert sha256_digest(normalise_name_google(raw)) != sha256_digest(
        normalise_name_meta(raw)
    )


def test_an_unpunctuated_name_agrees_between_the_two() -> None:
    assert normalise_name_google("Whitfield") == normalise_name_meta("Whitfield")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("  Dana  ", "dana"), ("DANA", "dana"), ("Dana", "dana")],
)
def test_google_names_are_lowercased_and_trimmed(raw: str, expected: str) -> None:
    assert normalise_name_google(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("O'Brien", "obrien"),
        ("de la Cruz", "delacruz"),
        ("St. John", "stjohn"),
        ("Anne-Marie", "annemarie"),
    ],
)
def test_meta_names_lose_punctuation_and_spaces(raw: str, expected: str) -> None:
    assert normalise_name_meta(raw) == expected


def test_an_accent_survives_the_meta_rules() -> None:
    assert normalise_name_meta("José") == "josé"


def test_a_name_that_is_only_punctuation_is_refused() -> None:
    with pytest.raises(InvalidIdentifier, match="empty after removing punctuation"):
        normalise_name_meta("---")


def test_an_empty_google_name_is_refused() -> None:
    with pytest.raises(InvalidIdentifier, match="empty after trimming"):
        normalise_name_google("   ")


def test_the_field_name_travels_into_the_refusal() -> None:
    with pytest.raises(InvalidIdentifier, match="family name"):
        normalise_name_google("  ", field="family name")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("New York", "newyork"), ("SÃO PAULO", "sãopaulo"), ("london", "london")],
)
def test_city_follows_the_meta_name_rules(raw: str, expected: str) -> None:
    assert normalise_name_meta(raw, field="city") == expected


@pytest.mark.parametrize(("raw", "expected"), [("CA", "ca"), ("AZ", "az"), (" mn ", "mn")])
def test_state_is_lowercased(raw: str, expected: str) -> None:
    assert normalise_state_meta(raw) == expected


def test_a_full_state_name_is_not_translated_into_an_abbreviation() -> None:
    """Meta's reference asks for the two-character code and supplies no
    translation table. Inventing one is how a customer in Minnesota gets
    hashed as living somewhere else."""
    assert normalise_state_meta("Minnesota") == "minnesota"


def test_the_us_zip_rule_takes_the_first_five() -> None:
    assert us_zip_five("55102-1234") == "55102"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("94035", "94035"), ("94035-1234", "94035"), (" 94035 ", "94035")],
)
def test_us_zip_normalisation(raw: str, expected: str) -> None:
    assert us_zip_five(raw) == expected


def test_a_uk_postcode_keeps_its_shape_under_the_meta_rules() -> None:
    """The reference's own example for the UK is ``m11ae``: lowercase, no
    space. Truncating it to five characters would be applying the US rule to
    a country it was never written for."""
    from preflight.identity import normalise_zip_meta

    assert normalise_zip_meta("M1 1AE") == "m11ae"


def test_google_does_not_truncate_a_postal_code() -> None:
    """The Data Manager API does not hash ``postalCode`` at all and explicitly
    permits the four-digit extension, noting it may improve the match rate.
    Two destinations, two correct answers for the same field."""
    assert normalise_postal_code_google("55102-1234") == "55102-1234"
    assert us_zip_five("55102-1234") != normalise_postal_code_google("55102-1234")


def test_an_empty_postal_code_is_refused_by_both() -> None:
    from preflight.identity import normalise_zip_meta

    with pytest.raises(InvalidIdentifier):
        normalise_zip_meta("  ")
    with pytest.raises(InvalidIdentifier):
        normalise_postal_code_google("  ")


def test_google_region_code_is_uppercase_and_unhashed() -> None:
    """``regionCode`` sits in the middle of a block of hashed fields and is
    one of the two the guide lists under "don't hash"."""
    assert normalise_region_code_google("us") == "US"


@pytest.mark.parametrize("raw", ["USA", "U", "12", "united states"])
def test_a_region_code_that_is_not_two_letters_is_refused(raw: str) -> None:
    with pytest.raises(InvalidIdentifier, match="alpha-2"):
        normalise_region_code_google(raw)


@pytest.mark.parametrize("raw", ["USA", "United States", "u", "1S"])
def test_a_country_that_is_not_two_letters_is_refused_not_truncated(raw: str) -> None:
    """Truncating ``USA`` to ``US`` happens to be right. Truncating
    ``AUSTRIA`` to ``AU`` is the same guess being wrong, and nothing
    downstream could tell the two apart."""
    with pytest.raises(InvalidIdentifier, match="alpha-2"):
        normalise_country_meta(raw)


def test_country_and_region_code_differ_only_in_case() -> None:
    assert normalise_country_meta("US") == normalise_region_code_google("US").lower()
