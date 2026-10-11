"""FastAPI app shared by the standalone server and the Cloudflare Worker.

The standalone server puts a Service on ``app.state.service``. In the Worker,
the ASGI bridge puts the Worker ``env`` into ``scope["env"]`` and a Service is
built around the D1 binding for that request.
"""

from __future__ import annotations

import html
import json
import re
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import ValidationError

from . import __version__, clock, mdlite, scoring
from ._generated import PRIVACY_MD
from .domains import InvalidSite
from .models import SCHEMA_VERSION, ReportBatch, SiteRecord
from .service import RateLimited, Service, Settings
from .storage import Store
from .storage.d1 import D1Executor

MAX_BODY = 64 * 1024
PREFIX_RE = re.compile(r"^[0-9a-f]{1,4}$")


def _service(request: Request) -> Service:
    env = request.scope.get("env")
    if env is not None:  # Cloudflare Worker
        def get(name: str) -> str | None:
            v = getattr(env, name, None)
            return None if v is None else str(v)

        svc = Service(Store(D1Executor(env.DB)), Settings.from_env(get))
        return svc
    return request.app.state.service


def _client_ip(request: Request, svc: Service) -> str:
    if svc.settings.trust_cf_headers:
        ip = request.headers.get("cf-connecting-ip")
        if ip:
            return ip
    return request.client.host if request.client else "unknown"


def create_app(service: Service | None = None) -> FastAPI:
    app = FastAPI(
        title="cookiemonsters",
        version=__version__,
        description="Accepts anonymous cookie-banner friction reports and publishes per-site grades.",
        docs_url="/docs",
        redoc_url=None,
    )
    if service is not None:
        app.state.service = service

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method == "POST":
            length = request.headers.get("content-length")
            if length is None or not length.isdigit():
                return JSONResponse({"detail": "content-length required"}, status_code=411)
            if int(length) > MAX_BODY:
                return JSONResponse({"detail": "body too large"}, status_code=413)
            if not request.headers.get("content-type", "").startswith("application/json"):
                return JSONResponse({"detail": "application/json required"}, status_code=415)
        if request.method == "OPTIONS":
            # Read endpoints need no preflight; write endpoint deliberately gets none,
            # so ordinary web pages cannot submit reports from a visitor's browser.
            return Response(status_code=204, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET"})
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'")
        if request.method == "GET":
            response.headers.setdefault("Access-Control-Allow-Origin", "*")
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError):
        # Do not echo the submitted values back; only where the problem is.
        errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "invalid")} for e in exc.errors()]
        return JSONResponse({"detail": errors[:20]}, status_code=422)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "version": __version__}

    @app.get("/v1/meta")
    async def meta(request: Request):
        svc = _service(request)
        return JSONResponse(
            {
                "version": __version__,
                "schema_version": SCHEMA_VERSION,
                "scoring_version": scoring.scoring_version(),
                "window_weeks": svc.window,
                "lookup_prefix_hex": await svc.prefix_length(),
                "publish_min_reports": svc.settings.publish_min_reports,
                "report_token_required": bool(svc.settings.report_token),
            },
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.post("/v1/reports", status_code=202)
    async def post_reports(request: Request):
        svc = _service(request)
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else None
        if not svc.token_ok(token):
            raise HTTPException(401, "missing or wrong report token")
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "body too large")
        try:
            batch = ReportBatch.model_validate_json(raw)
        except ValidationError as exc:
            errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "invalid")} for e in exc.errors()]
            return JSONResponse({"detail": errors[:20]}, status_code=422)
        try:
            result = await svc.submit(batch.reports, _client_ip(request, svc))
        except RateLimited:
            return JSONResponse({"detail": "rate limit"}, status_code=429, headers={"Retry-After": "3600"})
        return JSONResponse(result, status_code=202)

    @app.get("/v1/lookup/{prefix}")
    async def lookup(prefix: str, request: Request):
        """Private grade lookup: the client sends only the first few hex characters of
        SHA-256(site) and picks its own site out of the bucket that comes back."""
        if not PREFIX_RE.match(prefix):
            raise HTTPException(400, "prefix must be 1-4 lowercase hex characters")
        svc = _service(request)
        sites = await svc.lookup(prefix)
        body = {"prefix": prefix, "sites": [_compact(r) for r in sites]}
        return JSONResponse(body, headers={"Cache-Control": "public, max-age=300"})

    @app.get("/v1/sites/{site}", response_model=SiteRecord)
    async def get_site(site: str, request: Request):
        svc = _service(request)
        try:
            rec = await svc.site(site)
        except InvalidSite as exc:
            raise HTTPException(400, str(exc))
        if rec is None:
            raise HTTPException(404, "no grade for this site")
        return JSONResponse(rec, headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/v1/feed")
    async def feed(
        request: Request,
        cursor: str = Query("", max_length=253),
        since: str = Query("0000-W01", description="Only sites seen in or after this ISO week"),
        limit: int = Query(500, ge=1, le=1000),
        min_reports: int = Query(1, ge=1, le=1_000_000),
    ):
        svc = _service(request)
        since_week = _week_or_400(since)
        rows, nxt = await svc.feed(cursor.lower(), since_week, limit, min_reports)
        return JSONResponse(
            {"schema_version": SCHEMA_VERSION, "items": rows, "next_cursor": nxt},
            headers={"Cache-Control": "public, max-age=900"},
        )

    @app.get("/v1/feed.jsonl")
    async def feed_jsonl(request: Request, since: str = Query("0000-W01"), min_reports: int = Query(1, ge=1)):
        svc = _service(request)
        since_week = _week_or_400(since)

        async def lines() -> AsyncIterator[bytes]:
            cursor = ""
            while True:
                rows, nxt = await svc.feed(cursor, since_week, 1000, min_reports)
                for r in rows:
                    yield (json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n").encode()
                if nxt is None:
                    return
                cursor = nxt

        return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"Cache-Control": "public, max-age=900"})

    @app.get("/v1/leaderboard")
    async def leaderboard(request: Request, order: str = Query("worst", pattern="^(worst|best)$"), limit: int = Query(50, ge=1, le=200)):
        svc = _service(request)
        return {"order": order, "items": await svc.leaderboard(order == "worst", limit)}

    @app.get("/v1/schema")
    async def schema():
        return {"site_record": SiteRecord.model_json_schema(), "report_batch": ReportBatch.model_json_schema()}

    @app.get("/v1/privacy")
    async def privacy(format: str = Query("html", pattern="^(html|md)$")):
        text = PRIVACY_MD
        if format == "md":
            return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")
        return HTMLResponse(_page("What cookiemonsters knows about you", mdlite.to_html(text)))

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        svc = _service(request)
        worst = await svc.leaderboard(True, 25)
        best = await svc.leaderboard(False, 25)
        return HTMLResponse(_page("cookiemonsters", _leaderboard_html(worst, best)))

    return app


