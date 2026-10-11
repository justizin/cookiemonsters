import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

from conftest import report

from cookiemonsters import clock

ROOT = Path(__file__).resolve().parents[2]


def post(c, *reports, token=None, **kw):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return c.post("/v1/reports", json={"reports": list(reports)}, headers=headers, **kw)


def test_health_and_meta(client):
    assert client.get("/healthz").json()["ok"] is True
    m = client.get("/v1/meta").json()
    assert m["schema_version"] == 1 and m["scoring_version"] == 1
    assert m["lookup_prefix_hex"] == 1 and m["report_token_required"] is False


def test_report_roundtrip_and_normalisation(client):
    r = post(client, report(site="https://shop.example.co.uk/basket?x=1"))
    assert r.status_code == 202, r.text
    assert r.json() == {"accepted": 1, "rejected": []}
    rec = client.get("/v1/sites/WWW.example.co.uk").json()
    assert rec["site"] == "example.co.uk"
    assert rec["grade"] == "A" and rec["score"] == 95 and rec["friction"] == 5
    assert rec["confidence"] == "low" and rec["reports"] == 1
    assert rec["cmps"] == {"onetrust": 1.0}
    assert rec["first_seen_week"] == rec["last_seen_week"] == clock.iso_week(clock.utcnow().date())
    assert 0.5 < rec["rank_signal"] < 0.95


def test_median_over_reports(client):
    post(
        client,
        report(),
        report(),
        report(outcome="rejected_in_settings", clicks=3, flags=["pre_ticked"]),
        report(outcome="rejected_by_toggles", clicks=12, toggles=10, flags=["legitimate_interest", "banner_reappeared"]),
    )
    rec = client.get("/v1/sites/example.com").json()
    assert rec["friction"] == 21 and rec["grade"] == "B" and rec["reports"] == 4
    assert rec["outcomes"] == {"rejected_first_layer": 0.5, "rejected_in_settings": 0.25, "rejected_by_toggles": 0.25}
    assert rec["flags"] == {"pre_ticked": 0.25, "legitimate_interest": 0.25, "banner_reappeared": 0.25}
    assert rec["dominant_flags"] == []


def test_invalid_sites_are_rejected_individually(client):
    r = post(client, report(site="localhost"), report(site="10.0.0.1"), report(site="co.uk"), report(site="fine.org"))
    body = r.json()
    assert r.status_code == 202 and body["accepted"] == 1
    assert [x["index"] for x in body["rejected"]] == [0, 1, 2]
    assert client.get("/v1/sites/fine.org").status_code == 200


def test_strict_schema_and_no_echo(client):
    marker = "SECRET-VALUE-123"
    for bad in (
        report(extra_field=marker),
        report(outcome=marker),
        report(clicks=51),
        report(flags=["pre_ticked", "pre_ticked"]),
        report(cmp="Bad Name!" + marker),
        report(client={"extension_version": marker, "rules_version": "2026-10-11", "browser": "chrome"}),
    ):
        r = post(client, bad)
        assert r.status_code == 422, bad
        assert marker not in r.text
    assert client.post("/v1/reports", json={"reports": []}).status_code == 422
    assert client.post("/v1/reports", json={"reports": [report()] * 26}).status_code == 422


