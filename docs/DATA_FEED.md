# Ranking feed

The service publishes one record per **registrable domain** (eTLD+1 per the Public Suffix List, lowercase, IDNs in punycode) — the same key search indexes use for site-level signals. The JSON Schema is served at `GET /v1/schema` and defined by `SiteRecord` in `api/cookiemonsters/models.py`.

## Record

```json
{
  "schema_version": 1,
  "scoring_version": 1,
  "site": "example.de",
  "score": 63,
  "friction": 37,
  "grade": "C",
  "confidence": "low",
  "reports": 1,
  "rank_signal": 0.5325,
  "window_weeks": 13,
  "first_seen_week": "2026-W41",
  "last_seen_week": "2026-W41",
  "outcomes": {"rejected_in_settings": 1.0},
  "flags": {"pre_ticked": 1.0},
  "dominant_flags": ["pre_ticked"],
  "cmps": {"didomi": 1.0}
}
```

| Field | Use |
|---|---|
| `score` (0–100, higher = easier to refuse) / `friction` (= 100 − score) | The headline number. Monotone, documented in SCORING.md. |
| `rank_signal` (0–1) | Score shrunk toward 0.5 by sample size; safest to use directly as a ranking feature. |
| `grade`, `confidence`, `reports` | For display, and for thresholding (e.g. only use `confidence != "low"`). |
| `outcomes`, `flags`, `cmps` | Shares (0–1) so a consumer can re-weight: e.g. penalise only `consent_or_pay`, or only `tracking_before_choice`. |
| `first_seen_week`, `last_seen_week` | Freshness. Weeks, never days or times. |
| `schema_version`, `scoring_version` | Shape and formula versions; a consumer should check both. |

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /v1/feed?cursor=&limit=500&since=2026-W30&min_reports=3` | Keyset-paginated by `site`. Follow `next_cursor` until it is `null`. `since` limits to sites seen in or after that ISO week, for incremental pulls. |
| `GET /v1/feed.jsonl?since=&min_reports=` | Everything, one record per line (`application/x-ndjson`), streamed. |
| `GET /v1/sites/{host-or-site}` | One record; the server normalises the input. |
| `GET /v1/leaderboard?order=worst\|best&limit=` | Convenience ranking. |
| `GET /v1/schema` | JSON Schemas for the record and for reports. |

All read endpoints are public, cacheable, CORS `*`, and contain no personal data. `CM_PUBLISH_MIN_REPORTS` hides sites below a report count from every read endpoint; raise it before many people share a server, so a published tally cannot be traced to one reporter.

## Caveats for a ranking consumer

- Grades measure the banner a reporter saw. Sites show different banners by region (often none outside the EU/UK) and by A/B bucket. Reports carry no region, by design; a consumer who needs regional grades needs regional servers.
- `reject_failed` partly measures the extension's rules, not the site. Consider down-weighting it or requiring `confidence: "high"`.
- A one-person server's feed is a list of sites one person visited (see PRIVACY.md). Do not publish it.
