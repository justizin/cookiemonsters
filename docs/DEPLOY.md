# Running and deploying

## Standalone (recommended for one person)

```sh
pip install "./api[standalone]"
cookiemonsters serve                         # 127.0.0.1:8787, SQLite at ~/.cookiemonsters/cookiemonsters.sqlite3
cookiemonsters serve --db ./cm.sqlite3 --port 9000
cookiemonsters maintain                      # prune + refresh (also happens on the first report of each day)
cookiemonsters export > feed.jsonl           # the ranking feed
```

Environment variables (same names in the Worker):

| Variable | Default | Meaning |
|---|---|---|
| `CM_REPORT_TOKEN` | empty | If set, `POST /v1/reports` needs `Authorization: Bearer <token>`. Enter the same token in the extension. |
| `CM_PUBLISH_MIN_REPORTS` | 1 | Sites with fewer reports are hidden from every read endpoint. |
| `CM_RATE_PER_DAY` | 1000 | Reports per client per UTC day. |
| `CM_RATE_PER_SITE_DAY` | 5 | Reports per client per site per day. |
| `CM_TRUST_CF_HEADERS` | off | Take the client address from `CF-Connecting-IP` (only behind Cloudflare). |
| `CM_ALLOW_RESERVED_TLDS` | off | Accept `.test` etc. (testing only). |
| `CM_DB_PATH` | `~/.cookiemonsters/…` | Standalone database file. |

## Cloudflare Workers (Python) + D1

Prerequisites: a Cloudflare account, Node (for `wrangler`), and `uv`.

```sh
cd api/worker
python ../../tools/worker_sync.py            # copy the package next to the entry point
npx wrangler d1 create cookiemonsters        # paste the database_id into wrangler.toml
npx wrangler d1 migrations apply cookiemonsters --remote
npx wrangler secret put CM_REPORT_TOKEN      # optional, recommended
uv tool install workers-py                   # provides pywrangler, which vendors fastapi/pydantic for Pyodide
pywrangler dev                               # local test on http://localhost:8787
pywrangler deploy
```

`pywrangler` wraps `wrangler`, installing the Worker's Python dependencies from `api/worker/pyproject.toml` into `python_modules/`. Plain `npx wrangler dev` also works once `python_modules/` exists.

The daily cron (`17 3 * * *`) runs maintenance: it deletes the previous day's rate-limit salt and counters and aggregates older than the window. Workers Logs are disabled (`[observability] enabled = false`). Consider a Cloudflare rate-limiting rule on `POST /v1/reports` as a first line.

Point the extension at `https://cookiemonsters.<your-subdomain>.workers.dev`.

## Extension builds

```sh
python extension/build.py               # all three
python extension/build.py firefox       # one
```

Output: `extension/dist/<browser>/` (unpacked) and `extension/dist/cookiemonsters-<browser>-<version>.zip`.

- **Chrome / Edge**: load `dist/chrome` unpacked, or upload the zip to the Chrome Web Store / Edge Add-ons.
- **Firefox** (115+): load `dist/firefox/manifest.json` temporarily, or sign the zip with `web-ext sign`. Change `browser_specific_settings.gecko.id` in `manifests/firefox.json` to an id you own before publishing. In the settings page press *Allow access to this server*.

### Safari

Needs macOS and Xcode.

```sh
python extension/build.py safari --safari-xcode
open extension/dist/safari-xcode/cookiemonsters/cookiemonsters.xcodeproj
```

Run the app target once, then Safari → Settings → Extensions → enable cookiemonsters and grant it access to websites. For local development also enable Develop → *Allow Unsigned Extensions*. Change the bundle identifier in `build.py` before distributing.

## Regenerating derived files

Edit only the sources (`shared/*`, `extension/rules/*`, `options.template.html`, `storage/sql.py`), then:

```sh
python tools/sync_generated.py
```

To refresh the Public Suffix List, replace `shared/public_suffix_list.dat` with the current list from publicsuffix.org and re-run it.
