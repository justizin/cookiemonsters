"""End to end: the packaged Chrome build, loaded into real Chromium, browsing
fixture sites on reserved .test names, reporting to a live standalone API, and
reading grades back through the private prefix lookup."""

from __future__ import annotations

import asyncio
import functools
import http.server
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

HERE = Path(__file__).resolve().parent
EXT = HERE.parent
ROOT = EXT.parent
sys.path.insert(0, str(ROOT / "api"))

from cookiemonsters.app import create_app  # noqa: E402
from cookiemonsters.service import Service, Settings  # noqa: E402
from cookiemonsters.storage import Store  # noqa: E402
from cookiemonsters.storage.sqlite import SQLiteExecutor  # noqa: E402


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def fixture_port():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(HERE / "fixtures")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    store = Store(SQLiteExecutor(tmp_path_factory.mktemp("api") / "e2e.sqlite3"))
    t = threading.Thread(target=lambda: asyncio.run(store.migrate()))  # Playwright may own this thread's loop
    t.start()
    t.join()
    svc = Service(store, Settings(allow_reserved_tlds=True, report_token="e2e-token"))
    inner = create_app(svc)
    paths: list[str] = []

    async def app(scope, receive, send):
        if scope["type"] == "http":
            paths.append(scope["method"] + " " + scope["path"])
        await inner(scope, receive, send)

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield {"base": f"http://127.0.0.1:{port}", "paths": paths}
    server.should_exit = True


@pytest.fixture(scope="module")
def extension_dir():
    subprocess.run([sys.executable, str(EXT / "build.py"), "chrome"], check=True, capture_output=True)
    return EXT / "dist" / "chrome"


@pytest.fixture(scope="module")
def ctx(extension_dir, tmp_path_factory):
    with pw.sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                str(tmp_path_factory.mktemp("profile")),
                headless=True,
                channel="chromium",  # full Chromium in new headless mode; the headless shell cannot load extensions
                args=[
                    f"--disable-extensions-except={extension_dir}",
                    f"--load-extension={extension_dir}",
                    "--host-resolver-rules=MAP *.test 127.0.0.1",
                ],
            )
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"cannot launch Chromium with extensions: {exc}")
        sw = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker", timeout=10000)
        yield context, sw
        context.close()


def get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def visit(context, url, expect_events, timeout=15):
    page = context.new_page()
    page.goto(url)
    deadline = time.time() + timeout
    while time.time() < deadline:
        ev = page.evaluate("window.__events || []")
        frames_ev = [f.evaluate("window.__events || []") for f in page.frames[1:] if not f.is_detached()]
        if ev == expect_events or any(fe == expect_events for fe in frames_ev):
            break
        time.sleep(0.2)
    else:
        raise AssertionError(f"{url}: events {ev} {frames_ev}, wanted {expect_events}")
    return page


