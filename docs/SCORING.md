# Scoring

All numbers live in [`shared/scoring.json`](../shared/scoring.json). `scoring_version` is 1. Both the Python scorer and the extension's JavaScript scorer must reproduce [`shared/scoring_vectors.json`](../shared/scoring_vectors.json) exactly.

## Per visit: friction points (0 = effortless, 100 = impossible)

```
friction = outcome base
         + 4 per click beyond the outcome's minimum   (cap 20)
         + 2 per optional switch turned off           (cap 16)
         + points for each dark-pattern flag
clamped to [0, 100]
```

| Outcome | Base | Minimum clicks | Why |
|---|---|---|---|
| `no_banner` | 0 | 0 | Nothing to refuse. (If tracking cookies were set anyway, the flag below still costs 10.) |
| `rejected_first_layer` | 5 | 1 | The good case: one visible "Reject all". |
| `rejected_in_settings` | 25 | 2 | Refusing exists but is one layer down, behind "Settings". This is the most common way refusal is made harder than acceptance. |
| `rejected_by_toggles` | 35 | 2 | No reject-all anywhere: each category has to be switched off and saved. |
| `reject_failed` | 60 | 0 | The extension tried and the banner stayed. Usually a broken rule or an unusually hostile banner; weighted below "accept only" because some of it is our fault. |
| `accept_only` | 75 | 0 | Only "accept" is offered. |
| `consent_or_pay` | 80 | 0 | Refusing costs money ("accept tracking or subscribe"). |

| Flag | Points | Meaning |
|---|---|---|
| `pre_ticked` | 8 | Optional categories were already on when the panel opened. |
| `legitimate_interest` | 6 | Tracking enabled under "legitimate interest", needing a separate objection. |
| `reject_less_prominent` | 6 | Reject button area under 60 % of the biggest accept button. |
| `banner_reappeared` | 10 | The banner came back within 4 s of refusing. |
| `tracking_before_choice` | 10 | A well-known tracking cookie existed before any choice was made. |
| `reject_needs_scroll` | 4 | The reject control was outside the viewport. |

Grades are bands on friction: **A** < 10, **B** < 25, **C** < 45, **D** < 70, **F** otherwise. `score = 100 − friction`, so higher is better.

Examples: one-click reject → 5 (A). Settings → reject-all with pre-ticked boxes and three clicks → 25 + 4 + 8 = 37 (C). Ten categories switched off over twelve clicks with legitimate interest and a returning banner → 35 + 20 + 16 + 6 + 10 = 87 (F).

## Per site

- **Window**: the current ISO week and the 12 before it (13 weeks ≈ 90 days). Older aggregates are deleted.
- **Friction**: median of per-visit friction over the window (even count: mean of the two middle values, rounded half up). Computed from a stored histogram, so no individual report is needed.
- **Confidence**: `low` < 3 reports, `medium` < 10, `high` ≥ 10.
- **Shares**: fraction of reports per outcome, per flag and per CMP. A flag is "dominant" at ≥ 50 %.
- **`rank_signal`**: `(score/100 · n + 0.5 · 3) / (n + 3)` — the score shrunk toward neutral by sample size, so a site with one bad report does not rank as low as one with a hundred. Usable directly as a feature in [0, 1].

The median (not the mean) keeps one odd visit — an A/B-tested banner variant, a rule that misfired once — from moving a grade.

## Changing the formula

Bump `scoring_version`, update the vectors, run `tools/sync_generated.py`. Aggregates are keyed by version, and rows from other versions are deleted at the next maintenance run, so grades re-learn over one window. This is the cost of not keeping raw reports (see DESIGN.md).
