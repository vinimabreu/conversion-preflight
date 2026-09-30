"""The implementation's rules, stated next to the documentation they were written against.

Every entry answers three questions about one (platform, field) pair:

- what the code does, in plain words (``implementation``);
- what the platform documentation said when the code was written, verbatim
  (``doc_quote``, with the retrieval date in ``source``);
- which Knowledge Base entry should say the same thing today (``kb_entry``).

The agent compares the three. When the Knowledge Base entry, rebuilt from the
live documentation, stops agreeing with ``doc_quote``, the documentation moved
or the entry lost a detail; when ``implementation`` does not match either, the
code is the thing to look at. Known differences are declared in
``divergences`` so they are reported as decisions, not rediscovered as bugs.

``doc_examples`` are the platforms' own worked examples, with the published
SHA-256 where there is one. The test suite runs every example through the code
and fails unless the output matches or the input is named in a divergence.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from . import identity as ident

GOOGLE_SOURCE = (
    "https://developers.google.com/data-manager/api/devguides/concepts/formatting "
    "(English page, 'Last updated 2026-09-24 UTC', retrieved 2026-09-30)"
)
META_SOURCE = (
    "https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/"
    "customer-information-parameters (retrieved 2026-09-30)"
)
GOOGLE_KB = "normalization_and_hashing/google"
META_KB = "normalization_and_hashing/meta"

FIELDS = (
    "email",
    "phone",
    "first_name",
    "last_name",
    "city",
    "state",
    "postal_code",
    "country",
)
PLATFORMS = ("google", "meta")



@dataclass(frozen=True)
class NeedsReview:
    """A value the rules will not guess about. Returned, not raised: the caller
    routes it to a person and uploads the conversion on its other identifiers."""

    raw: str
    reason: str


Normaliser = Callable[[str, str | None], "str | NeedsReview"]


@dataclass(frozen=True)
class DocExample:
    """A worked example copied from the platform page, never invented."""

    input: str
    normalized: str
    sha256: str | None = None
    region: str | None = None
    diverges: bool = False
    """True when the code deliberately does not reproduce this example; the rule's divergences say why."""


@dataclass(frozen=True)
class Rule:
    platform: str
    field: str
    param: str
    hashed: bool
    implementation: str
    doc_quote: str
    source: str
    kb_entry: str
    normalise: Normaliser | None = None
    doc_examples: tuple[DocExample, ...] = ()
    divergences: tuple[str, ...] = field(default=())

    @property
    def implemented(self) -> bool:
        return self.normalise is not None

    def describe(self) -> dict[str, object]:
        """The rule as the agent sees it: everything except the callable."""
        return {
            "platform": self.platform,
            "field": self.field,
            "param": self.param,
            "hashed": self.hashed,
            "implemented": self.implemented,
            "implementation": self.implementation,
            "doc_quote": self.doc_quote,
            "source": self.source,
            "kb_entry": self.kb_entry,
            "doc_examples": [
                {k: v for k, v in vars(ex).items() if v not in (None, False)}
                for ex in self.doc_examples
            ],
            "divergences": list(self.divergences),
        }


# Country calling codes whose national significant number never starts with 0,
# so "+44 0..." is a trunk zero written into an international number, not a
# digit of it. Deliberately limited to the plans the package resolves; Italy,
# for one, keeps a leading 0 in E.164, so this cannot be a general rule.
_NO_LEADING_ZERO_AFTER = ("44", "49", "55", "61")
_ZIP_PLUS_FOUR = re.compile(r"^[0-9]{5}[- ]?[0-9]{4}$")


def _phone(value: str, region: str | None) -> ident.NormalisedPhone | NeedsReview:
    if "(0)" in value.replace(" ", ""):
        return NeedsReview(value, "the '(0)' notation marks a national trunk zero inside an "
                           "international number; write the number without it at the source")
    result = ident.normalise_phone(value, default_region=region)
    if isinstance(result, ident.PhoneNeedsReview):
        return NeedsReview(result.raw, result.reason)
    for code in _NO_LEADING_ZERO_AFTER:
        if result.e164.startswith(f"+{code}0"):
            return NeedsReview(value, f"+{code} numbers never continue with 0; the 0 is the "
                               "national trunk prefix and has to be dropped at the source")
    return result


def _phone_google(value: str, region: str | None) -> str | NeedsReview:
    result = _phone(value, region)
    return result.for_google() if isinstance(result, ident.NormalisedPhone) else result


def _phone_meta(value: str, region: str | None) -> str | NeedsReview:
    result = _phone(value, region)
    return result.for_meta() if isinstance(result, ident.NormalisedPhone) else result


