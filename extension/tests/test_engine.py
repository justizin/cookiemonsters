"""Consent engine against fixture banners, in real headless Chromium.

The engine is pure DOM, so it is injected straight into the fixture page;
test_e2e.py covers the packaged extension.
"""

from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
FIXTURES = HERE / "fixtures"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(QuietHandler, directory=str(FIXTURES))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"no Chromium available: {exc}")
        yield b
        b.close()


def run(browser, server, name, **opts):
    page = browser.new_page()
    page.goto(f"{server}/{name}")
    page.add_script_tag(path=str(SRC / "common/generated_rules.js"))
    page.add_script_tag(path=str(SRC / "content/engine.js"))
    args = {"timeoutMs": 3000, "reappearMs": 1500, "settleMs": 100, "isTop": True}
    args.update(opts)
    result = page.evaluate("opts => CMEngine.run(opts)", args)
    events = page.evaluate("window.__events || []")
    url = page.url
    page.close()
    return result, events, url


def test_onetrust_one_click(browser, server):
    r, ev, _ = run(browser, server, "onetrust_one_click.html")
    assert r["outcome"] == "rejected_first_layer" and r["clicks"] == 1 and r["cmp"] == "onetrust"
    assert r["flags"] == [] and ev == ["reject"]


def test_onetrust_settings_and_toggles(browser, server):
    r, ev, _ = run(browser, server, "onetrust_settings.html")
    assert r["outcome"] == "rejected_by_toggles", r
    assert r["toggles_unticked"] == 2 and r["clicks"] == 4
    assert "pre_ticked" in r["flags"]
    assert ev == ["settings", "save:000"]


def test_cookiebot_decline(browser, server):
    r, ev, _ = run(browser, server, "cookiebot.html")
    assert (r["outcome"], r["cmp"], ev) == ("rejected_first_layer", "cookiebot", ["reject"])


def test_usercentrics_in_shadow_dom(browser, server):
    r, ev, _ = run(browser, server, "usercentrics_shadow.html")
    assert (r["outcome"], r["cmp"], ev) == ("rejected_first_layer", "usercentrics", ["reject"])


def test_generic_banner_with_tiny_reject(browser, server):
    r, ev, _ = run(browser, server, "generic_en_small_reject.html")
    assert (r["outcome"], r["cmp"], ev) == ("rejected_first_layer", "generic", ["reject"])
    assert r["flags"] == ["reject_less_prominent"]


def test_generic_german_settings_panel(browser, server):
    r, ev, _ = run(browser, server, "generic_de_settings.html")
    assert r["outcome"] == "rejected_by_toggles", r
    assert r["toggles_unticked"] == 3 and r["clicks"] == 5
    assert set(r["flags"]) == {"pre_ticked", "legitimate_interest"}
    assert ev == ["settings", "save:10000"]  # only the locked "Notwendig" stays on


def test_late_banner(browser, server):
    r, ev, _ = run(browser, server, "late_banner.html")
    assert r["outcome"] == "rejected_first_layer" and ev == ["reject"]


def test_accept_only_is_not_clicked(browser, server):
    r, ev, url = run(browser, server, "accept_only.html")
    assert r["outcome"] == "accept_only" and r["clicks"] == 0
    assert ev == [] and url.endswith("accept_only.html")


def test_consent_or_pay(browser, server):
    r, ev, _ = run(browser, server, "consent_or_pay.html")
    assert r["outcome"] == "consent_or_pay" and ev == []


def test_no_banner(browser, server):
    r, ev, _ = run(browser, server, "no_banner.html", timeoutMs=800)
    assert r == {"outcome": "no_banner", "clicks": 0, "toggles_unticked": 0, "flags": [], "cmp": "none", "rules_version": r["rules_version"]}


def test_no_banner_in_subframe_reports_nothing(browser, server):
    r, _, _ = run(browser, server, "no_banner.html", timeoutMs=500, isTop=False)
    assert r is None


def test_tracking_without_asking(browser, server):
    r, _, _ = run(browser, server, "tracking_no_banner.html", timeoutMs=500)
    assert r["outcome"] == "no_banner" and r["flags"] == ["tracking_before_choice"]


def test_banner_reappears(browser, server):
    r, ev, _ = run(browser, server, "reappear.html")
    assert r["outcome"] == "rejected_first_layer" and r["cmp"] == "hubspot"
    assert "banner_reappeared" in r["flags"] and ev == ["reject"]


def test_never_follows_navigating_links(browser, server):
    r, ev, url = run(browser, server, "navigating_reject.html")
    assert ev == [] and url.endswith("navigating_reject.html")
    assert r["clicks"] == 0


def test_never_clicks_accept_even_if_a_rule_points_at_it(browser, server):
    r, ev, _ = run(browser, server, "mislabelled_selector.html")
    assert ev == [] and r["clicks"] == 0 and r["outcome"] == "accept_only"


def test_sourcepoint_message_frame(browser, server):
    r, ev, _ = run(browser, server, "sp_message.html", isTop=False)
    assert (r["outcome"], r["cmp"], ev) == ("rejected_first_layer", "sourcepoint", ["reject"])


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Reject All", "reject"), ("Decline optional cookies", "reject"), ("Use necessary cookies only", "reject"),
        ("Continue without accepting →", "reject"), ("Alle ablehnen", "reject"), ("Tout refuser", "reject"),
        ("Rechazar todo", "reject"), ("Rifiuta tutto", "reject"), ("Alles weigeren", "reject"), ("Odrzuć wszystkie", "reject"),
        ("Nur notwendige Cookies", "reject"), ("Solo necessari", "reject"),
        ("Accept all", "acceptAll"), ("Alle akzeptieren", "acceptAll"), ("Tout accepter", "acceptAll"), ("Allow all", "acceptAll"),
        ("Accept", "accept"), ("OK, got it", "accept"), ("I agree", "accept"), ("Zustimmen", "accept"), ("J'accepte", "accept"),
        ("Allow selection", "save"), ("Confirm my choices", "save"), ("Auswahl speichern", "save"), ("Enregistrer", "save"),
        ("Cookie settings", "settings"), ("Manage preferences", "settings"), ("Einstellungen", "settings"), ("Personnaliser", "settings"),
        ("Privacy policy", None), ("Subscribe to newsletter", None), ("Solo per oggi", None),
    ],
)
def test_button_classifier(browser, server, text, kind):
    page = browser.new_page()
    page.goto(f"{server}/no_banner.html")
    page.add_script_tag(path=str(SRC / "common/generated_rules.js"))
    page.add_script_tag(path=str(SRC / "content/engine.js"))
    got = page.evaluate("t => { const b = document.createElement('button'); b.textContent = t; document.body.append(b); return CMEngine.classify(b); }", text)
    page.close()
    assert got == kind