def test_body_limits_and_content_type(client):
    big = json.dumps({"reports": [report()], "pad": "x" * 70000})
    assert client.post("/v1/reports", content=big, headers={"Content-Type": "application/json"}).status_code == 413
    assert client.post("/v1/reports", content=b"site=x", headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 415


def test_report_token(make_client):
    c = make_client(report_token="s3cret")
    assert post(c, report()).status_code == 401
    assert post(c, report(), token="wrong").status_code == 401
    assert post(c, report(), token="s3cret").status_code == 202
    assert c.get("/v1/meta").json()["report_token_required"] is True


def test_rate_limits(make_client):
    c = make_client(rate_per_site_day=2, rate_per_day=5)
    r = post(c, report(), report(), report()).json()
    assert r["accepted"] == 2 and r["rejected"][0]["reason"].startswith("too many")
    assert post(c, report(site="a.org"), report(site="b.org")).json()["accepted"] == 2  # 5 today
    refused = post(c, report(site="c.org"))  # 6th
    assert refused.status_code == 429 and refused.headers["retry-after"]
    assert c.get("/v1/sites/c.org").status_code == 404  # a refused batch folds nothing


def test_nothing_identifying_is_stored(client):
    post(client, report(), report(site="other.org"), report())
    dump = "\n".join(sqlite3.connect(client.db_path).iterdump())
    assert "testclient" not in dump  # the client address as TestClient presents it
    rows = sqlite3.connect(client.db_path).execute("SELECT count(*) FROM site_week").fetchone()[0]
    assert rows == 2  # one aggregate per site and week, no per-report rows
    tables = {r[0] for r in sqlite3.connect(client.db_path).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"site_week", "sites", "day_salt", "rate"}


def test_maintenance_deletes_old_salts_and_old_weeks(client):
    post(client, report())
    db = sqlite3.connect(client.db_path, isolation_level=None)
    db.execute("INSERT INTO day_salt VALUES ('2000-01-01', 'aa')")
    db.execute("INSERT INTO rate VALUES ('2000-01-01', 'k', 3)")
    db.execute("INSERT INTO site_week (site, week, scoring_version, n, hist, outcomes, flags, cmps) VALUES ('old.org', '2000-W01', 1, 1, '{\"80\":1}', '{}', '{}', '{}')")
    asyncio.run(client.svc.maintain())
    assert db.execute("SELECT count(*) FROM day_salt WHERE day < '2001'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM rate WHERE day < '2001'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM site_week WHERE site = 'old.org'").fetchone()[0] == 0


def test_window_excludes_old_weeks(client):
    post(client, report(outcome="accept_only", clicks=0))
    db = sqlite3.connect(client.db_path, isolation_level=None)
    db.execute("INSERT INTO site_week (site, week, scoring_version, n, hist, outcomes, flags, cmps) VALUES ('example.com', '2000-W01', 1, 9, '{\"0\":9}', '{\"no_banner\":9}', '{}', '{}')")
    post(client, report(outcome="accept_only", clicks=0))
    rec = client.get("/v1/sites/example.com").json()
    assert rec["reports"] == 2 and rec["grade"] == "F"


def test_private_lookup_by_prefix(client):
    post(client, report(site="example.com"), report(site="example.org", outcome="accept_only", clicks=0))
    h = hashlib.sha256(b"example.com").hexdigest()
    for n in (1, 2, 4):
        body = client.get(f"/v1/lookup/{h[:n]}").json()
        assert body["prefix"] == h[:n]
        match = [s for s in body["sites"] if s["site"] == "example.com"]
        assert match and match[0]["grade"] == "A"
        assert set(match[0]) == {"site", "grade", "score", "confidence", "reports", "dominant_flags"}
    other = "0" if h[0] != "0" else "1"
    assert all(s["site"] != "example.com" for s in client.get(f"/v1/lookup/{other}").json()["sites"])
    for bad in ("", "abcde", "XYZ", "g1"):
        assert client.get(f"/v1/lookup/{bad}").status_code in (400, 404)


def test_prefix_length_grows_with_known_sites(client):
    svc = client.svc

    async def count(_):
        return n

    svc.store.count_sites = count
    for n, want in ((0, 1), (319, 1), (5120, 2), (81920, 3), (10**7, 4)):
        assert asyncio.run(svc.prefix_length()) == want, n


def test_publish_threshold(make_client):
    c = make_client(publish_min_reports=2)
    post(c, report())
    assert c.get("/v1/sites/example.com").status_code == 404
    assert c.get("/v1/feed").json()["items"] == []
    post(c, report())
    assert c.get("/v1/sites/example.com").json()["reports"] == 2


def test_feed_pagination_and_jsonl(client):
    sites = [f"site{i:02d}.com" for i in range(7)]
    post(client, *[report(site=s) for s in sites])
    seen, cursor = [], ""
    while True:
        page = client.get("/v1/feed", params={"cursor": cursor, "limit": 3}).json()
        seen += [r["site"] for r in page["items"]]
        if not page["next_cursor"]:
            break
        cursor = page["next_cursor"]
    assert seen == sites
    lines = client.get("/v1/feed.jsonl").text.strip().splitlines()
    assert [json.loads(x)["site"] for x in lines] == sites
    assert client.get("/v1/feed", params={"since": "2999-W01"}).json()["items"] == []
    assert client.get("/v1/feed", params={"since": "nonsense"}).status_code == 400


def test_feed_records_match_schema(client):
    from cookiemonsters.models import SiteRecord

    post(client, report(), report(site="x.org", outcome="consent_or_pay", clicks=0, flags=["tracking_before_choice"]))
    for line in client.get("/v1/feed.jsonl").text.strip().splitlines():
        SiteRecord.model_validate_json(line)
    schema = client.get("/v1/schema").json()
    assert "site_record" in schema and "report_batch" in schema


def test_leaderboard_and_index(client):
    post(client, report(site="nice.org"), report(site="nasty.com", outcome="accept_only", clicks=0))
    worst = client.get("/v1/leaderboard").json()["items"]
    assert [r["site"] for r in worst] == ["nasty.com", "nice.org"]
    best = client.get("/v1/leaderboard", params={"order": "best"}).json()["items"]
    assert best[0]["site"] == "nice.org"
    page = client.get("/")
    assert page.status_code == 200 and "nasty.com" in page.text and "<script" not in page.text


def test_html_is_escaped(client):
    # cmp slugs and sites are validated, so nothing unescaped can reach the page; check escaping anyway
    from cookiemonsters.app import _leaderboard_html

    out = _leaderboard_html([{"grade": "F", "site": "<b>x</b>", "score": 1, "reports": 1, "dominant_flags": ["<i>"]}], [])
    assert "<b>x</b>" not in out and "&lt;b&gt;" in out


def test_privacy_text_served_and_in_sync(client):
    md = client.get("/v1/privacy", params={"format": "md"}).text
    assert md == (ROOT / "shared/privacy.md").read_text()
    assert md in (ROOT / "docs/PRIVACY.md").read_text()
    html = client.get("/v1/privacy").text
    assert "What could identify you" in html
    options = (ROOT / "extension/src/options/options.html").read_text()
    assert "What could identify you" in options


def test_security_headers_and_cors(client):
    r = client.get("/v1/meta")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["access-control-allow-origin"] == "*"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    pre = client.options("/v1/reports", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "POST" not in pre.headers.get("access-control-allow-methods", "")
    w = post(client, report())
    assert w.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in w.headers


def test_unknown_site_404_and_invalid_400(client):
    assert client.get("/v1/sites/never-reported.com").status_code == 404
    assert client.get("/v1/sites/localhost").status_code == 400
