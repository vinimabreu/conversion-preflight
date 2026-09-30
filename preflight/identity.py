# Vendored from github.com/vinimabreu/revenue-loop, src/revenue_loop/identity.py
# at commit 265d1c9 (file last changed in f03e121). Kept byte-identical below this
# header; the upstream tests run here with only their import line changed.

"""Normalisation and hashing, per destination, with the divergences kept apart.

A hashed identifier either matches the one the platform computed or it does
not, and a mismatch is silent: the upload succeeds, the conversion lands, and
it is simply never attributed. Google says so in as many words in its own
guidance, warning that skipping the domain-specific email rules "will result
in different hash values than Google expects for these domains, leading to
missed matches". Nothing raises. Nothing is logged. The campaign just looks
worse than it is.

So this module refuses the one shortcut everybody takes, which is a single
``normalise_email`` shared by both destinations. The two documented
specifications genuinely differ:

- **Email.** The Data Manager API's formatting guide requires, for
  ``gmail.com`` and ``googlemail.com`` addresses only, removing every dot
  before the ``@`` and the ``+`` together with everything after it, and its
  worked example is ``cloudy.sanfrancisco+shopping@gmail.com`` becoming
  ``cloudysanfrancisco@gmail.com``. Meta's customer-information reference
  asks for whitespace removal and lowercasing, and nothing else; its own
  worked example keeps the underscore in ``john_smith@gmail.com``. The same
  raw address therefore produces two different SHA-256 values, and both are
  correct for their own destination.
- **Names.** Google asks for lowercase and a trim and says nothing about
  punctuation, so a hyphenated family name keeps its hyphen. Meta asks for
  "lowercase, no punctuation", so the same name loses it.
- **Phone.** Google documents E.164, which carries the leading ``+``. Meta
  documents digits only, with the country code and without leading zeros.

Where the documentation is silent, this module says so instead of implying
precision. The largest such silence is which Unicode case operation
"lowercase" means. ``str.lower`` and ``str.casefold`` disagree on real
inputs: ``casefold`` maps U+00DF SHARP S to ``ss``, which is a
transliteration rather than a lowercasing, and would hash ``straße`` and
``strasse`` identically. Since both platforms write "convert to lowercase",
this module uses ``str.lower`` and pins that choice with tests, so a future
interpreter or a well-meaning refactor cannot change every hash in the system
without a red suite.

The other silence is handled by refusing. An identifier carrying an invisible
character or an exotic whitespace code point is a paste accident or an
encoding bug; neither platform documents what it does with one, and a
character that prints as nothing cannot be reasoned about in a review queue.
:class:`InvalidIdentifier` names the code point rather than printing the
character, because printing it shows nothing.
"""

from __future__ import annotations

import base64
import hashlib
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

ASCII_WHITESPACE = " \t\n\r\v\f"
"""The whitespace this module trims without complaint.

``str.strip()`` with no argument removes every Unicode whitespace character,
including U+00A0 NO-BREAK SPACE and U+3000 IDEOGRAPHIC SPACE. Silently
dropping those would produce a hash for an address that was never really
typed, so anything outside this set is a loud :class:`InvalidIdentifier`
instead.
"""

GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
"""The two domains whose local part Google normalises further.

Named from the Data Manager API formatting guide, which applies the dot and
plus-suffix rules to these domains and states plainly that addresses on any
other domain must keep both.
"""


class HashEncoding(StrEnum):
    """How the SHA-256 bytes are rendered, mirroring the API's own enum.

    The Data Manager API takes an ``encoding`` field on the request with
    exactly these two values and notes that hex case is insignificant while
    Base64 case is significant. Meta's published payloads use lowercase hex.
    """

    HEX = "HEX"
    BASE64 = "BASE64"


class InvalidIdentifier(ValueError):
    """The value cannot be normalised into something worth hashing.

    Raised rather than returned because the caller has a real choice to make
    (drop the identifier, or fix the source) and an empty string would make
    that choice invisibly.
    """


def _reject_exotic_characters(value: str, *, field: str) -> None:
    for char in value:
        if char in ASCII_WHITESPACE:
            continue
        if char.isspace() or unicodedata.category(char) in {"Cc", "Cf", "Co", "Cs"}:
            raise InvalidIdentifier(
                f"{field} contains U+{ord(char):04X}, an invisible or non-ASCII "
                "whitespace character; neither destination documents what it "
                "does with one, and hashing it would produce a value that "
                "silently never matches"
            )


def _lowercase(value: str) -> str:
    """The documented "convert to lowercase", pinned to ``str.lower``.

    See the module docstring for why this is not ``str.casefold``.
    """
    return value.lower()


