/* Mirror of api/cookiemonsters/scoring.py. Weights come from shared/scoring.json
 * via generated_core.js; parity is enforced by extension/tests/scoring_parity.mjs.
 * SPDX-License-Identifier: AGPL-3.0-or-later */
(function (global) {
  'use strict';
  const W = global.CM_CORE_DATA.scoring;

  function visitFriction(r) {
    const extra = Math.max(0, (r.clicks | 0) - W.min_clicks_for_outcome[r.outcome]);
    let total = W.outcome_base[r.outcome];
    total += Math.min(extra * W.extra_click_points, W.extra_click_cap);
    total += Math.min(Math.max(0, r.toggles_unticked | 0) * W.toggle_points, W.toggle_cap);
    for (const f of new Set(r.flags || [])) total += W.flag_points[f] || 0;
    return Math.max(0, Math.min(100, total));
  }

  function gradeFor(friction) {
    for (const [letter, upper] of W.grade_bands) if (friction < upper) return letter;
    return 'F';
  }

  /** Median of a list, even counts average the middle two rounded half up. */
  function median(values) {
    if (!values.length) return null;
    const s = [...values].sort((a, b) => a - b);
    const lo = s[(s.length - 1) >> 1];
    const hi = s[s.length >> 1];
    return Math.floor((lo + hi + 1) / 2);
  }

  global.CMScore = { visitFriction, gradeFor, median, version: W.scoring_version };
})(typeof window !== 'undefined' ? window : globalThis);
