import sqlite3
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from cookiemonsters.app import create_app  # noqa: E402
from cookiemonsters.service import Service, Settings  # noqa: E402
from cookiemonsters.storage import Store  # noqa: E402
from cookiemonsters.storage.sqlite import SQLiteExecutor  # noqa: E402


def report(site="example.com", outcome="rejected_first_layer", clicks=1, toggles=0, flags=(), cmp="onetrust", **extra):
    r = {
        "site": site,
        "outcome": outcome,
        "clicks": clicks,
        "toggles_unticked": toggles,
        "flags": list(flags),
        "cmp": cmp,
        "client": {"extension_version": "0.1.0", "rules_version": "2026-10-11", "browser": "firefox"},
    }
    r.update(extra)
    return r


@pytest.fixture
def make_client(tmp_path):
    def make(**settings):
        store = Store(SQLiteExecutor(tmp_path / "t.sqlite3"))
        import asyncio

        asyncio.run(store.migrate())
        svc = Service(store, Settings(**settings))
        c = TestClient(create_app(svc))
        c.svc = svc
        c.db_path = tmp_path / "t.sqlite3"
        return c

    return make


@pytest.fixture
def client(make_client):
    return make_client()


class FakeD1:
    """Imitates the D1 binding API on top of sqlite3 (prepare/bind/run/all/batch)."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.batches = 0

    class Stmt:
        def __init__(self, d1, sql, params=()):
            self.d1, self.sql, self.params = d1, sql, params

        def bind(self, *params):
            for p in params:
                assert p is not None, "D1 cannot bind None"
            return FakeD1.Stmt(self.d1, self.sql, params)

        async def run(self):
            self.d1.db.execute(self.sql, self.params)
            return types.SimpleNamespace(success=True)

        async def all(self):
            rows = [dict(r) for r in self.d1.db.execute(self.sql, self.params).fetchall()]
            return types.SimpleNamespace(results=rows)

    def prepare(self, sql):
        return FakeD1.Stmt(self, sql)

    async def batch(self, stmts):
        self.batches += 1
        self.db.execute("BEGIN")
        try:
            for s in stmts:
                self.db.execute(s.sql, s.params)
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