def _zip_meta(value: str, region: str | None) -> str | NeedsReview:
    if region is not None and region.strip().upper() == "US":
        return ident.us_zip_five(value)
    if region is None and _ZIP_PLUS_FOUR.match(value.strip(ident.ASCII_WHITESPACE)):
        return NeedsReview(value, "this looks like a US ZIP+4, and Meta hashes only the first "
                           "five digits for US addresses; the record has no country and "
                           "there is no default_region to say whether it is in the US")
    return ident.normalise_zip_meta(value)


_INVISIBLE = (
    "Refuses invisible characters and non-ASCII whitespace (for example U+00A0, "
    "U+200B) with the code point named, instead of hashing them."
)
_PHONE_PARSE = (
    "Drops spaces, parentheses, dashes, dots and slashes. A leading '+' or the "
    "international prefix '00' followed by 8 to 15 digits is taken as E.164; a "
    "country code starting with 0 is refused. A number without a country code "
    "resolves only through the region (the record's own two-letter country when "
    "it has one, else default_region), and only for US, CA, GB, AU, BR and DE; "
    "for GB, AU and DE the national trunk '0' is dropped. A trunk zero written "
    "inside an international number ('+44 (0)20...', '+49 030...') is refused. "
    "Anything else, and any letter, is returned as needs_review with the reason, "
    "never guessed."
)

