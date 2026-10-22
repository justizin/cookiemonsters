#!/usr/bin/env python3
"""Record before/after videos of the extension on the demo sites.

Each scenario is recorded twice in a fresh browser profile: once without the
extension and once with it. The whole screen (an X display, normally Xvfb) is
captured with ffmpeg, so the toolbar and the extension's badge are in the shot.
Every run is also checked: what the page saw clicked, and whether the banner is
still showing at the end.

  Xvfb :99 -screen 0 1280x800x24 &      # or run under xvfb-run
  DISPLAY=:99 python extension/demo/record.py chrome  --out demo-videos
  DISPLAY=:99 python extension/demo/record.py firefox --out demo-videos \\
      --firefox /path/to/firefox --geckodriver /path/to/geckodriver

Chrome uses Playwright's Chromium (pip install playwright). Firefox uses Selenium
(pip install selenium) with a stock Firefox and geckodriver; the extension is
installed as a temporary add-on. Output: one clip per run, one side-by-side
video per scenario, one combined video per browser, and results.json.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXT = HERE.parent
SITES = HERE / "sites"
W, H = 1280, 800
# Where the extension's toolbar button sits in a 1280x800 window: x, y, w, h (magnified in the video).
BADGE_BOX = {"chrome": (1112, 42, 64, 40), "firefox": (1188, 44, 64, 40)}
CLIP_SECONDS = 11  # long enough for the 4 s 'did the banner come back?' watch and the badge
FF_UUID = "4c6f6f6b-6965-4d6f-6e73-746572730001"
FF_ID = "cookiemonsters@cookiemonsters.local"

SCENARIOS = [
    {
        "key": "news", "host": "news.daily-fixture.localhost", "path": "news.html",
        "title": "One-click 'Reject All' (OneTrust-style banner)",
        "with": ["reject"],
    },
    {
        "key": "shop", "host": "shop.fixture-outfitters.localhost", "path": "shop.html",
        "title": "No reject button: opens settings, switches off pre-ticked categories, saves",
        "with": ["settings", "save:0000"],
    },
    {
        "key": "zeitung", "host": "www.tageblatt.localhost", "path": "zeitung.html",
        "title": "German dialog, no known CMP: heuristics find Einstellungen, untick, Auswahl speichern",
        "with": ["settings", "save:10000"],
    },
    {
        "key": "forum", "host": "forum.fixture-forum.localhost", "path": "forum.html",
        "title": "Accept-only banner: nothing is clicked, site graded F",
        "with": [],
    },
]
BANNER_JS = "() => [...document.querySelectorAll('.cm-bar, .cm-modal')].some(e => e.getBoundingClientRect().height > 0)"


# ---------------------------------------------------------------------------- helpers

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve() -> tuple[http.server.ThreadingHTTPServer, int]:
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(SITES)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


class Recorder:
    def __init__(self, path: Path):
        self.path = path
        self.proc = None

    def __enter__(self):
        display = os.environ.get("DISPLAY")
        if not display:
            raise SystemExit("DISPLAY is not set; run under Xvfb (see the docstring)")
        self.proc = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "x11grab", "-draw_mouse", "0",
             "-video_size", f"{W}x{H}", "-framerate", "25", "-i", display,
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-t", str(CLIP_SECONDS + 4), str(self.path)],
            stdin=subprocess.PIPE,
        )
        time.sleep(0.6)
        return self

    def __exit__(self, *exc):
        try:
            self.proc.communicate(b"q", timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def build(target: str) -> Path:
    subprocess.run([sys.executable, str(EXT / "build.py"), target], check=True, stdout=subprocess.DEVNULL)
    return EXT / "dist" / target


def check(sc: dict, with_ext: bool, events: list, banner_left: bool) -> dict:
    want = sc["with"] if with_ext else []
    clicked_accept = any(e == "accept" for e in events)
    if with_ext:
        ok = events == want and not clicked_accept and (banner_left == (sc["key"] == "forum"))
    else:
        ok = events == [] and banner_left
    return {"scenario": sc["key"], "extension": with_ext, "events": events, "expected": want,
            "banner_still_showing": banner_left, "ok": ok}


# ---------------------------------------------------------------------------- Chrome

def chrome_extension_id(path: Path) -> str:
    digest = hashlib.sha256(str(path).encode()).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def run_chrome(out: Path, port: int) -> list[dict]:
    from playwright.sync_api import sync_playwright

    ext = build("chrome").resolve()
    ext_id = chrome_extension_id(ext)
    results = []
    with sync_playwright() as p:
        for sc in SCENARIOS:
            for with_ext in (False, True):
                profile = Path(tempfile.mkdtemp(prefix="cm-chrome-"))
                (profile / "Default").mkdir()
                # Pin the extension so its badge is visible in the toolbar.
                (profile / "Default" / "Preferences").write_text(json.dumps({"extensions": {"pinned_extensions": [ext_id]}}))
                args = [f"--window-size={W},{H}", "--window-position=0,0",
                        "--no-first-run", "--no-default-browser-check", "--disable-search-engine-choice-screen", "--test-type",
                        "--hide-crash-restore-bubble"]
                if with_ext:
                    args += [f"--disable-extensions-except={ext}", f"--load-extension={ext}"]
                ctx = p.chromium.launch_persistent_context(
                    str(profile), headless=False, channel="chromium", args=args, no_viewport=True,
                    ignore_default_args=["--enable-automation", "--disable-extensions"],
                )
                sw = None
                if with_ext:
                    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=15000)
                    sw.evaluate("() => chrome.storage.local.set({settings: {serverUrl: '', reporting: false, lookups: false, token: '', paused: false, disabledSites: [], allowReserved: true}})")
                    # First install opens the settings page; let it, then close it.
                    deadline = time.time() + 5
                    while time.time() < deadline and not any(pg.url.startswith("chrome-extension://") for pg in ctx.pages):
                        time.sleep(0.2)
                # Record in a fresh tab so the address bar is not focused/highlighted.
                page = ctx.new_page()
                for pg in list(ctx.pages):
                    if pg is not page:
                        pg.close()
                page.goto("about:blank")
                time.sleep(1.0)
                clip = out / f"chrome_{sc['key']}_{'with' if with_ext else 'without'}.mp4"
                url = f"http://{sc['host']}:{port}/{sc['path']}"
                with Recorder(clip):
                    page.goto(url)
                    time.sleep(CLIP_SECONDS)
                events = page.evaluate("window.__events || []")
                banner_left = page.evaluate(BANNER_JS)
                r = check(sc, with_ext, events, banner_left)
                if sw is not None:
                    r["extension_state"] = sw.evaluate(
                        """async (u) => { const t = (await chrome.tabs.query({})).find(t => t.url === u);
                           if (!t) return null; const e = (await chrome.storage.session.get('tab:' + t.id))['tab:' + t.id];
                           return e ? {site: e.site, outcome: e.result.outcome, clicks: e.result.clicks,
                                       toggles: e.result.toggles_unticked, flags: e.result.flags, cmp: e.result.cmp,
                                       grade: e.localGrade, badge: await chrome.action.getBadgeText({tabId: t.id})} : null; }""",
                        url,
                    )
                r["clip"] = clip.name
                results.append(r)
                print(json.dumps(r))
                ctx.close()
                shutil.rmtree(profile, ignore_errors=True)
    return results


# ---------------------------------------------------------------------------- Firefox

def run_firefox(out: Path, port: int, firefox: str, geckodriver: str) -> list[dict]:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.service import Service

    build("firefox")
    xpi = next((EXT / "dist").glob("cookiemonsters-firefox-*.zip"))
    results = []
    for sc in SCENARIOS:
        for with_ext in (False, True):
            opts = webdriver.FirefoxOptions()
            opts.binary_location = firefox
            prefs = {
                "network.dns.localDomains": ",".join(s["host"] for s in SCENARIOS),
                "dom.security.https_first": False,
                "dom.security.https_first_schemeless": False,
                "browser.shell.checkDefaultBrowser": False,
                "browser.aboutwelcome.enabled": False,
                "browser.startup.homepage_override.mstone": "ignore",
                "datareporting.policy.dataSubmissionEnabled": False,
                "datareporting.policy.dataSubmissionPolicyBypassNotification": True,
                "toolkit.telemetry.reportingpolicy.firstRun": False,
                "browser.tabs.warnOnClose": False,
                "extensions.webextensions.uuids": json.dumps({FF_ID: FF_UUID}),
                "network.proxy.type": 0,
            }
            for k, v in prefs.items():
                opts.set_preference(k, v)
            driver = webdriver.Firefox(options=opts, service=Service(geckodriver, log_output=subprocess.DEVNULL,
                                                                   service_args=["--allow-system-access"]))  # needed to drive the extension's settings page
            driver.set_window_rect(0, 0, W, H)
            if with_ext:
                main_tab = driver.current_window_handle
                driver.install_addon(str(xpi), temporary=True)
                # The extension opens its settings page on install (Firefox reuses the empty
                # tab for it); use it to allow .localhost/.test names for the badge.
                deadline = time.time() + 10
                options_tab = None
                while time.time() < deadline and options_tab is None:
                    for h in driver.window_handles:
                        driver.switch_to.window(h)
                        if driver.current_url.startswith("moz-extension://"):
                            options_tab = h
                            break
                    time.sleep(0.3)
                if options_tab is None:
                    raise RuntimeError("extension settings page did not open after install")
                driver.find_element(By.ID, "allowReserved").click()
                driver.find_element(By.ID, "save").click()
                time.sleep(0.5)
                options_url = driver.current_url
                if options_tab != main_tab:
                    driver.close()
                driver.switch_to.window(main_tab)
            driver.get("about:blank")
            time.sleep(1.0)
            clip = out / f"firefox_{sc['key']}_{'with' if with_ext else 'without'}.mp4"
            with Recorder(clip):
                driver.get(f"http://{sc['host']}:{port}/{sc['path']}")
                time.sleep(CLIP_SECONDS)
            events = driver.execute_script("return window.__events || []")
            banner_left = driver.execute_script("return (" + BANNER_JS + ")()")
            r = check(sc, with_ext, events, banner_left)
            if with_ext:
                page_url = driver.current_url
                driver.switch_to.new_window("tab")
                driver.get(options_url)
                r["extension_state"] = driver.execute_async_script(
                    """const cb = arguments[arguments.length - 1]; (async () => {
                         const t = (await browser.tabs.query({})).find(t => t.url === arguments[0]);
                         if (!t) return cb(null);
                         const e = (await browser.storage.session.get('tab:' + t.id))['tab:' + t.id];
                         cb(e ? {site: e.site, outcome: e.result.outcome, clicks: e.result.clicks,
                                 toggles: e.result.toggles_unticked, flags: e.result.flags, cmp: e.result.cmp,
                                 grade: e.localGrade, badge: await browser.action.getBadgeText({tabId: t.id})} : null);
                       })()""",
                    page_url,
                )
            r["clip"] = clip.name
            results.append(r)
            print(json.dumps(r))
            driver.quit()
    return results


# ---------------------------------------------------------------------------- composing

def font_arg() -> str:
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        if Path(f).exists():
            return f"fontfile='{f}'"
    return "font='Sans'"


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "’").replace(":", "\\:").replace(",", "\\,").replace("%", "\\%")


def side_by_side(out: Path, browser: str, sc: dict) -> Path:
    a = out / f"{browser}_{sc['key']}_without.mp4"
    b = out / f"{browser}_{sc['key']}_with.mp4"
    dst = out / f"{browser}_{sc['key']}_side_by_side.mp4"
    f = font_arg()
    label = lambda t, color: (  # noqa: E731
        f"scale=960:600,pad=960:660:0:60:color=0x111111,"
        f"drawtext={f}:text='{esc(t)}':fontcolor={color}:fontsize=26:x=(w-text_w)/2:y=17"
    )
    title = f"{browser.capitalize()} — {sc['title']}"
    bx, by, bw, bh = BADGE_BOX[browser]
    graph = (
        f"[0:v]trim=0:{CLIP_SECONDS},setpts=PTS-STARTPTS,{label('Without cookiemonsters', '0xff8a80')}[l];"
        f"[1:v]trim=0:{CLIP_SECONDS},setpts=PTS-STARTPTS,split[r0][b0];"
        f"[b0]crop={bw}:{bh}:{bx}:{by},scale={bw * 3}:{bh * 3}:flags=lanczos,pad={bw * 3 + 8}:{bh * 3 + 8}:4:4:color=0x9be7a0[badge];"
        f"[r0]{label('With cookiemonsters', '0x9be7a0')}[r1];"
        f"[r1][badge]overlay=W-w-16:H-h-16[r];"
        f"[l][r]hstack=2,pad=1920:720:0:60:color=0x000000,"
        f"drawtext={f}:text='{esc(title)}':fontcolor=white:fontsize=24:x=(w-text_w)/2:y=18[v]"
    )
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(a), "-i", str(b),
                    "-filter_complex", graph, "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "23", "-pix_fmt", "yuv420p", str(dst)], check=True)
    return dst


def slow_replay(out: Path, browser: str, sc: dict, start: float = 1.4, length: float = 3.2, factor: float = 2.0) -> Path:
    src = out / f"{browser}_{sc['key']}_with.mp4"
    dst = out / f"{browser}_{sc['key']}_with_slow.mp4"
    f = font_arg()
    graph = (
        f"[0:v]trim={start}:{start + length},setpts=(PTS-STARTPTS)*{factor},fps=25,scale=1152:720,"
        f"pad=1920:720:768:0:color=0x111111,"
        f"drawtext={f}:text='With cookiemonsters':fontcolor=0x9be7a0:fontsize=34:x=40:y=280,"
        f"drawtext={f}:text='replay at 1/{factor:g} speed':fontcolor=white:fontsize=26:x=40:y=332,"
        f"drawtext={f}:text='{esc(browser.capitalize())}':fontcolor=0xaaaaaa:fontsize=22:x=40:y=380[v]"
    )
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                    "-filter_complex", graph, "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "23", "-pix_fmt", "yuv420p", str(dst)], check=True)
    return dst


def concat(out: Path, browser: str, parts: list[Path]) -> Path:
    lst = out / f"{browser}_list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    dst = out / f"cookiemonsters_{browser}_demo.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(dst)], check=True)
    lst.unlink()
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("browser", choices=["chrome", "firefox"])
    ap.add_argument("--out", default="demo-videos")
    ap.add_argument("--firefox", default=shutil.which("firefox") or "firefox")
    ap.add_argument("--geckodriver", default=shutil.which("geckodriver") or "geckodriver")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    httpd, port = serve()
    try:
        if args.browser == "chrome":
            results = run_chrome(out, port)
        else:
            results = run_firefox(out, port, args.firefox, args.geckodriver)
    finally:
        httpd.shutdown()
    parts = []
    for sc in SCENARIOS:
        parts.append(side_by_side(out, args.browser, sc))
        if sc["with"]:  # nothing to replay when the extension (correctly) clicks nothing
            parts.append(slow_replay(out, args.browser, sc))
    final = concat(out, args.browser, parts)
    (out / f"results_{args.browser}.json").write_text(json.dumps(results, indent=2) + "\n")
    bad = [r for r in results if not r["ok"]]
    print(f"{final}  —  {len(results) - len(bad)}/{len(results)} runs as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