def _strip_punctuation_and_symbols(value: str) -> str:
    """Drop Unicode punctuation, symbols and whitespace, keep letters and digits.

    This is the reading of Meta's "no punctuation, special characters, or
    spaces" instruction. Letters, marks and digits survive, which is what
    keeps the documented Korean and accented examples intact.
    """
    return "".join(
        char
        for char in value
        if not unicodedata.category(char).startswith(("P", "S", "Z"))
        and not char.isspace()
    )


def sha256_digest(value: str, *, encoding: HashEncoding = HashEncoding.HEX) -> str:
    """Hash an already normalised value.

    Deliberately takes a plain string and does no normalising of its own. A
    hash function that quietly normalises is a hash function that can be
    called with the wrong dialect and still look like it worked; here the
    caller has to have picked a dialect before it gets this far.
    """
    raw = hashlib.sha256(value.encode("utf-8")).digest()
    if encoding is HashEncoding.BASE64:
        return base64.b64encode(raw).decode("ascii")
    return raw.hex()


def _split_email(value: str, *, field: str) -> tuple[str, str]:
    _reject_exotic_characters(value, field=field)
    trimmed = value.strip(ASCII_WHITESPACE)
    if trimmed.count("@") != 1:
        raise InvalidIdentifier(
            f"{field} must contain exactly one @; got {trimmed.count('@')}"
        )
    local, domain = trimmed.split("@")
    if not local:
        raise InvalidIdentifier(f"{field} has an empty local part before the @")
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise InvalidIdentifier(f"{field} domain {domain!r} is not a plausible mail domain")
    return local, domain


def normalise_email_google(value: str) -> str:
    """The Data Manager API's documented email normalisation.

    Lowercase, whitespace removed everywhere rather than only at the ends
    (the guide says "trim leading, trailing and intermediate whitespace"),
    and then, for ``gmail.com`` and ``googlemail.com`` only, every dot in the
    local part removed along with the ``+`` and everything after it.

    The worked example from the guide survives as a test:
    ``cloudy.sanfrancisco+shopping@gmail.com`` becomes
    ``cloudysanfrancisco@gmail.com``, while ``user.name+NYC@Example.com``
    becomes ``user.name+nyc@example.com`` with both the dot and the plus
    intact, because it is not a Google-operated domain.
    """
    local, domain = _split_email(value, field="email")
    local = "".join(ch for ch in local if ch not in ASCII_WHITESPACE)
    domain = "".join(ch for ch in domain if ch not in ASCII_WHITESPACE)
    local = _lowercase(local)
    domain = _lowercase(domain)
    if domain in GMAIL_DOMAINS:
        local = local.split("+", 1)[0].replace(".", "")
        if not local:
            raise InvalidIdentifier(
                "the Google domain rules empty this local part; there is no "
                "address left to hash"
            )
    return f"{local}@{domain}"


def normalise_email_meta(value: str) -> str:
    """Meta's documented email normalisation: remove whitespace, lowercase.

    Nothing else. The customer-information reference gives exactly those two
    instructions and its worked example, ``John_Smith@gmail.com`` becoming
    ``john_smith@gmail.com``, shows a Google-operated domain keeping a local
    part that the Google rules would have altered. Adding Google's dot and
    plus handling here would be a plausible-looking guess that produces a
    hash Meta never computes.
    """
    local, domain = _split_email(value, field="email")
    joined = "".join(ch for ch in f"{local}@{domain}" if ch not in ASCII_WHITESPACE)
    return _lowercase(joined)


@dataclass(frozen=True)
class NormalisedPhone:
    """A phone number the rules fully determined.

    Holds the E.164 form once, and renders the per-destination spellings from
    it, so the two destinations can never end up disagreeing about which
    country a number belongs to.
    """

    e164: str

    def for_google(self) -> str:
        """E.164 with the leading ``+``, as the formatting guide requires."""
        return self.e164

    def for_meta(self) -> str:
        """Digits only, country code included, as the reference requires."""
        return self.e164[1:]


@dataclass(frozen=True)
class PhoneNeedsReview:
    """A phone number the rules refuse to guess about.

    A value, not an exception, because the correct handling is to route it to
    a human queue and upload the conversion on its other identifiers, not to
    abort the conversion. Carries the raw input and the named reason so the
    queue can show a person exactly what arrived.
    """

    raw: str
    reason: str


PhoneResult = NormalisedPhone | PhoneNeedsReview

_DIGITS = frozenset("0123456789")
_PHONE_FORMATTING = frozenset(" ()-./")

