"""Standalone entry point: ``cookiemonsters serve`` (or ``python -m cookiemonsters serve``)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .service import Service, Settings
from .storage import Store
from .storage.sqlite import SQLiteExecutor

DEFAULT_DB = Path(os.environ.get("CM_DB_PATH", Path.home() / ".cookiemonsters" / "cookiemonsters.sqlite3"))


def build_service(db: str | Path) -> Service:
    store = Store(SQLiteExecutor(db))
    asyncio.run(store.migrate())
    return Service(store, Settings.from_env(os.environ))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cookiemonsters", description="cookiemonsters grading server (standalone)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the HTTP API locally")
    s.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1 — local only)")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--db", default=str(DEFAULT_DB), help="SQLite file (default ~/.cookiemonsters/cookiemonsters.sqlite3)")
    m = sub.add_parser("maintain", help="prune expired data and refresh stale summaries")
    m.add_argument("--db", default=str(DEFAULT_DB))
    e = sub.add_parser("export", help="write the ranking feed as JSON Lines to stdout")
    e.add_argument("--db", default=str(DEFAULT_DB))
    sub.add_parser("schema-sql", help="print the SQL schema (used to generate the D1 migration)")
    args = p.parse_args(argv)

    if args.cmd == "schema-sql":
        from .storage.sql import SCHEMA

        print(";\n\n".join(SCHEMA) + ";")
        return 0

    svc = build_service(args.db)
    if args.cmd == "serve":
        import uvicorn

        from .app import create_app

        if args.host not in ("127.0.0.1", "::1", "localhost"):
            print(f"warning: listening on {args.host}; reports reveal which sites you visit — keep this private.", file=sys.stderr)
        uvicorn.run(create_app(svc), host=args.host, port=args.port, server_header=False, access_log=False)
    elif args.cmd == "maintain":
        print(json.dumps(asyncio.run(svc.maintain(refresh_limit=100000))))
    elif args.cmd == "export":
        async def dump() -> None:
            cursor = ""
            while True:
                rows, cursor = await svc.feed(cursor, "0000-W01", 1000, 1)
                for r in rows:
                    sys.stdout.write(json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n")
                if cursor is None:
                    return
        asyncio.run(dump())
    return 0
