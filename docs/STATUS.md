# Status of this attempt (claude-opus-5.5, 2026-10-11)

## Verified here

- `tools/sync_generated.py --check`: all derived files current.
- 76 API tests (`api/tests`): scoring vectors, PSL normalisation (shared vectors with the extension), validation/no-echo, body and content-type limits, token, both rate limits (refused batches fold nothing), weekly window, maintenance pruning salts/counters/old weeks, prefix lookup, prefix-length growth, publish threshold, feed pagination + JSONL + schema validation, leaderboard, HTML escaping, privacy text in sync across server/docs/extension, security headers and CORS, "no client address anywhere in the database", D1 executor against a fake D1 binding, the Worker entry wiring `env` into the ASGI bridge and its cron handler.
- `node extension/tests/scoring_parity.mjs`: the JS scorer and PSL agree with Python on all 27 shared vectors, and SHA-256 prefixes match.
- 48 engine tests in headless Chromium against 15 fixture pages (OneTrust ×2 + mislabelled rule, Cookiebot, Usercentrics in shadow DOM, Sourcepoint message frame, HubSpot reappearing banner, generic English with a tiny reject, generic German settings panel with legitimate interest, late-injected banner, accept-only, consent-or-pay, navigating "Decline" link, no banner, tracking without asking) plus 32 button-label classifications in 7 languages.
- 2 end-to-end tests with the **built Chrome package** in real Chromium: default config sends nothing; after configuring a live standalone API with a token, three sites (one via a cross-origin consent iframe) are refused, badged, queued with a pending random-delay alarm, flushed as one batch, graded server-side; a revisit gets the server grade through the prefix lookup, queues no second report, and the server never sees the site name outside reports. Per-site disable leaves the banner alone.
- Standalone server via `cookiemonsters serve` (pip-installed into a fresh venv): health, report, feed, export; no access-log lines.
- `npx wrangler d1 migrations apply --local` applied the generated migration; `wrangler dev` bundled the Worker and its modules.

- Container (added 2026-10-17): `Containerfile` built with Docker 29 and run with `--read-only --cap-drop ALL --security-opt no-new-privileges` and a named volume. It ran as uid 10001, answered `/healthz`, refused reports without the token, accepted one with it, kept the data across a restart, reported healthy, wrote no request logs, and `export` worked from a one-off container. `docker compose config` validates `compose.yaml`. Docker Hub is blocked in this sandbox, so the build used a stand-in base image (this machine's Python 3.13 on glibc) passed as `PYTHON_IMAGE`, not `python:3.13-slim-bookworm` itself.

## Not verified here

- **The Python Worker did not execute.** `workerd` must download the Pyodide runtime (`pyodide-capnp-bin.edgeworker.net`) and `pywrangler` must reach `index.pyodide.org`; both are blocked in this sandbox. Run `pywrangler dev` in `api/worker/` once before deploying. The ASGI bridge contract (`asgi.fetch(app, request.js_object, env)` with `env` in `scope["env"]`) is covered only by tests with stand-ins.
- Firefox and Safari were not run; their manifests are generated from the same base and checked only for referenced files. `--safari-xcode` was not run (no macOS).
- CMP selectors were exercised against fixtures that imitate each vendor's markup, not against live sites. Expect some to need adjusting; `reject_failed` reports are the signal.

- Podman, `podman compose` and the Quadlet unit were not run (no Podman here).

## Known gaps

- SPA navigations re-run the engine only where the Navigation API exists (Chromium).
- No Global Privacy Control header.
- Grades are not split by region.
- Multi-user deployments need per-install anonymous credentials (see SECURITY.md).
