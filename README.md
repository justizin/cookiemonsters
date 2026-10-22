# cookiemonsters

A browser extension that refuses non-essential cookies for you — clicking "Reject all", or opening the banner's settings and switching every optional category off — and a small Python service that grades websites on how hard they made that.

- **Extension** (`extension/`): one Manifest V3 source tree built for Chrome/Edge, Firefox and Safari. Rules for 26 consent platforms plus a multilingual heuristic for everything else. Never clicks "accept", never follows a link away from the page, never hides a banner it could not refuse.
- **Grading service** (`api/`): one FastAPI app that runs **standalone on your computer** (SQLite) or **serverless on Cloudflare Workers** (Python, D1). Accepts anonymous reports, folds them into weekly per-site tallies, and publishes an A–F grade, a 0–100 score and a ranking feed a search engine could ingest.
- **Privacy**: off by default; nothing leaves the browser until you enter a server address. Grades are looked up by a short hash prefix, not by site name. The plain-language explanation of what is identifiable and why is in [docs/PRIVACY.md](docs/PRIVACY.md) and on the extension's settings page.

Branch `attempt/claude-opus-5.5` · License AGPL-3.0-or-later (Public Suffix List data: MPL-2.0).

## Quick start

```sh
# 1. grading server on your own machine (Python 3.11+; not macOS's built-in 3.9)
python3.13 -m venv .venv && source .venv/bin/activate
python -m pip install -U pip              # old pip (<22) backtracks for ages on this
pip install "./api[standalone]"
cookiemonsters serve                     # http://127.0.0.1:8787, data in ~/.cookiemonsters/

# …or in a container (Podman or Docker; see docs/DEPLOY.md#container)
podman build -t cookiemonsters .          # docker build -f Containerfile -t cookiemonsters .
podman run -d -p 127.0.0.1:8787:8787 -v cookiemonsters-data:/data cookiemonsters

# 2. build the extension
python extension/build.py                # -> extension/dist/{chrome,firefox,safari}/ and .zip files
```

Load it:

- **Chrome / Edge**: `chrome://extensions` → Developer mode → *Load unpacked* → `extension/dist/chrome`.
- **Firefox**: `about:debugging#/runtime/this-firefox` → *Load Temporary Add-on* → `extension/dist/firefox/manifest.json`. Then in the extension's settings press *Allow access to this server* (Firefox treats host access as opt-in).
- **Safari** (macOS + Xcode): `python extension/build.py safari --safari-xcode`, open the generated Xcode project, run, then enable it in Safari → Settings → Extensions. See [docs/DEPLOY.md](docs/DEPLOY.md#safari).

Then open the extension's settings, enter `http://127.0.0.1:8787`, and tick reporting and/or grade lookups. Without that, it still refuses cookies and shows a grade for the current visit — it just never talks to a server.

## Repository map

```
shared/        single sources: scoring weights, test vectors, Public Suffix List, privacy text
api/           cookiemonsters Python package (FastAPI app, scoring, storage, CLI) + tests
api/worker/    Cloudflare Python Worker entry, wrangler.toml, D1 migration
extension/     MV3 source (src/), CMP rules (rules/), per-browser manifest overlays, build.py, tests
deploy/        Podman Quadlet unit (Containerfile and compose.yaml sit at the root)
tools/         sync_generated.py (regenerates derived files), worker_sync.py, make_icons.py
docs/          DESIGN, PRIVACY, SCORING, DATA_FEED, SECURITY, DEPLOY, STATUS
```

## Tests

```sh
make test        # or, by hand:
python tools/sync_generated.py --check              # derived files up to date
python -m pytest api/tests                          # 76 API tests
node extension/tests/scoring_parity.mjs             # JS scorer + PSL == Python, same vectors
python -m pytest extension/tests                    # 48 engine tests + 2 packaged-extension end-to-end tests
                                                    # + 3 Firefox tests when FIREFOX and GECKODRIVER are set
```

The extension tests run real headless Chromium through Playwright (`pip install playwright && playwright install chromium`). The end-to-end test loads the built Chrome extension, browses fixture sites on `.test` names, reports to a live standalone API, and checks the grade comes back through the private lookup — and that no request to the server ever contained a site name except the reports themselves.

`extension/demo/record.py` records the extension in Chrome and Firefox on four demo sites, with and without the extension, and builds side-by-side videos (instructions at the top of the file).

What was and was not verified is in [docs/STATUS.md](docs/STATUS.md).
