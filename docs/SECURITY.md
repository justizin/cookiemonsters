# Security and threat model

## Assets

1. The user's browsing — which sites they visit and when. The most sensitive thing in the system.
2. The user's consent state on each site — the extension must never flip it toward "accept".
3. The integrity of published grades.

## Extension

| Threat | Mitigation |
|---|---|
| A page tricks the engine into accepting (button labelled "Reject" that accepts, overlays, etc.) | Only refuse/save/settings controls are clicked; anything whose visible text classifies as accept is never clicked, even if a rule selector points at it. The engine cannot fully defend against a site that lies in its own button labels — but such a site gains nothing it could not get by not showing a reject button. |
| Engine follows a link and navigates away | Links with a real `href` to another document are never clicked. |
| Page scripts talk to the background | Content scripts run in the isolated world; no `externally_connectable`; popup/options-only messages are refused when they come from a tab. The background derives the site from `sender.tab.url`, never from page-supplied data. |
| Remote code / remote steering | No remote rules, no `eval`, extension-page CSP `script-src 'self'`. Rules ship in the package and change only with an update. |
| Leaking browsing to the server | Off by default. Reports batched, shuffled and delayed; at most one per site per day; no identifiers or timestamps. Lookups by hash prefix. `credentials: 'omit'`, `referrerPolicy: 'no-referrer'`. `http://` only to loopback. |
| Over-broad permissions | `storage`, `alarms`, host access. No `cookies`, `tabs`, `webRequest`, `history`. |

## Server

| Threat | Mitigation |
|---|---|
| Malformed or hostile input | Pydantic models with `extra="forbid"`, enums for outcome/flags/browser, bounded ints, patterned strings, ≤ 25 reports per batch, 64 KiB body cap checked from `Content-Length` before reading, JSON content type required. Validation errors return locations only, never echo values. |
| Writing to arbitrary keys (IPs, `localhost`, made-up names, public suffixes) | The site is re-derived server-side from the vendored PSL; unknown and reserved TLDs, IPs, single labels and bare suffixes are refused. |
| Grade flooding from one source | Per-client daily budget (charged per batch, up front) and per-client-per-site daily cap, both keyed by a daily-salted HMAC; Cloudflare rate-limiting rules can sit in front. Optional bearer `CM_REPORT_TOKEN` (constant-time compare) for a private deployment. |
| Ordinary web pages submitting reports from visitors' browsers | No CORS on the write path: a cross-origin JSON POST needs a preflight, which never allows POST. |
| SQL injection | All values bound as parameters. The only interpolated strings are JSON paths built from validated enum values / ints / slug-pattern CMP ids. |
| XSS on the HTML pages | Server-rendered with `html.escape`, no scripts, CSP `default-src 'none'`. |
| Logs as a side channel | The app logs nothing per request; uvicorn access logs are off in standalone; Workers observability is off in `wrangler.toml`. |
| Operator compromise | The database holds weekly per-site tallies and today's rate-limit salt and counters. With the salt, an attacker who already knows a client's IP can test which sites that IP reported *today*; after the daily prune, nothing links tallies to anyone. |

## Known limits

- **Sybil resistance**: a shared bearer token identifies "an allowed client", not a person. A multi-user deployment needs per-install anonymous credentials (e.g. Privacy Pass-style blind tokens) and a raised `CM_PUBLISH_MIN_REPORTS`.
- **Prefix lookups** hide little when the server knows few sites; the server sets the prefix length so buckets hold about 20 sites, but with fewer than ~20 known sites every bucket is small. Users who care should run the server locally.
- **Region**: reports carry no region; grades mix banners shown in different jurisdictions.
- The `tracking_before_choice` signal only sees cookies readable from `document.cookie` (not `HttpOnly`, not third-party).
