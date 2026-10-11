# Design

## Goals, in priority order

1. **Never make things worse for the user.** The extension never clicks anything that grants consent, never navigates away, and never hides a banner it could not refuse (hiding would leave tracking on while looking like it is off).
2. **Collect the least data that can still produce a grade**, and say plainly what that data reveals (see [PRIVACY.md](PRIVACY.md)).
3. **Measure friction honestly and reproducibly**, so grades can feed a ranking signal without anyone having to trust a black box.
4. One codebase per side: one extension source tree for three browsers, one Python app for laptop and serverless.

## Shape

```
              browser                                       server (standalone or Cloudflare Worker)
┌──────────────────────────────────────────┐        ┌────────────────────────────────────────────────┐
│ content script (every frame)             │        │ FastAPI app (api/cookiemonsters/app.py)        │
│  engine.js: detect → refuse → measure    │        │  POST /v1/reports  ──► service.submit           │
│        │ result (outcome, clicks, flags) │        │       validate · re-derive site · rate-limit    │
│        ▼                                 │        │       fold into site_week (one atomic UPSERT)   │
│ background                               │ batch, │       recompute cached site summary             │
│  merge frames per tab, badge, popup      │ random │  GET /v1/lookup/{hex prefix}  (private lookup)  │
│  queue ≤1 report/site/day ───────────────┼─delay─►│  GET /v1/sites/{site}  /v1/feed  /v1/feed.jsonl │
│  lookup grade by SHA-256 prefix ◄────────┼────────┤  GET /v1/leaderboard  /v1/meta  /v1/privacy  / │
└──────────────────────────────────────────┘        │ Store (storage/sql.py) — one SQLite-dialect     │
                                                    │  layer; executors: sqlite3 · D1 binding         │
                                                    └────────────────────────────────────────────────┘
```

## Extension

### Engine (`extension/src/content/engine.js`)

Pure DOM, no extension APIs, so the tests inject it straight into fixture pages.

1. **Detect.** Watch the DOM (MutationObserver plus a 500 ms poll for shadow roots and style changes) for up to 15 s, because tag managers inject banners late. Try each CMP rule in `extension/rules/cmps.json` (26 platforms: OneTrust, Cookiebot, Didomi, Quantcast/InMobi, Sourcepoint message + privacy manager, TrustArc, Usercentrics, Osano, CookieYes, Klaro, iubenda, Complianz, Borlabs, CookieConsent v2/v3, Google Funding Choices, consentmanager, Termly, Axeptio, tarteaucitron, Shopify, HubSpot, Cookie-Script, Civic, Wix). Rules may name a `shadowHost`; all queries walk open shadow roots. Otherwise fall back to the heuristic: a visible, banner-ish container (dialog roles, cookie/consent/privacy ids and classes, or anything `position: fixed/sticky`) whose text talks about cookies or consent in one of ~20 languages and which contains at least one reject or accept button.
2. **Refuse.** In order, stopping at the first that makes the banner disappear: the first-layer reject button; the settings panel's reject-all; switching off every optional toggle in the panel and pressing save. Buttons come from the rule's selectors when they exist, otherwise from the text classifier (`extension/rules/heuristics.json`), which checks *accept all* first, then reject, save, settings, accept. Anything classified as accept is never clicked, even if a rule selector points at it (a stale rule is treated as missing, not obeyed). Links that would navigate are never followed.
3. **Toggles.** Checkboxes, `role=switch`/`checkbox` and `aria-pressed` buttons in the panel. Disabled ones and those whose label mentions necessary/essential/required/"always active" are skipped. A toggle labelled *legitimate interest* is switched off and flagged even if it also says "necessary". If an input does not flip, its label is clicked.
4. **Verify.** The banner must be gone within 2.5 s; then the page is watched 4 s more for a banner that comes back.
5. **Measure.** Outcome, clicks, toggles switched off, CMP id and six dark-pattern flags: `pre_ticked`, `legitimate_interest`, `reject_less_prominent` (reject button area < 60 % of the largest accept button), `reject_needs_scroll`, `banner_reappeared`, `tracking_before_choice` (a well-known tracking cookie name such as `_ga`/`_fbp` was already in `document.cookie` before any choice — names are matched locally and only the yes/no leaves). Outcomes: `no_banner`, `rejected_first_layer`, `rejected_in_settings`, `rejected_by_toggles`, `reject_failed`, `accept_only`, `consent_or_pay`.

Every frame runs the engine (`all_frames`), because Sourcepoint, TrustArc and others render in iframes; only the top frame reports `no_banner`, so an empty ad iframe cannot overwrite a real result. The background attributes every frame's result to the **tab's** top-level site.

### Background (`extension/src/background/bg.js`)

