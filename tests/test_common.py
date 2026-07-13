"""Tests for the shared language-detection helper
(src/remediate/extractors/common.py) -- QA blocker regression coverage
(mixed-script false positives, implausible dead/constructed-language
codes) plus the softened LANG_DETECTED wording."""

from __future__ import annotations

from remediate.extractors.common import (
    _IMPLAUSIBLE_LANG_CODES,
    _dominant_script_family,
    _is_plausible_detection,
    determine_language,
)

# A long enough paragraph, dominated by English prose, with a modest
# amount of embedded Chinese -- QA's repro: the unrestricted classifier
# reads plain Latin-alphabet prose like this as 'la' (Latin) at
# confidence 1.0, a wrong language shipped with unwarranted authority.
_MIXED_EN_CJK_TEXT = (
    "This report covers 中文内容 which is embedded within the English "
    "text of this quarterly summary document for review purposes and "
    "stakeholder communication needs across departments 谢谢大家的支持和帮助."
)


def test_mixed_en_cjk_paragraph_never_detected_as_implausible_code():
    lang, flag = determine_language(None, _MIXED_EN_CJK_TEXT, "the source PDF")
    assert lang not in _IMPLAUSIBLE_LANG_CODES
    assert flag is not None
    assert flag.code in ("LANG_DETECTED", "LANG_ASSUMED")


def test_lang_detected_message_reads_as_a_guess_not_a_certainty():
    lang, flag = determine_language(
        None,
        "This is a perfectly ordinary English paragraph with enough words "
        "to be confidently detected as English by the classifier for this "
        "test case here, covering the default happy path end to end.",
        "the source PDF",
    )
    assert flag is not None and flag.code == "LANG_DETECTED"
    assert "guess" in flag.message.lower()
    assert "not a confirmed detection" in flag.message.lower()


def test_implausible_codes_are_excluded_from_the_classifier_candidate_set():
    # 'la' (Latin) and 'eo' (Esperanto) are supported by the underlying
    # model but implausible for a real document -- set_languages() must
    # have removed them from the classifier's candidate set entirely.
    for code in ("la", "eo", "vo"):
        assert not _is_plausible_detection(code, "any text")


def test_dominant_script_family_detects_majority_cjk_text():
    cjk_text = "这是一段完全由中文字符组成的文本用于测试脚本检测功能是否正确识别多数字符集属于中日韩统一表意文字范围之内。"
    assert _dominant_script_family(cjk_text) == "cjk"


def test_dominant_script_family_ignores_a_few_stray_non_latin_characters():
    mostly_english = (
        "This is an English paragraph that happens to quote a single "
        "foreign proper noun like 京都 in passing but is otherwise "
        "entirely ordinary Latin-script prose with plenty of words."
    )
    assert _dominant_script_family(mostly_english) is None


def test_script_mismatch_is_treated_as_implausible():
    # A detected code outside a dominant script family's known languages
    # should never be accepted at face value.
    cjk_text = "这是一段完全由中文字符组成的文本用于测试脚本检测功能是否正确识别多数字符集属于中日韩统一表意文字范围之内。"
    assert not _is_plausible_detection("fr", cjk_text)
    assert _is_plausible_detection("zh", cjk_text)


def test_language_assumed_fallback_message_still_explains_the_default():
    lang, flag = determine_language(None, "short", "the source PDF")
    assert lang == "en"
    assert flag is not None and flag.code == "LANG_ASSUMED"
    assert "guess" in flag.message.lower()