_REGION_PLANS: dict[str, tuple[str, int, bool]] = {
    "US": ("1", 10, False),
    "CA": ("1", 10, False),
    "GB": ("44", 10, True),
    "AU": ("61", 9, True),
    "BR": ("55", 10, False),
    "DE": ("49", 10, True),
}
"""National numbering plans this package resolves without a country code.

Region code to (country calling code, national significant digits, whether
the national written form carries a trunk 0 that E.164 drops). The table is
short on purpose: a region that is not in it produces a refusal naming the
region, which is a two-line change for whoever needs it, rather than a
country code invented from the shape of the digits. Brazil is listed at its
ten-digit landline length; the eleven-digit mobile form with the extra 9 is
handled by name below.
"""


def normalise_phone(value: str, *, default_region: str | None = None) -> PhoneResult:
    """Return the E.164 form of ``value``, or an explicit refusal.

    Applied in order, and every step is deterministic:

    - Presentation characters (spaces, dashes, dots, slashes, parentheses)
      are dropped. They carry formatting, not identity.
    - A leading ``+`` followed by 8 to 15 digits is E.164 already.
    - A leading ``00`` is the international call prefix and becomes ``+``.
    - A bare national number resolves only through ``default_region`` and the
      plan table above.

    Anything else is a :class:`PhoneNeedsReview` with the reason named.
    Guessing the country is the specific failure this refuses: the same ten
    digits are a real subscriber in several countries, and the wrong guess
    hashes to a stranger, which at best never matches and at worst attributes
    a sale to whoever that stranger's clicks belong to.
    """
    trimmed = value.strip(ASCII_WHITESPACE)
    if not trimmed:
        return PhoneNeedsReview(raw=value, reason="empty after trimming whitespace")

    plus = trimmed.startswith("+")
    body = trimmed[1:] if plus else trimmed
    digits: list[str] = []
    for char in body:
        if char in _DIGITS:
            digits.append(char)
        elif char in _PHONE_FORMATTING:
            continue
        else:
            return PhoneNeedsReview(
                raw=value,
                reason=f"contains U+{ord(char):04X}, which is neither a digit nor "
                "phone formatting",
            )
    number = "".join(digits)

    if not plus and number.startswith("00"):
        plus = True
        number = number[2:]

    if plus:
        if not number:
            return PhoneNeedsReview(raw=value, reason="a + with no digits after it")
        if number.startswith("0"):
            return PhoneNeedsReview(
                raw=value, reason="no country calling code starts with 0"
            )
        if not 8 <= len(number) <= 15:
            return PhoneNeedsReview(
                raw=value,
                reason=f"{len(number)} digits after the +; E.164 admits 8 to 15",
            )
        return NormalisedPhone(e164=f"+{number}")

    if default_region is None:
        return PhoneNeedsReview(
            raw=value,
            reason="no country code on the number and no default region on the "
            "account; guessing the country would hash a stranger",
        )
    plan = _REGION_PLANS.get(default_region.upper())
    if plan is None:
        return PhoneNeedsReview(
            raw=value,
            reason=f"default region {default_region!r} has no numbering plan in "
            "this package; add it explicitly rather than guessing",
        )
    country_code, national_len, trunk_zero = plan

    if trunk_zero and number.startswith("0") and len(number) == national_len + 1:
        number = number[1:]
    if default_region.upper() == "BR" and len(number) == 11 and number[2] == "9":
        return NormalisedPhone(e164=f"+{country_code}{number}")
    if len(number) == national_len:
        return NormalisedPhone(e164=f"+{country_code}{number}")
    if len(number) == national_len + len(country_code) and number.startswith(country_code):
        return NormalisedPhone(e164=f"+{number}")
    return PhoneNeedsReview(
        raw=value,
        reason=f"{len(number)} digits does not fit the {default_region.upper()} "
        f"numbering plan ({national_len} national digits)",
    )


def normalise_name_google(value: str, *, field: str = "name") -> str:
    """Lowercase and trim, exactly as the formatting guide states.

    No punctuation stripping, because the guide does not ask for any. A
    hyphenated family name keeps its hyphen here and loses it in
    :func:`normalise_name_meta`, and the pair of tests covering that is the
    shortest proof in the repository that one shared normaliser would be
    wrong for at least one destination.
    """
    _reject_exotic_characters(value, field=field)
    trimmed = value.strip(ASCII_WHITESPACE)
    if not trimmed:
        raise InvalidIdentifier(f"{field} is empty after trimming")
    return _lowercase(trimmed)


