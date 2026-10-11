"""Friction scoring. Weights live in shared/scoring.json (compiled into _generated.py).

Per visit:   friction = outcome base + extra clicks + toggles + dark-pattern flags,
             clamped to [0, 100].
Per site:    friction = median of per-visit friction over the last 13 weeks
             (mean of the two middle values for an even count, rounded half up),
             computed from a histogram so raw reports never need to be stored.
             score = 100 - friction; grade from fixed bands.

See docs/SCORING.md for the rationale behind every number.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from ._generated import SCORING


def weights() -> dict:
    return SCORING


def scoring_version() -> int:
    return int(weights()["scoring_version"])


OUTCOMES: tuple[str, ...] = tuple(weights()["outcome_base"])
FLAGS: tuple[str, ...] = tuple(weights()["flag_points"])


def visit_components(outcome: str, clicks: int, toggles_unticked: int, flags: Iterable[str]) -> dict[str, int]:
    w = weights()
    extra = max(0, clicks - w["min_clicks_for_outcome"][outcome])
    comps = {
        "outcome": w["outcome_base"][outcome],
        "extra_clicks": min(extra * w["extra_click_points"], w["extra_click_cap"]),
        "toggles": min(max(0, toggles_unticked) * w["toggle_points"], w["toggle_cap"]),
    }
    for f in sorted(set(flags)):
        comps["flag:" + f] = w["flag_points"][f]
    return comps


def visit_friction(outcome: str, clicks: int, toggles_unticked: int, flags: Iterable[str]) -> int:
    total = sum(visit_components(outcome, clicks, toggles_unticked, flags).values())
    return max(0, min(100, total))


def grade_for(friction: int) -> str:
    for letter, upper in weights()["grade_bands"]:
        if friction < upper:
            return letter
    return "F"


def histogram_median(hist: Mapping[int, int]) -> int | None:
    """Median of a {value: count} histogram; even counts average the middle two, rounded half up."""
    n = sum(c for c in hist.values() if c > 0)
    if n == 0:
        return None
    lo_idx, hi_idx = (n - 1) // 2, n // 2
    lo = hi = None
    seen = 0
    for value in sorted(hist):
        c = hist[value]
        if c <= 0:
            continue
        if lo is None and seen + c > lo_idx:
            lo = value
        if seen + c > hi_idx:
            hi = value
            break
        seen += c
    assert lo is not None and hi is not None
    return (lo + hi + 1) // 2


def confidence(n: int) -> str:
    c = weights()["confidence"]
    if n >= c["high"]:
        return "high"
    if n >= c["medium"]:
        return "medium"
    return "low"


def site_summary(n: int, hist: Mapping[int, int], outcomes: Mapping[str, int], flags: Mapping[str, int]) -> dict:
    """Turn aggregated counts into the public per-site record (without the site key)."""
    friction = histogram_median(hist)
    if friction is None:
        return {"reports": 0, "friction": None, "score": None, "grade": None, "confidence": "none", "outcomes": {}, "flags": {}, "dominant_flags": []}
    threshold = weights()["flag_share_threshold"]
    flag_share = {f: round(flags.get(f, 0) / n, 3) for f in FLAGS if flags.get(f, 0)}
    outcome_share = {o: round(outcomes.get(o, 0) / n, 3) for o in OUTCOMES if outcomes.get(o, 0)}
    return {
        "reports": n,
        "friction": friction,
        "score": 100 - friction,
        "grade": grade_for(friction),
        "confidence": confidence(n),
        "outcomes": outcome_share,
        "flags": flag_share,
        "dominant_flags": sorted(f for f, s in flag_share.items() if s >= threshold),
    }