- Keeps per-tab state in `storage.session` (survives service-worker restarts), merging frames (a frame that found a banner beats one that did not).
- Badge: the server grade when known, otherwise a grade for this visit computed locally with the same scorer as the server (`common/score.js`, parity-tested against Python).
- Reports, only if a server is set *and* reporting is on: at most one per site per UTC day; queued in `storage.local`; sent as one shuffled batch after a random 5–30 minute delay (`alarms`); retried later on network error, 401, 429 or 5xx; dropped if reporting is switched off. Plain `http://` is allowed only to 127.0.0.1/localhost.
- Lookups, only if lookups are on: `GET /v1/meta` tells the client how many hex characters of `SHA-256(site)` to send (1–4, chosen so each bucket holds ~20 known sites); `GET /v1/lookup/{prefix}` returns every graded site in that bucket; the client picks its own. Buckets are cached 6 h (30 min when the site was not in it) and cleared after each successful report batch. `fetch` uses `cache: 'no-store'` so the browser's HTTP cache cannot serve a stale bucket behind our back.
- Message handlers reject popup/options-only messages that come from content scripts.

### Cross-browser

`manifest.base.json` + `manifests/<browser>.json`, deep-merged by `build.py`. Chrome uses a service worker that `importScripts` the same files Firefox and Safari list in `background.scripts`. APIs are called through `globalThis.browser || globalThis.chrome`. Firefox needs a gecko id and an explicit host-permission grant for the server (button on the settings page). Safari is the Chrome-style tree wrapped by `xcrun safari-web-extension-converter`.

Permissions: `storage`, `alarms`, host access to all sites. Deliberately **not** `cookies`, `tabs`, `webRequest` or `webNavigation`.

## Server

### One app, two runtimes

`create_app()` builds the FastAPI app. Standalone: `cookiemonsters serve` constructs a `Service` over `SQLiteExecutor` and runs uvicorn with access logs off, bound to 127.0.0.1 by default. Worker: `api/worker/src/entry.py` hands requests to Cloudflare's `asgi` bridge, which puts the Worker `env` into `scope["env"]`; the app then builds a `Service` over `D1Executor(env.DB)` for that request. Every query lives once in `storage/sql.py` in SQLite dialect, which D1 also speaks. Bound parameters are never NULL (D1 cannot bind Python `None` reliably). Generated data (scoring weights, PSL, privacy text) is a Python module, not package data, so it imports identically under CPython and Pyodide.

### No raw reports

A report is validated, its site re-derived against the Public Suffix List, scored, and folded into `site_week(site, ISO week, scoring_version)` with one atomic `INSERT … ON CONFLICT DO NOTHING` + `UPDATE … json_set(…)` batch: a count, a histogram of per-visit friction, outcome counts, flag counts, CMP counts. The report itself is not stored anywhere. The median per site is computed from the histogram, so no individual data is needed to score. The public record per site is cached in `sites` and rebuilt when its reports change or when the 13-week window moves (daily maintenance).

Trade-off accepted: if the scoring formula changes, history cannot be re-scored; `scoring_version` is part of the key and old-version rows are dropped, so grades re-learn over one window. Keeping raw reports would make re-scoring possible, at the cost of storing exactly the per-visit record PRIVACY.md promises not to keep.

### Rate limiting without storing addresses

`day_salt` holds one random salt per UTC day. Counters are keyed by `HMAC(salt, client address)` (daily budget, charged per batch before anything is folded so a refused batch can be retried unchanged) and `HMAC(salt, address|site)` (per-site daily cap, so one client cannot dominate a site). The first request of each day, and the daily cron in the Worker, delete earlier salts and counters, after which the keys cannot be reversed or linked. PRIVACY.md states the residual risk during the day.

### Scoring and feed

See [SCORING.md](SCORING.md) and [DATA_FEED.md](DATA_FEED.md). Weights are in `shared/scoring.json`; `shared/scoring_vectors.json` holds hand-computed cases both implementations must reproduce.

## Single sources and generated files

`tools/sync_generated.py` derives: `api/cookiemonsters/_generated.py` (weights, PSL, privacy text), `extension/src/common/generated_core.js` (weights, PSL), `generated_rules.js` (CMP rules + heuristics), `options.html` (settings page with the privacy text), `docs/PRIVACY.md`, and the D1 migration from `storage/sql.py`. `--check` fails CI when anything is stale, and `build.py` refuses to build with stale files.

## Non-goals here

- Global Privacy Control / `Sec-GPC` headers (a different mechanism; easy follow-up via `declarativeNetRequest`).
- Remote rule updates. Rules ship with the extension; fetching selectors from a server would let that server steer what the extension clicks.
- Accounts, per-user history, dashboards.
