"""The grader must fail an invented digest even when the right one is also present."""

from __future__ import annotations

import hashlib

from eval.cases import CASES, HEX64
from eval.run_eval import grade

BY_ID = {case.id: case for case in CASES}


def answer_with(*digests: str, cite: str = "") -> str:
    return "\n".join(f"`{d}`" for d in digests) + cite


def test_case_ids_are_unique():
    assert len(BY_ID) == len(CASES)


def test_expected_digests_are_well_formed():
    for case in CASES:
        for digest in case.expect_hashes:
            assert HEX64.fullmatch(digest), case.id


def test_correct_answer_passes():
    case = BY_ID["V1-gmail-both"]
    answer = answer_with(*case.expect_hashes, cite=" [normalization_and_hashing/google] [normalization_and_hashing/meta]")
    assert grade(case, answer, ["normalize_and_hash"], kb_only=False) == {"pass": True, "failures": []}


def test_an_extra_invented_digest_fails_the_case():
    case = BY_ID["V2-meta-phone-published"]
    invented = hashlib.sha256(b"+16505551212").hexdigest()  # Google's spelling, wrong for Meta
    answer = answer_with(*case.expect_hashes, invented, cite=" [normalization_and_hashing/meta]")
    verdict = grade(case, answer, ["normalize_and_hash"], kb_only=False)
    assert not verdict["pass"]
    assert any("invented digest" in f for f in verdict["failures"])


def test_an_extra_digest_that_came_from_a_tool_result_is_allowed():
    case = BY_ID["K3-google-unhashed"]
    from_tool = hashlib.sha256(b"a line from a tool").hexdigest()
    answer = (f"In clear: postal_code, region_code, city, administrative_area. "
              f"For contrast, a hashed field looks like `{from_tool}` [normalization_and_hashing/google]")
    tools = ["knowledge_base_read", "normalize_and_hash"]
    assert not grade(case, answer, tools, kb_only=False)["pass"]
    assert grade(case, answer, tools, kb_only=False, tool_digests=frozenset({from_tool}))["pass"]


def test_uppercase_digest_is_still_recognised():
    case = BY_ID["V6-meta-country"]
    answer = answer_with(case.expect_hashes[0].upper(), cite=" [normalization_and_hashing/meta]")
    assert grade(case, answer, ["normalize_and_hash"], kb_only=False)["pass"]


def test_missing_citation_and_missing_tool_call_fail():
    case = BY_ID["V4-google-phone"]
    verdict = grade(case, answer_with(*case.expect_hashes), [], kb_only=False)
    assert "no citation [normalization_and_hashing/google]" in verdict["failures"]
    assert "did not call normalize_and_hash|preflight_batch" in verdict["failures"]


def test_baseline_is_not_failed_for_tools_it_does_not_have():
    case = BY_ID["R1-phone-no-country"]
    verdict = grade(case, "It needs a country code.", [], kb_only=True)
    assert verdict["pass"]


def test_refusal_fails_if_any_digest_appears():
    case = BY_ID["R1-phone-no-country"]
    digest = hashlib.sha256(b"5550199").hexdigest()
    verdict = grade(case, f"Without a country: `{digest}`", ["normalize_and_hash"], kb_only=False)
    assert not verdict["pass"]


def test_brazilian_cep_cut_to_five_digits_fails():
    case = BY_ID["K4-brazil-cep"]
    good = grade(case, "Send `24020-005` in clear [normalization_and_hashing/google]", [], kb_only=False)
    bad = grade(case, "Send `24020`, dropping the extension [normalization_and_hashing/google]", [], kb_only=False)
    undecided = grade(case, "Could be `24020-005`, `24020005` or `24020`; I won't guess "
                      "[normalization_and_hashing/google]", [], kb_only=False)
    listed = grade(case, "I can't tell you whether to send `24020-005`, `24020005` or `24020` "
                   "[normalization_and_hashing/google]", [], kb_only=False)
    assert good["pass"] and not bad["pass"]
    assert not undecided["pass"] and not listed["pass"]
    assert not any("forbidden" in f for f in undecided["failures"])


# The auditor's counterexamples: wrong answers that version 1 of the grader
# passed, and right answers it failed.
G = " [normalization_and_hashing/google]"
M = " [normalization_and_hashing/meta]"
KB = ["knowledge_base_read"]


def test_refusal_fails_even_when_the_digest_came_from_a_tool():
    case = BY_ID["R1-phone-no-country"]
    guessed = hashlib.sha256(b"15550199").hexdigest()
    verdict = grade(case, f"Assuming the US: `{guessed}`, country code 1.", ["normalize_and_hash"],
                    kb_only=False, tool_digests=frozenset({guessed}))
    assert not verdict["pass"]
    assert any("digest in a refusal" in f for f in verdict["failures"])


def test_affirming_the_wrong_rule_fails_the_rule_cases():
    wrong = {
        "K1-meta-gmail-dots": "Yes. Meta wants the dots removed from jane.doe+promo@gmail.com; "
                              "this step is not optional." + M,
        "K5-non-gmail-dots": "Yes, first.last@company.com becomes firstlast@company.com; "
                             "do not keep the dots." + G,
        "K3-google-unhashed": "Hash city, state, country and postal code; region_code too." + G,
        "K4-brazil-cep": "Don't send 24020-005. Google wants 24020." + G,
    }
    for case_id, answer in wrong.items():
        assert not grade(BY_ID[case_id], answer, KB, kb_only=False)["pass"], case_id


def test_right_answers_in_plain_words_pass_the_rule_cases():
    right = {
        "K1-meta-gmail-dots": "No. Meta keeps them: jane.doe+promo@gmail.com is hashed as written, "
                              "lowercased and trimmed." + M,
        "K5-non-gmail-dots": "No. Outside gmail.com and googlemail.com the dots stay, so "
                             "first.last@company.com is hashed as first.last@company.com." + G,
        "K3-google-unhashed": "In clear: postal_code, region_code (country), city and "
                              "administrative_area (state). Do not hash them." + G,
        "K4-brazil-cep": "Send 24020-005, exactly as written; it is not hashed." + G,
        "K2-google-base64": "Not only hex: the Data Manager API accepts Base64 as well." + G,
    }
    for case_id, answer in right.items():
        verdict = grade(BY_ID[case_id], answer, KB, kb_only=False)
        assert verdict["pass"], (case_id, verdict)
