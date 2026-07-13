"""Shared helpers used by more than one format extractor.

Currently just document-language determination (R15): both the DOCX and
PDF extractors follow the exact same policy (source metadata wins;
otherwise deterministic content-based detection with a confidence
threshold; otherwise a loud 'en' fallback) so it lives here once instead
of being duplicated per format.
"""

from __future__ import annotations

from py3langid.langid import MODEL_FILE, LanguageIdentifier

from ..ir import Flag

# Content-based language detection (R15) for docs with no language
# metadata. py3langid (a maintained fork of langid.py) is used over
# langdetect because it's deterministic by construction -- langid.py's
# naive-Bayes classifier has no PRNG in its decision path, so there's no
# DetectorFactory.seed footgun to remember to pin. norm_probs=True turns
# its raw log-likelihood score into an actual 0-1 confidence so the flag
# message and the "too short/ambiguous, fall back to en" threshold below
# both have a meaningful number to compare against.
LANG_IDENTIFIER = LanguageIdentifier.from_pickled_model(MODEL_FILE, norm_probs=True)
LANG_DETECT_MIN_CHARS = 40
LANG_DETECT_CONFIDENCE_THRESHOLD = 0.7

# Dead/constructed languages in the model's 97-language set that are
# implausible for a real-world document but that the naive-Bayes
# classifier can still land on with spurious high confidence (e.g. plain
# Latin-alphabet prose with generic vocabulary gets misread as Latin
# itself, code 'la'). Restrict the classifier's candidate set up front
# (a supported py3langid feature -- proven, not hand-rolled) so these
# can't be selected in the first place.
_IMPLAUSIBLE_LANG_CODES = frozenset({"la", "eo", "vo"})
LANG_IDENTIFIER.set_languages(
    [lang for lang in LANG_IDENTIFIER.nb_classes if lang not in _IMPLAUSIBLE_LANG_CODES]
)

# Unicode code-point ranges for script families whose presence in the
# source text should constrain which detected language codes are
# plausible -- e.g. a paragraph that's substantially CJK characters
# should never be reported as detected-with-confidence 'la' or 'en'.
# Not exhaustive (this is a sanity check, not a script-detection
# subsystem): covers the common non-Latin scripts likely to show up in
# real documents.
_SCRIPT_RANGES: dict[str, list[tuple[int, int]]] = {
    "cjk": [(0x4E00, 0x9FFF), (0x3040, 0x30FF), (0x3400, 0x4DBF), (0xAC00, 0xD7A3), (0xF900, 0xFAFF)],
    "cyrillic": [(0x0400, 0x04FF)],
    "arabic": [(0x0600, 0x06FF), (0x0750, 0x077F)],
    "greek": [(0x0370, 0x03FF)],
    "hebrew": [(0x0590, 0x05FF)],
    "devanagari": [(0x0900, 0x097F)],
    "thai": [(0x0E00, 0x0E7F)],
}

# Language codes (from the model's set) that are a plausible detection
# result when a script family dominates the text. If the script family
# is dominant but the detected code isn't in this set, the detection is
# treated as unreliable rather than shipped at face value.
_SCRIPT_FAMILY_PLAUSIBLE_CODES: dict[str, frozenset[str]] = {
    "cjk": frozenset({"zh", "ja", "ko"}),
    "cyrillic": frozenset({"ru", "uk", "bg", "sr", "mk", "be"}),
    "arabic": frozenset({"ar", "fa", "ps", "ur"}),
    "greek": frozenset({"el"}),
    "hebrew": frozenset({"he"}),
    "devanagari": frozenset({"hi", "mr", "ne"}),
    "thai": frozenset({"th"}),
}

# A script family only overrides the detected code if it makes up at
# least this fraction of the text's alphabetic characters -- a few
# stray CJK characters in an otherwise-English document (e.g. a quoted
# proper noun) shouldn't override an otherwise-solid English detection.
_SCRIPT_SIGNIFICANT_FRACTION = 0.15


def _dominant_script_family(text: str) -> str | None:
    """The script family making up the largest share of `text`'s
    alphabetic characters, if that share is significant; else None
    (text is Latin-script or too mixed to call)."""
    family_counts: dict[str, int] = {}
    total_letters = 0
    for ch in text:
        if not ch.isalpha():
            continue
        total_letters += 1
        cp = ord(ch)
        for family, ranges in _SCRIPT_RANGES.items():
            if any(lo <= cp <= hi for lo, hi in ranges):
                family_counts[family] = family_counts.get(family, 0) + 1
                break
    if not family_counts or total_letters == 0:
        return None
    family, count = max(family_counts.items(), key=lambda kv: kv[1])
    if count / total_letters >= _SCRIPT_SIGNIFICANT_FRACTION:
        return family
    return None


def _is_plausible_detection(code: str, text: str) -> bool:
    """Sanity check on a py3langid result: if a non-Latin script family
    dominates the text, the detected code must belong to that family's
    known languages -- otherwise the detection is more likely a
    classifier quirk (e.g. mixed-script text) than a real result."""
    if code in _IMPLAUSIBLE_LANG_CODES:
        return False
    family = _dominant_script_family(text)
    if family is None:
        return True
    return code in _SCRIPT_FAMILY_PLAUSIBLE_CODES.get(family, frozenset())


def determine_language(meta_lang: str | None, text: str, source_label: str) -> tuple[str, Flag | None]:
    """R15: source metadata wins if present. Otherwise run deterministic
    content-based detection on `text` and flag the result for human
    review (LANG_DETECTED) -- but only if the detection is plausible
    (see `_is_plausible_detection`): a confident-but-implausible result
    (script/code mismatch, or a dead/constructed-language code) is
    treated the same as "not confident enough" rather than shipped with
    unwarranted authority. If there isn't enough text, or no plausible
    confident detection, fall back to 'en' with a loud LANG_ASSUMED flag
    rather than silently guessing or hard-rejecting the document
    (single-user tool -- a rejection is worse UX than a flagged
    default).

    `source_label` is a short human-readable description of where the
    metadata would have come from (e.g. "the source .docx",
    "the source PDF") for the flag message.
    """
    meta_lang = (meta_lang or "").strip()
    if meta_lang:
        return meta_lang.split(",")[0].strip(), None

    text = text.strip()
    if len(text) >= LANG_DETECT_MIN_CHARS:
        code, confidence = LANG_IDENTIFIER.classify(text)
        if confidence >= LANG_DETECT_CONFIDENCE_THRESHOLD and _is_plausible_detection(code, text):
            return code, Flag(
                code="LANG_DETECTED",
                wcag_sc="3.1.1",
                message=(
                    f"No document language metadata found in {source_label}; "
                    f"automated content-based detection guessed the "
                    f"document language is '{code}' (confidence "
                    f"{float(confidence):.2f}). This is a machine guess, "
                    "not a confirmed detection -- verify it's correct."
                ),
            )

    return "en", Flag(
        code="LANG_ASSUMED",
        wcag_sc="3.1.1",
        message=(
            f"No document language metadata found in {source_label}, and "
            "there wasn't enough text (or no detection could be reliably "
            "made -- e.g. too little text, low confidence, or a result "
            "that didn't hold up to a sanity check) to determine a "
            "language; defaulted the page language to 'en'. Confirm this "
            "is correct or set the actual language -- this is a guess, "
            "not a detection."
        ),
    )