def normalise_name_meta(value: str, *, field: str = "name") -> str:
    """Lowercase, no punctuation, as the customer-information reference asks.

    The reference's own examples pin the edges this keeps: the Korean
    single-character given name and the accented ``Valéry`` both survive
    unchanged apart from case, because the rule removes punctuation and
    symbols, not non-ASCII letters.
    """
    _reject_exotic_characters(value, field=field)
    trimmed = _strip_punctuation_and_symbols(value.strip(ASCII_WHITESPACE))
    if not trimmed:
        raise InvalidIdentifier(
            f"{field} is empty after removing punctuation and whitespace"
        )
    return _lowercase(trimmed)


def normalise_city_meta(value: str) -> str:
    """Lowercase, no punctuation, no spaces: ``newyork``, per the reference."""
    return normalise_name_meta(value, field="city")


def normalise_state_meta(value: str) -> str:
    """Two-character lowercase state code for the US, lowercase otherwise.

    The reference asks for the two-character ANSI abbreviation in lowercase
    for US states and for non-US states to be "standardised in lowercase"
    with no punctuation or spaces. This normalises the form without
    translating a full state name into an abbreviation, because a translation
    table that is wrong for one entry hashes a state the customer never lived
    in, and the reference supplies no such table.
    """
    return normalise_name_meta(value, field="state")


def normalise_zip_meta(value: str) -> str:
    """Lowercase, no spaces or dashes, and the first five digits for the US.

    The five-digit rule applies only when a region code says the address is
    in the US, which is why the region is a parameter of the caller rather
    than something guessed from the shape of the string here. This function
    performs the case and separator normalisation; :func:`us_zip_five` does
    the truncation, so a call site that truncates a UK postcode has to say so
    out loud.
    """
    _reject_exotic_characters(value, field="postal code")
    trimmed = "".join(
        ch
        for ch in value.strip(ASCII_WHITESPACE)
        if ch not in {" ", "-"} and ch not in ASCII_WHITESPACE
    )
    if not trimmed:
        raise InvalidIdentifier("postal code is empty after normalising")
    return _lowercase(trimmed)


def us_zip_five(value: str) -> str:
    """The first five characters of a normalised US ZIP, per the reference.

    Meta documents "only the first 5 digits" for US postal codes. Google's
    ``postalCode`` is not hashed at all and explicitly permits the ZIP+4
    extension, noting it may improve the match rate. Two destinations, two
    correct answers, so the truncation lives in its own named function
    instead of inside a shared normaliser.
    """
    normalised = normalise_zip_meta(value)
    return normalised[:5]


def normalise_country_meta(value: str) -> str:
    """ISO 3166-1 alpha-2, lowercase, as the reference documents.

    The reference's worked example is the United States becoming ``us`` with
    a published SHA-256, which this package carries as a test vector. A value
    that is not two letters is refused rather than truncated, because
    truncating ``USA`` to ``US`` is a guess that happens to be right and
    truncating ``AUSTRIA`` to ``AU`` is the same guess being wrong.
    """
    _reject_exotic_characters(value, field="country")
    trimmed = value.strip(ASCII_WHITESPACE)
    if len(trimmed) != 2 or not trimmed.isascii() or not trimmed.isalpha():
        raise InvalidIdentifier(
            f"country must be a two-letter ISO 3166-1 alpha-2 code; got {value!r}"
        )
    return _lowercase(trimmed)


def normalise_region_code_google(value: str) -> str:
    """The Data Manager API's ``regionCode``: two letters, and never hashed.

    The formatting guide lists ``regionCode`` and ``postalCode`` under "don't
    hash", which is easy to miss when every neighbouring field is hashed.
    Uppercase is the ISO 3166-1 alpha-2 canonical form and is what the
    guide's own examples show for this field.
    """
    _reject_exotic_characters(value, field="region code")
    trimmed = value.strip(ASCII_WHITESPACE)
    if len(trimmed) != 2 or not trimmed.isascii() or not trimmed.isalpha():
        raise InvalidIdentifier(
            f"region code must be a two-letter ISO 3166-1 alpha-2 code; got {value!r}"
        )
    return trimmed.upper()


def normalise_postal_code_google(value: str) -> str:
    """The Data Manager API's ``postalCode``: trimmed, and never hashed.

    The guide permits both five digits and ZIP+4 for US addresses and asks
    for no extension outside the US, so nothing is truncated here.
    """
    _reject_exotic_characters(value, field="postal code")
    trimmed = value.strip(ASCII_WHITESPACE)
    if not trimmed:
        raise InvalidIdentifier("postal code is empty after trimming")
    return trimmed
