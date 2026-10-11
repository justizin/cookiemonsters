"""Framework-free core: settings and the operations behind every endpoint."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Callable, Mapping

from . import clock, scoring
from .domains import InvalidSite, registrable_domain
from .models import Report
from .storage import Store


def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    report_token: str = ""
    allow_reserved_tlds: bool = False
    publish_min_reports: int = 1
    rate_per_day: int = 1000
    rate_per_site_day: int = 5
    trust_cf_headers: bool = False

    @classmethod
    def from_env(cls, get: Callable[[str], str | None] | Mapping[str, str]) -> "Settings":
        g = get.get if isinstance(get, Mapping) else get
        def gi(name: str, default: int) -> int:
            v = g(name)
            return int(v) if v not in (None, "") else default
        return cls(
            report_token=(g("CM_REPORT_TOKEN") or "").strip(),
            allow_reserved_tlds=_bool(g("CM_ALLOW_RESERVED_TLDS")),
            publish_min_reports=max(1, gi("CM_PUBLISH_MIN_REPORTS", 1)),
            rate_per_day=gi("CM_RATE_PER_DAY", 1000),
            rate_per_site_day=gi("CM_RATE_PER_SITE_DAY", 5),
            trust_cf_headers=_bool(g("CM_TRUST_CF_HEADERS")),
        )


class RateLimited(Exception):
    pass


class Service:
    def __init__(self, store: Store, settings: Settings):
        self.store = store
        self.settings = settings

    @property
    def window(self) -> int:
        return int(scoring.weights()["window_weeks"])

    def token_ok(self, presented: str | None) -> bool:
        if not self.settings.report_token:
            return True
        return bool(presented) and hmac.compare_digest(presented.encode(), self.settings.report_token.encode())

    async def _rate_key(self, day: str, *parts: str) -> tuple[str, bool]:
        fresh = secrets.token_hex(16)
        salt = await self.store.day_salt(day, fresh)
        key = hmac.new(bytes.fromhex(salt), "|".join(parts).encode(), hashlib.sha256).hexdigest()[:24]
        return key, salt == fresh

    async def submit(self, reports: list[Report], client_ip: str) -> dict:
        now = clock.utcnow().date()
        today, week = clock.day(now), clock.iso_week(now)
        client_key, first_today = await self._rate_key(today, "client", client_ip)
        if first_today:
            await self.maintain()
        accepted, rejected = 0, []
        touched: set[str] = set()
        # Charge the whole batch up front, so a refused batch folds nothing and can be retried as is.
        if await self.store.bump_rate(today, client_key, len(reports)) > self.settings.rate_per_day:
            raise RateLimited()
        for i, r in enumerate(reports):
            try:
                site = registrable_domain(r.site, allow_reserved=self.settings.allow_reserved_tlds)
            except InvalidSite as exc:
                rejected.append({"index": i, "reason": str(exc)})
                continue
            pair_key, _ = await self._rate_key(today, "pair", client_ip, site)
            if await self.store.bump_rate(today, pair_key) > self.settings.rate_per_site_day:
                rejected.append({"index": i, "reason": "too many reports for this site today"})
                continue
            friction = scoring.visit_friction(r.outcome, r.clicks, r.toggles_unticked, r.flags)
            await self.store.fold_report(site, week, friction, r.outcome, r.flags, r.cmp)
            touched.add(site)
            accepted += 1
        window = clock.window_weeks(now, self.window)
        for site in sorted(touched):
            await self.store.refresh_site(site, week, window)
        return {"accepted": accepted, "rejected": rejected}

    async def maintain(self, refresh_limit: int = 200) -> dict:
        """Delete expired salts/counters/aggregates and refresh summaries whose window moved."""
        now = clock.utcnow().date()
        window = clock.window_weeks(now, self.window)
        week = window[-1]
        await self.store.prune(clock.day(now), window[0])
        stale = await self.store.stale_sites(week, refresh_limit)
        for site in stale:
            await self.store.refresh_site(site, week, window)
        return {"refreshed": len(stale)}

    async def site(self, raw: str) -> dict | None:
        site = registrable_domain(raw, allow_reserved=self.settings.allow_reserved_tlds)
        rec = await self.store.get_site(site)
        if rec and rec["reports"] >= self.settings.publish_min_reports:
            return rec
        return None

    async def prefix_length(self) -> int:
        """Shortest hash prefix that still puts ~20 known sites in each bucket (1-4 hex chars)."""
        count = await self.store.count_sites(self.settings.publish_min_reports)
        length = 1
        while length < 4 and count / (16 ** (length + 1)) >= 20:
            length += 1
        return length

    async def lookup(self, prefix: str) -> list[dict]:
        return await self.store.by_prefix(prefix, self.settings.publish_min_reports)

    async def feed(self, cursor: str, since_week: str, limit: int, min_reports: int) -> tuple[list[dict], str | None]:
        rows = await self.store.feed_page(cursor, since_week, max(min_reports, self.settings.publish_min_reports), limit)
        nxt = rows[-1]["site"] if len(rows) == limit else None
        return rows, nxt

    async def leaderboard(self, worst: bool, limit: int) -> list[dict]:
        return await self.store.leaderboard(worst, self.settings.publish_min_reports, limit)
