"""The D1 executor and the Worker entry, against a fake D1 binding."""

import asyncio
import importlib
import sys
import types
from pathlib import Path

from conftest import FakeD1

from cookiemonsters.models import Report
from cookiemonsters.service import Service, Settings
from cookiemonsters.storage import Store
from cookiemonsters.storage.d1 import D1Executor

ROOT = Path(__file__).resolve().parents[2]


def mk(site, outcome="rejected_in_settings", clicks=2):
    return Report.model_validate(
        {"site": site, "outcome": outcome, "clicks": clicks, "toggles_unticked": 0, "flags": [], "cmp": "didomi",
         "client": {"extension_version": "0.1.0", "rules_version": "2026-10-11", "browser": "chrome"}}
    )


def test_d1_store_full_cycle():
    d1 = FakeD1()

    async def go():
        store = Store(D1Executor(d1))
        # The migration file applied by wrangler must create the same schema.
        sql = "\n".join(l for l in (ROOT / "api/worker/migrations/0001_init.sql").read_text().splitlines() if not l.startswith("--"))
        for stmt in filter(str.strip, sql.split(";")):
            await store.ex.execute(stmt)
        svc = Service(store, Settings())
        res = await svc.submit([mk("a.example.com"), mk("example.com")], "203.0.113.9")
        assert res["accepted"] == 2
        rec = await svc.site("example.com")
        assert rec["reports"] == 2 and rec["grade"] == "C" and rec["friction"] == 25
        assert await svc.maintain() == {"refreshed": 0}

    asyncio.run(go())
    assert d1.batches >= 2  # folding a report uses one atomic batch


def test_worker_entry_wires_env_into_asgi(monkeypatch):
    calls = {}

    async def fake_fetch(app, js_request, env):
        calls["args"] = (app, js_request, env)
        return "response"

    class WorkerEntrypoint:
        def __init__(self, env):
            self.env = env

    monkeypatch.setitem(sys.modules, "asgi", types.SimpleNamespace(fetch=fake_fetch))
    monkeypatch.setitem(sys.modules, "workers", types.SimpleNamespace(WorkerEntrypoint=WorkerEntrypoint))
    monkeypatch.syspath_prepend(str(ROOT / "api/worker/src"))
    sys.modules.pop("entry", None)
    entry = importlib.import_module("entry")

    d1 = FakeD1()
    from cookiemonsters.storage.sql import SCHEMA

    for s in SCHEMA:
        d1.db.execute(s)
    env = types.SimpleNamespace(DB=d1, CM_PUBLISH_MIN_REPORTS="1")
    worker = entry.Default(env)
    req = types.SimpleNamespace(js_object="JSREQ")
    assert asyncio.run(worker.fetch(req)) == "response"
    assert calls["args"][1:] == ("JSREQ", env)
    asyncio.run(worker.scheduled(None))


def test_app_builds_d1_service_from_scope_env():
    """When the ASGI scope carries a Worker env, requests use D1, not app.state."""
    from fastapi.testclient import TestClient

    from cookiemonsters.app import create_app
    from cookiemonsters.storage.sql import SCHEMA

    d1 = FakeD1()
    for s in SCHEMA:
        d1.db.execute(s)
    env = types.SimpleNamespace(DB=d1, CM_TRUST_CF_HEADERS="1", CM_REPORT_TOKEN="t")
    inner = create_app()

    async def app(scope, receive, send):
        scope = dict(scope, env=env)
        await inner(scope, receive, send)

    c = TestClient(app)
    body = {"reports": [{"site": "example.com", "outcome": "no_banner", "clicks": 0, "toggles_unticked": 0, "flags": [], "cmp": "none",
                         "client": {"extension_version": "0.1.0", "rules_version": "2026-10-11", "browser": "safari"}}]}
    assert c.post("/v1/reports", json=body).status_code == 401
    r = c.post("/v1/reports", json=body, headers={"Authorization": "Bearer t", "CF-Connecting-IP": "198.51.100.7"})
    assert r.status_code == 202 and r.json()["accepted"] == 1
    assert c.get("/v1/sites/example.com").json()["grade"] == "A"
    dump = "\n".join(d1.db.iterdump())
    assert "198.51.100.7" not in dump