def tab_entry(sw, page_url, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        entry = sw.evaluate(
            """async (u) => {
                const tabs = await chrome.tabs.query({});
                const t = tabs.find(t => t.url === u);
                if (!t) return null;
                const e = (await chrome.storage.session.get('tab:' + t.id))['tab:' + t.id];
                const badge = await chrome.action.getBadgeText({tabId: t.id});
                return e ? Object.assign({badge}, e) : null;
            }""",
            page_url,
        )
        if entry:
            return entry
        time.sleep(0.2)
    raise AssertionError("no tab entry for " + page_url)


def test_extension_end_to_end(ctx, api, fixture_port):
    context, sw = ctx
    # Default: no server configured -> nothing may be sent.
    p0 = visit(context, f"http://news.alpha.test:{fixture_port}/onetrust_one_click.html", ["reject"])
    p0.close()
    assert api["paths"] == []

    sw.evaluate(
        """(base) => chrome.storage.local.set({settings: {serverUrl: base, reporting: true, lookups: true,
              token: 'e2e-token', allowReserved: true, paused: false, disabledSites: []}})""",
        api["base"],
    )

    u1 = f"http://news.alpha.test:{fixture_port}/onetrust_one_click.html"
    p1 = visit(context, u1, ["reject"])
    e1 = tab_entry(sw, u1)
    assert e1["site"] == "alpha.test" and e1["result"]["outcome"] == "rejected_first_layer"
    assert e1["badge"] == "A"

    # Cross-origin consent iframe (Sourcepoint style): the report belongs to the top-level site.
    u2 = f"http://shop.beta.test:{fixture_port}/sp_parent.html"
    p2 = visit(context, u2, ["reject"])
    e2 = tab_entry(sw, u2)
    assert e2["site"] == "beta.test" and e2["result"]["cmp"] == "sourcepoint"

    u3 = f"http://forum.delta.test:{fixture_port}/accept_only.html"
    p3 = visit(context, u3, [], timeout=1)
    time.sleep(2)
    e3 = tab_entry(sw, u3)
    assert e3["result"]["outcome"] == "accept_only" and e3["badge"] == "F"
    assert p3.evaluate("window.__events") == []  # nothing clicked

    queue = sw.evaluate("async () => (await chrome.storage.local.get('queue')).queue")
    assert set(queue) == {"alpha.test", "beta.test", "delta.test"}
    alarm = sw.evaluate("async () => await chrome.alarms.get('flush')")
    assert alarm is not None  # reports wait for a random later time

    sent = sw.evaluate("() => flush()")
    assert sent["sent"] == 3 and sent["status"] == 202

    assert get(api["base"] + "/v1/sites/alpha.test")["grade"] == "A"
    beta = get(api["base"] + "/v1/sites/beta.test")
    assert beta["cmps"] == {"sourcepoint": 1.0}
    assert get(api["base"] + "/v1/sites/delta.test")["grade"] == "F"

    # Second visit the same day: grade comes from the server, no second report is queued.
    for p in (p1, p2, p3):
        p.close()
    api["paths"].clear()
    u4 = f"http://www.alpha.test:{fixture_port}/onetrust_one_click.html"
    p4 = visit(context, u4, ["reject"])
    deadline = time.time() + 10
    while time.time() < deadline:
        e4 = tab_entry(sw, u4)
        if e4.get("server"):
            break
        time.sleep(0.2)
    if not e4.get("server"):
        dbg = sw.evaluate("async () => { const all = await chrome.storage.local.get(null); let r; try { r = await lookup('alpha.test', await settings()); } catch (e) { r = 'ERR ' + e; } return {r, keys: Object.keys(all), lk: Object.entries(all).filter(([k]) => k.startsWith('lk:') || k==='meta')}; }")
        raise AssertionError(f"no server grade; paths={api['paths']} entry={e4} direct={dbg}")
    assert e4["server"]["grade"] == "A" and e4["server"]["site"] == "alpha.test"
    queue = sw.evaluate("async () => (await chrome.storage.local.get('queue')).queue")
    assert queue == {}

    # Privacy: the server never saw the site name in a lookup, only a short hash prefix.
    lookups = [p for p in api["paths"] if p.startswith("GET /v1/lookup/")]
    assert lookups and all(len(p.rsplit("/", 1)[1]) <= 4 for p in lookups)
    assert not any("alpha" in p for p in api["paths"])
    p4.close()


def test_per_site_disable(ctx, fixture_port):
    context, sw = ctx
    sw.evaluate(
        """async () => { const s = (await chrome.storage.local.get('settings')).settings;
             s.disabledSites = ['epsilon.test']; await chrome.storage.local.set({settings: s}); }"""
    )
    page = context.new_page()
    page.goto(f"http://epsilon.test:{fixture_port}/onetrust_one_click.html")
    time.sleep(3)
    assert page.evaluate("window.__events") == []
    assert page.is_visible("#onetrust-banner-sdk")
    page.close()