RULES: tuple[Rule, ...] = (
    Rule(
        platform="google",
        field="email",
        param="email_address",
        hashed=True,
        implementation=(
            f"{_INVISIBLE} Requires exactly one '@' and a dotted domain. Removes "
            "ASCII whitespace anywhere in the address, lowercases with str.lower, "
            "and for gmail.com and googlemail.com only removes every '.' in the "
            "local part and the '+' with everything after it."
        ),
        doc_quote=(
            "Convert to lowercase. If the email address has the gmail.com or "
            "googlemail.com domain: Remove all dots (.) before the @ symbol. Remove "
            "the plus sign (+) from the local-part and remove all characters that "
            "follow it. [...] If the email address has a domain other than gmail.com "
            "or googlemail.com, don't remove dots or plus signs. Whitespace: Trim "
            "leading, trailing and intermediate whitespace. Hashing: Hash using the "
            "SHA-256 algorithm. Encode the hash bytes using hex or Base64 encoding."
        ),
        source=GOOGLE_SOURCE,
        kb_entry=GOOGLE_KB,
        normalise=lambda v, _r: ident.normalise_email_google(v),
        doc_examples=(
            DocExample("cloudy.sanfrancisco+shopping@gmail.com", "cloudysanfrancisco@gmail.com"),
            DocExample("user.name+NYC@Example.com", "user.name+nyc@example.com"),
        ),
    ),
    Rule(
        platform="google",
        field="phone",
        param="phone_number",
        hashed=True,
        implementation=f"{_PHONE_PARSE} Output is E.164 with the leading '+'.",
        doc_quote=(
            "Use E.164 format. Include the plus sign (+) and the country code. All "
            "characters after the plus sign must be digits. For example, the US phone "
            "number (800)555-0100 should be formatted and normalized to +18005550100. "
            "Whitespace: Trim leading and trailing whitespace. Hashing: Hash using the "
            "SHA-256 algorithm."
        ),
        source=GOOGLE_SOURCE,
        kb_entry=GOOGLE_KB,
        normalise=_phone_google,
        doc_examples=(DocExample("(800)555-0100", "+18005550100", region="US"),),
        divergences=(
            "Letters are refused (needs_review) instead of stripped. This page says "
            "only that every character after the plus sign must be digits; the "
            "Google Ads page's samples strip all non-digits, which can fuse an "
            "extension into the number.",
            "Fewer than 8 digits after the '+' is refused. E.164 has a few 7-digit "
            "numbers (small territories) that the Google Ads sample pattern "
            "+[1-9]\\d{6,14} accepts; this code does not.",
        ),
    ),
    Rule(
        platform="google",
        field="first_name",
        param="given_name",
        hashed=True,
        implementation=(
            f"{_INVISIBLE} Trims ASCII whitespace at both ends and lowercases. Keeps "
            "punctuation. Does not remove prefixes such as 'Mrs.': the caller must."
        ),
        doc_quote=(
            "Convert to lowercase. Don't include prefixes such as Mrs. Whitespace: "
            "Trim leading and trailing whitespace. Hashing: Hash using the SHA-256 "
            "algorithm."
        ),
        source=GOOGLE_SOURCE,
        kb_entry=GOOGLE_KB,
        normalise=lambda v, _r: ident.normalise_name_google(v, field="given_name"),
        divergences=(
            "Titles and suffixes ('Mrs.', 'Jr.') are not removed, because removing "
            "them needs a list of words, and a wrong entry in that list changes a real "
            "name. preflight_file warns when it sees a common one; the source system "
            "has to split it out.",
        ),
    ),
    Rule(
        platform="google",
        field="last_name",
        param="family_name",
        hashed=True,
        implementation=(
            f"{_INVISIBLE} Trims ASCII whitespace at both ends and lowercases. Keeps "
            "punctuation, so a hyphenated name keeps its hyphen. Does not remove "
            "suffixes such as 'Jr.': the caller must."
        ),
        doc_quote=(
            "Convert to lowercase. Don't include suffixes such as Jr. Whitespace: "
            "Trim leading and trailing whitespace. Hashing: Hash using the SHA-256 "
            "algorithm."
        ),
        source=GOOGLE_SOURCE,
        kb_entry=GOOGLE_KB,
        normalise=lambda v, _r: ident.normalise_name_google(v, field="family_name"),
        divergences=(
            "Titles and suffixes ('Mrs.', 'Jr.') are not removed, because removing "
            "them needs a list of words, and a wrong entry in that list changes a real "
            "name. preflight_file warns when it sees a common one; the source system "
            "has to split it out.",
        ),
    ),
    Rule(
        platform="google",
        field="city",
        param="city",
        hashed=False,
        implementation="Not implemented. The tool returns not_implemented for this pair.",
        doc_quote=(
            "Used only for Google Analytics. The city of the user's address. Convert "
            "to lowercase. Remove symbol characters. Whitespace: Trim leading and "
            "trailing whitespace. Hashing: Don't hash city."
        ),
        source=GOOGLE_SOURCE,
        kb_entry=GOOGLE_KB,
    ),
    Rule(
        platform="google",
        field="state",
        param="administrative_area",
        hashed=False,
        implementation="Not implemented. The tool returns not_implemented for this pair.",
        doc_quote=(
            "Used only for Google Analytics. The administrative area (state or "
            "province) of the user's address. Use either the two-letter abbreviation "
            "(for example, ca) or the full name (for example, california). Convert to "
            "lowercase. Remove symbol characters. Whitespace: Trim leading and "
            "trailing whitespace. Hashing: Don't hash administrative_area."
        ),
        source=GOOGLE_SOURCE,
        kb_entry=GOOGLE_KB,
    ),
    Rule(
        platform="google",
        field="postal_code",
        param="postal_code",
        hashed=False,
        implementation=(
            f"{_INVISIBLE} Trims ASCII whitespace at both ends. Nothing else: no "
            "truncation, so a US ZIP+4 is kept, and never hashed."
        ),
        doc_quote=(
            "Both US and international zip and postal codes are allowed. For US "
            "addresses, use either 5 digits or 5 digits followed by a 4-digit "
            "extension. Using a 4-digit extension may improve your match rate. For all "
            "other countries, don't use postal code extensions. Whitespace: Trim "
            "leading and trailing whitespace. Hashing: Don't hash postal_code."
        ),
        source=GOOGLE_SOURCE,
        kb_entry=GOOGLE_KB,
        normalise=lambda v, _r: ident.normalise_postal_code_google(v),
    ),
    Rule(
        platform="google",
        field="country",
        param="region_code",
        hashed=False,
        implementation=(
            f"{_INVISIBLE} Accepts exactly two ASCII letters after trimming and "
            "uppercases them. Refuses full names rather than translating. Never hashed."
        ),
        doc_quote=(
            "A two-character ISO-3166-1 alpha-2 code. Whitespace: Trim leading and "
            "trailing whitespace. Hashing: Don't hash region_code."
        ),
        source=GOOGLE_SOURCE,
        kb_entry=GOOGLE_KB,
        normalise=lambda v, _r: ident.normalise_region_code_google(v),
    ),
    Rule(
        platform="meta",
        field="email",
        param="em",
        hashed=True,
        implementation=(
            f"{_INVISIBLE} Requires exactly one '@' and a dotted domain. Removes "
            "ASCII whitespace anywhere in the address and lowercases with str.lower. "
            "No Gmail-specific rule."
        ),
        doc_quote=(
            "Hashing required. Trim any leading and trailing spaces. Convert all "
            "characters to lowercase."
        ),
        source=META_SOURCE,
        kb_entry=META_KB,
        normalise=lambda v, _r: ident.normalise_email_meta(v),
        doc_examples=(
            DocExample(
                "John_Smith@gmail.com",
                "john_smith@gmail.com",
                "62a14e44f765419d10fea99367361a727c12365e2520f32218d505ed9aa0f62f",
            ),
        ),
        divergences=(
            "Whitespace inside the address is removed; the documentation asks only "
            "for leading and trailing spaces to be trimmed. A valid address has no "
            "internal whitespace, so this only changes inputs that were already broken.",
        ),
    ),
    Rule(
        platform="meta",
        field="phone",
        param="ph",
        hashed=True,
        implementation=f"{_PHONE_PARSE} Output is digits only: country code, no '+'.",
        doc_quote=(
            "Hashing required. Remove symbols, letters, and any leading zeros. Phone "
            "numbers must include a country code to be used for matching (e.g., the "
            "number 1 must precede a phone number in the United States). Always "
            "include the country code as part of your customers’ phone numbers, "
            "even if all of your data is from the same country."
        ),
        source=META_SOURCE,
        kb_entry=META_KB,
        normalise=_phone_meta,
        doc_examples=(
            DocExample(
                "(650)555-1212",
                "16505551212",
                "e323ec626319ca94ee8bff2e4c87cf613be6ea19919ed1364124e16807ab3176",
                region="US",
            ),
        ),
        divergences=(
            "Letters are refused (needs_review) instead of removed, because a letter "
            "in a phone field is usually an extension or a typo, and dropping it "
            "silently can leave a different, valid-looking number.",
            "Fewer than 8 digits in the full international number is refused, which "
            "excludes the few 7-digit E.164 numbers.",
            "'Remove any leading zeros' is applied only to the international prefix "
            "00 and to a national trunk 0 (GB, AU, DE). A number that still starts "
            "with 0 after that is refused, because stripping zeros from a format "
            "the code cannot identify can produce another subscriber's number.",
        ),
    ),
    Rule(
        platform="meta",
        field="first_name",
        param="fn",
        hashed=True,
        implementation=(
            f"{_INVISIBLE} Trims, removes Unicode punctuation, symbols and spaces "
            "(categories P, S, Z), lowercases. Accented and non-Latin letters are kept."
        ),
        doc_quote=(
            "Hashing required. Using Roman alphabet a-z characters is recommended. "
            "Lowercase only with no punctuation. If using special characters, the "
            "text must be encoded in UTF-8 format."
        ),
        source=META_SOURCE,
        kb_entry=META_KB,
        normalise=lambda v, _r: ident.normalise_name_meta(v, field="fn"),
        divergences=(
            "Spaces inside a name are removed, so 'Mary Ann' becomes 'maryann'. The "
            "fn and ln rule names only punctuation; the ct rule is the one that says "
            "no spaces. The code applies the stricter reading to names too, and the "
            "page has no multi-word example that settles it.",
            "Symbols (Unicode category S, for example the trademark sign) are removed "
            "along with punctuation. Letters with accents and non-Latin letters are "
            "kept, as the page's examples show.",
        ),
        doc_examples=(
            DocExample(
                "Mary", "mary", "6915771be1c5aa0c886870b6951b03d7eafc121fea0e80a5ea83beb7c449f4ec"
            ),
            DocExample(
                "정", "정", "8fa8cd9c440be61d0151429310034083132b35975c4bea67fdd74158eb51db14"
            ),
            DocExample(
                "Valéry",
                "valéry",
                "08e1996b5dd49e62a4b4c010d44e4345592a863bb9f8e3976219bac29417149c",
            ),
        ),
    ),
    Rule(
        platform="meta",
        field="last_name",
        param="ln",
        hashed=True,
        implementation=(
            f"{_INVISIBLE} Same as first_name: trims, removes punctuation, symbols "
            "and spaces, lowercases, keeps accented and non-Latin letters."
        ),
        doc_quote=(
            "Hashing required. Using Roman alphabet a-z characters is recommended. "
            "Lowercase only with no punctuation. If using special characters, the "
            "text must be encoded in UTF-8 format. See First Name (fn) for examples."
        ),
        source=META_SOURCE,
        kb_entry=META_KB,
        normalise=lambda v, _r: ident.normalise_name_meta(v, field="ln"),
        divergences=(
            "Spaces inside a name are removed, so 'Mary Ann' becomes 'maryann'. The "
            "fn and ln rule names only punctuation; the ct rule is the one that says "
            "no spaces. The code applies the stricter reading to names too, and the "
            "page has no multi-word example that settles it.",
            "Symbols (Unicode category S, for example the trademark sign) are removed "
            "along with punctuation. Letters with accents and non-Latin letters are "
            "kept, as the page's examples show.",
        ),
    ),
    Rule(
        platform="meta",
        field="city",
        param="ct",
        hashed=True,
        implementation=(
            f"{_INVISIBLE} Removes punctuation, symbols and spaces, lowercases: "
            "'New York' becomes 'newyork'."
        ),
        doc_quote=(
            "Hashing required. Using Roman alphabet a-z characters is recommended. "
            "Lowercase only with no punctuation, no special characters, and no spaces. "
            "If using special characters, the text must be encoded in UTF-8 format."
        ),
        source=META_SOURCE,
        kb_entry=META_KB,
        normalise=lambda v, _r: ident.normalise_city_meta(v),
    ),
    Rule(
        platform="meta",
        field="state",
        param="st",
        hashed=True,
        implementation=(
            f"{_INVISIBLE} Removes punctuation, symbols and spaces, lowercases. Does "
            "not translate a full US state name into its two-letter code: 'California' "
            "becomes 'california', not 'ca'."
        ),
        doc_quote=(
            "Hashing required. Use the 2-character ANSI abbreviation code in "
            "lowercase. Normalize states outside the U.S. in lowercase with no "
            "punctuation, no special characters, and no spaces."
        ),
        source=META_SOURCE,
        kb_entry=META_KB,
        normalise=lambda v, _r: ident.normalise_state_meta(v),
        divergences=(
            "A full US state name is normalised but not abbreviated, so it will not "
            "match Meta's hash of the two-letter code. Send the code.",
        ),
    ),
    Rule(
        platform="meta",
        field="postal_code",
        param="zp",
        hashed=True,
        implementation=(
            f"{_INVISIBLE} Removes spaces and dashes and lowercases. Keeps only the "
            "first five characters when the region is US (the record's own country "
            "when it has one, else default_region), and never otherwise. With no "
            "region at all, a value shaped like a US ZIP+4 is returned as "
            "needs_review instead of being hashed whole. A UK postcode keeps all "
            "its characters: 'M1 1AE' becomes 'm11ae'."
        ),
        doc_quote=(
            "Hashing required. Use lowercase with no spaces and no dash. Use only the "
            "first 5 digits for U.S. zip codes. Use the area, district, and sector "
            "format for the UK. Example: U.S zip code: 94035 Australia zip code: 1987 "
            "France zip code: 75018 UK zip code: m11ae"
        ),
        source=META_SOURCE,
        kb_entry=META_KB,
        normalise=_zip_meta,
        divergences=(
            "UK: the prose asks for the area, district and sector format, which for "
            "M1 1AE would stop at 'm11'; the page's own UK example is 'm11ae', the "
            "whole postcode. The page contradicts itself, and the code follows the "
            "example.",
        ),
    ),
    Rule(
        platform="meta",
        field="country",
        param="country",
        hashed=True,
        implementation=(
            f"{_INVISIBLE} Accepts exactly two ASCII letters after trimming and "
            "lowercases them. Refuses full names rather than translating them."
        ),
        doc_quote=(
            "Hashing required. Use the lowercase, 2-letter country codes in ISO "
            "3166-1 alpha-2. Important Note: Always include your customers\u2019 "
            "countries\u2019 even if all of your country codes are from the same "
            "country. We match on a global scale, and this simple step helps us match "
            "as many Accounts Center accounts as possible from your list."
        ),
        source=META_SOURCE,
        kb_entry=META_KB,
        normalise=lambda v, _r: ident.normalise_country_meta(v),
        doc_examples=(
            DocExample(
                "United States",
                "us",
                "79adb2a2fce5c6ba215fe5f27f532d4e7edbac4b6a5e09e1ef3a08084a904621",
                diverges=True,
            ),
        ),
        divergences=(
            "United States: the documented example translates a country name into "
            "its code. The code refuses names, because a translation that is wrong "
            "for one entry hashes a country the customer never lived in. Send the "
            "two-letter code.",
        ),
    ),
)

GLOBAL_DIVERGENCES: tuple[str, ...] = (
    "Invisible characters and non-ASCII whitespace (U+00A0, U+200B, U+3000 and the "
    "like) are refused with the code point named, in every field. Both platforms "
    "document trimming whitespace and say nothing about these; hashing one yields "
    "a value that silently never matches.",
    "A phone number written without its country code is completed from the "
    "record's own two-letter country, else default_region, for six numbering "
    "plans (US, CA, GB, AU, BR, DE). Both platforms require the country code and "
    "neither says where it comes from; any other region is refused, not guessed.",
)

_BY_KEY = {(rule.platform, rule.field): rule for rule in RULES}


def rule_for(platform: str, field_name: str) -> Rule | None:
    return _BY_KEY.get((platform.strip().lower(), field_name.strip().lower()))