def _week_or_400(s: str) -> str:
    if s == "0000-W01":
        return s
    try:
        return clock.parse_week(s)
    except (ValueError, IndexError):
        raise HTTPException(400, "since must be an ISO week like 2026-W41")


def _compact(r: dict) -> dict:
    return {k: r[k] for k in ("site", "grade", "score", "confidence", "reports", "dominant_flags")}


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>"
        "body{font:16px/1.5 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#1d1d1f;background:#fbfaf7}"
        "@media(prefers-color-scheme:dark){body{color:#ecebe6;background:#18181a}a{color:#9ec5ff}}"
        "table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:.25rem .5rem;border-bottom:1px solid #8884}"
        ".g{font-weight:700;width:2rem}.gA{color:#1a7f37}.gB{color:#4d8f1d}.gC{color:#b08800}.gD{color:#c25e00}.gF{color:#cf222e}"
        "code{font-size:.9em}</style>"
        f"<body>{body}</body></html>"
    )


def _leaderboard_html(worst: list[dict], best: list[dict]) -> str:
    def table(rows: list[dict]) -> str:
        if not rows:
            return "<p>No graded sites yet.</p>"
        out = ["<table><tr><th></th><th>Site</th><th>Score</th><th>Reports</th><th>Patterns</th></tr>"]
        for r in rows:
            g = html.escape(r["grade"])
            out.append(
                f"<tr><td class='g g{g}'>{g}</td><td>{html.escape(r['site'])}</td><td>{int(r['score'])}</td>"
                f"<td>{int(r['reports'])}</td><td>{html.escape(', '.join(r['dominant_flags']))}</td></tr>"
            )
        out.append("</table>")
        return "".join(out)

    return (
        "<h1>cookiemonsters</h1><p>How hard each site makes it to say no to tracking. "
        "Grades come from anonymous reports by the cookiemonsters browser extension. "
        "<a href='/v1/privacy'>What is collected</a> · <a href='/v1/feed'>Feed</a> · <a href='/docs'>API</a></p>"
        f"<h2>Hardest to refuse</h2>{table(worst)}<h2>Easiest to refuse</h2>{table(best)}"
    )
