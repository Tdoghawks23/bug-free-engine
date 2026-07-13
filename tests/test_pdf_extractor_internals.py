"""Boundary-condition unit tests for a couple of the PDF extractor's
internal thresholds (nit from the QA blocker review): the 120-char
heading-length sanity cutoff used by the per-heading confidence score,
and the 0.5 link/span-overlap ratio used to associate a hyperlink with
a text run or image."""

from __future__ import annotations

from collections import Counter

import fitz

from remediate.extractors.pdf import (
    _HEADING_LOW_CONFIDENCE_CHARS,
    _match_link,
    _heading_confidence,
)


def test_heading_length_at_threshold_scores_full_length_confidence():
    text = "x" * _HEADING_LOW_CONFIDENCE_CHARS
    # Isolate the length dimension: give size gap and tier rarity their
    # own max scores so only the length term can pull the average down.
    confidence_at = _heading_confidence(20.0, 10.0, Counter({20.0: 100}), text)
    confidence_over = _heading_confidence(20.0, 10.0, Counter({20.0: 100}), text + "x")
    assert confidence_at == 1.0
    assert confidence_over < confidence_at


def test_heading_length_one_over_threshold_starts_penalizing():
    at_threshold = "x" * _HEADING_LOW_CONFIDENCE_CHARS
    one_over = "x" * (_HEADING_LOW_CONFIDENCE_CHARS + 1)
    common_kwargs = (20.0, 10.0, Counter({20.0: 100}))
    assert _heading_confidence(*common_kwargs, at_threshold) > _heading_confidence(*common_kwargs, one_over)


def test_link_overlap_exactly_half_span_area_matches():
    # Two equal-sized (same-area) rects overlapping in exactly half
    # their area (ratio == 0.5) must still count as a match ("... >= 0.5").
    span_rect = fitz.Rect(0, 0, 10, 10)
    link_rect = fitz.Rect(5, 0, 15, 10)  # overlap (5,0,10,10) = 50, exactly half of 100
    link_pool = [{"rect": link_rect, "uri": "https://example.org/half", "matched": False}]
    assert _match_link(span_rect, link_pool) == "https://example.org/half"


def test_link_overlap_just_under_half_span_area_does_not_match():
    span_rect = fitz.Rect(0, 0, 10, 10)
    link_rect = fitz.Rect(5.1, 0, 15.1, 10)  # overlap area 4.9*10=49, just under half of 100
    link_pool = [{"rect": link_rect, "uri": "https://example.org/short", "matched": False}]
    assert _match_link(span_rect, link_pool) is None
