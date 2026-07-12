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


def determine_language(meta_lang: str | None, text: str, source_label: str) -> tuple[str, Flag | None]:
    """R15: source metadata wins if present. Otherwise run deterministic
    content-based detection on `text` and flag the result for human
    review (LANG_DETECTED). If there isn't enough text to detect
    confidently, fall back to 'en' with a loud LANG_ASSUMED flag rather
    than silently guessing or hard-rejecting the document (single-user
    tool -- a rejection is worse UX than a flagged default).

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
        if confidence >= LANG_DETECT_CONFIDENCE_THRESHOLD:
            return code, Flag(
                code="LANG_DETECTED",
                wcag_sc="3.1.1",
                message=(
                    f"No document language metadata found in {source_label}; "
                    f"detected the document language as '{code}' from its "
                    f"text content (confidence {float(confidence):.2f}). "
                    "Confirm this is correct."
                ),
            )

    return "en", Flag(
        code="LANG_ASSUMED",
        wcag_sc="3.1.1",
        message=(
            f"No document language metadata found in {source_label}, and "
            "there wasn't enough text (or the detector wasn't confident "
            "enough) to reliably detect a language; defaulted the page "
            "language to 'en'. Confirm this is correct or set the actual "
            "language -- this is a guess, not a detection."
        ),
    )
