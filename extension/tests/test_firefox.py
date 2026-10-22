"""The packaged Firefox build in a real Firefox (Selenium + geckodriver).

Skipped unless FIREFOX and GECKODRIVER point at binaries, e.g.
  FIREFOX=/path/to/firefox GECKODRIVER=/path/to/geckodriver python -m pytest extension/tests/test_firefox.py
Needs a display (headless works). This caught two Firefox-only bugs the Chromium
tests could not: content-script globals read from `window` instead of `globalThis`,
and the settings page's messages being refused because it runs in a tab.
"""

from __future__ import annotations

import functools
import http.server
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

webdriver = pytest.importorskip("selenium.webdriver")
FIREFOX, GECKODRIVER = os.environ.get("FIREFOX"), os.environ.get("GECKODRIVER")
pytestmark = pytest.mark.skipif(not (FIREFOX and GECKODRIVER), reason="set FIREFOX and GECKODRIVER to run")

HERE = Path(__file__).resolve().parent
EXT = HERE.parent


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def port():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(HERE / "fixtures")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


@pytest.fixture(scope="module")
def driver():
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.service import Service

    subprocess.run([sys.executable, str(EXT / "build.py"), "firefox"], check=True, capture_output=True)
    xpi = next((EXT / "dist").glob("cookiemonsters-firefox-*.zip"))
    opts = webdriver.FirefoxOptions()
    opts.binary_location = FIREFOX
    if not os.environ.get("DISPLAY"):
        opts.add_argument("-headless")
    for k, v in {"dom.security.https_first": False, "browser.aboutwelcome.enabled": False,
                 "datareporting.policy.dataSubmissionEnabled": False}.items():
        opts.set_preference(k, v)
    d = webdriver.Firefox(options=opts, service=Service(GECKODRIVER, log_output=subprocess.DEVNULL,
                                                        service_args=["--allow-system-access"]))
    d.install_addon(str(xpi), temporary=True)
    # The settings page opens on install (Firefox reuses the empty tab).
    deadline = time.time() + 10
    while time.time() < deadline and not d.current_url.startswith("moz-extension://"):
        time.sleep(0.2)
    assert d.current_url.startswith("moz-extension://"), "settings page did not open on install"
    d.options_url = d.current_url
    d.find_element(By.ID, "allowReserved").click()
    d.find_element(By.ID, "save").click()
    yield d
    d.quit()


def ext_call(d, script, *args):
    """Run `script` (async, ends by calling cb) inside the extension's settings page."""
    main = d.current_window_handle
    d.switch_to.new_window("tab")
    d.get(d.options_url)
    try:
        return d.execute_async_script("const cb = arguments[arguments.length - 1];" + script, *args)
    finally:
        d.close()
        d.switch_to.window(main)


def test_firefox_rejects_and_badges(driver, port):
    url = f"http://news.alpha.localhost:{port}/onetrust_one_click.html"
    driver.get(url)
    deadline = time.time() + 15
    while time.time() < deadline and driver.execute_script("return window.__events") != ["reject"]:
        time.sleep(0.2)
    assert driver.execute_script("return window.__events") == ["reject"]
    time.sleep(5)  # the engine watches 4 s for a returning banner before reporting
    state = ext_call(driver, """(async () => {
        const t = (await browser.tabs.query({})).find(t => t.url === arguments[0]);
        const e = t && (await browser.storage.session.get('tab:' + t.id))['tab:' + t.id];
        cb(e ? {site: e.site, outcome: e.result.outcome, badge: await browser.action.getBadgeText({tabId: t.id})} : null);
    })()""", url)
    assert state == {"site": "alpha.localhost", "outcome": "rejected_first_layer", "badge": "A"}


def test_firefox_accept_only_untouched(driver, port):
    driver.get(f"http://forum.delta.localhost:{port}/accept_only.html")
    time.sleep(4)
    assert driver.execute_script("return window.__events") == []


def test_settings_page_messages_accepted(driver):
    # Regression: the settings page runs in a tab, so sender.tab is set; its messages must still be accepted.
    reply = ext_call(driver, "browser.runtime.sendMessage({type: 'cm:flush-now'}).then(cb, e => cb('ERR ' + e));")
    assert isinstance(reply, dict) and reply.get("sent") == 0
