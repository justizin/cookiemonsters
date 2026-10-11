import json
from pathlib import Path

import pytest

from cookiemonsters import scoring

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "shared/scoring_vectors.json").read_text())


@pytest.mark.parametrize("v", VECTORS["reports"], ids=lambda v: v["name"])
def test_visit_vectors(v):
    r = v["report"]
    f = scoring.visit_friction(r["outcome"], r["clicks"], r["toggles_unticked"], r["flags"])
    assert f == v["friction"]
    assert scoring.grade_for(f) == v["grade"]


@pytest.mark.parametrize("v", VECTORS["sites"], ids=lambda v: v["name"])
def test_site_vectors(v):
    hist = {}
    for f in v["frictions"]:
        hist[f] = hist.get(f, 0) + 1
    assert scoring.histogram_median(hist) == v["friction"]
    assert scoring.grade_for(v["friction"]) == v["grade"]


def test_median_edge_cases():
    assert scoring.histogram_median({}) is None
    assert scoring.histogram_median({7: 1}) == 7
    assert scoring.histogram_median({10: 2, 20: 2}) == 15
    assert scoring.histogram_median({10: 1, 11: 1}) == 11  # half rounds up
    assert scoring.histogram_median({0: 0, 5: 3}) == 5


def test_every_outcome_and_flag_is_weighted():
    w = scoring.weights()
    assert set(w["outcome_base"]) == set(w["min_clicks_for_outcome"])
    assert all(isinstance(v, int) for v in w["flag_points"].values())


def test_summary_shares_and_dominant_flags():
    s = scoring.site_summary(4, {5: 3, 37: 1}, {"rejected_first_layer": 3, "rejected_in_settings": 1}, {"pre_ticked": 2, "banner_reappeared": 1})
    assert s["friction"] == 5 and s["grade"] == "A" and s["score"] == 95
    assert s["dominant_flags"] == ["pre_ticked"]
    assert s["outcomes"] == {"rejected_first_layer": 0.75, "rejected_in_settings": 0.25}
    assert s["confidence"] == "medium"
