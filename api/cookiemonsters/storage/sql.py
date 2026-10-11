"""The one SQL layer. SQLite dialect, which is also what Cloudflare D1 speaks.

Every query lives here; executors (sqlite.py, d1.py) only know how to run a
statement. Parameters are never NULL (D1 cannot bind Python None reliably).

Tables
  site_week  aggregate counts per (site, ISO week, scoring version). This is the
             only place reports end up. A report is folded in with one atomic
             UPSERT and is never stored on its own.
  sites      cached public summary per site, plus the hash prefix used for
             private lookups. Rebuilt from site_week.
  day_salt   one random salt per UTC day for rate-limit keys. Deleted once the
             day is over, which makes yesterday's keys irreversible.
  rate       rate-limit counters keyed by HMAC(salt, client). Pruned daily.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol, Sequence

from .. import scoring

SCHEMA: list[str] = [
    """CREATE TABLE IF NOT EXISTS site_week (
  site TEXT NOT NULL,
  week TEXT NOT NULL,
  scoring_version INTEGER NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  hist TEXT NOT NULL DEFAULT '{}',
  outcomes TEXT NOT NULL DEFAULT '{}',
  flags TEXT NOT NULL DEFAULT '{}',
  cmps TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (site, week, scoring_version)
)""",
    """CREATE TABLE IF NOT EXISTS sites (
  site TEXT PRIMARY KEY,
  prefix TEXT NOT NULL,
  first_week TEXT NOT NULL,
  last_week TEXT NOT NULL,
  refreshed_week TEXT NOT NULL,
  reports INTEGER NOT NULL,
  score INTEGER NOT NULL,
  record TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS sites_prefix ON sites (prefix)",
    "CREATE INDEX IF NOT EXISTS sites_last_week ON sites (last_week, site)",
    "CREATE INDEX IF NOT EXISTS sites_score ON sites (score, site)",
    """CREATE TABLE IF NOT EXISTS day_salt (
  day TEXT PRIMARY KEY,
  salt TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS rate (
  day TEXT NOT NULL,
  k TEXT NOT NULL,
  n INTEGER NOT NULL,
  PRIMARY KEY (day, k)
)""",
]


def site_prefix(site: str) -> str:
    """First 8 hex chars of SHA-256(site). Clients query by a shorter prefix of this."""
    return hashlib.sha256(site.encode("ascii")).hexdigest()[:8]


class Executor(Protocol):
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None: ...
    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]: ...
    async def batch(self, statements: Sequence[tuple[str, Sequence[Any]]]) -> None: ...
    async def close(self) -> None: ...


def _json_inc(column: str, keys: Sequence[str]) -> str:
    """SQL expression that increments column[key] for every key, atomically inside one UPDATE."""
    expr = column
    for k in keys:
        path = '\'$."' + k + '"\''  # keys are validated enums / ints / cmp slugs; no quotes possible
        expr = f"json_set({expr}, {path}, coalesce(json_extract({column}, {path}), 0) + 1)"
    return expr


class Store:
    def __init__(self, ex: Executor):
        self.ex = ex

    async def migrate(self) -> None:
        for stmt in SCHEMA:
            await self.ex.execute(stmt)

    # -- writes -------------------------------------------------------------

    async def fold_report(self, site: str, week: str, friction: int, outcome: str, flags: Sequence[str], cmp: str) -> None:
        """Fold one report into its weekly aggregate. The report itself is not kept."""
        v = scoring.scoring_version()
        inc_hist = _json_inc("hist", [str(friction)])
        inc_out = _json_inc("outcomes", [outcome])
        inc_flags = _json_inc("flags", list(flags))
        inc_cmp = _json_inc("cmps", [cmp])
        insert = (
            "INSERT INTO site_week (site, week, scoring_version, n, hist, outcomes, flags, cmps) "
            "VALUES (?, ?, ?, 0, '{}', '{}', '{}', '{}') ON CONFLICT (site, week, scoring_version) DO NOTHING"
        )
        update = (
            f"UPDATE site_week SET n = n + 1, hist = {inc_hist}, outcomes = {inc_out}, flags = {inc_flags}, cmps = {inc_cmp} "
            "WHERE site = ? AND week = ? AND scoring_version = ?"
        )
        await self.ex.batch([(insert, (site, week, v)), (update, (site, week, v))])

    async def refresh_site(self, site: str, current_week: str, window: list[str]) -> dict | None:
        """Recompute the public record for one site from its weekly aggregates."""
        v = scoring.scoring_version()
        marks = ",".join("?" for _ in window)
        rows = await self.ex.fetchall(
            f"SELECT week, n, hist, outcomes, flags, cmps FROM site_week WHERE site = ? AND scoring_version = ? AND week IN ({marks})",
            (site, v, *window),
        )
        if not rows:
            await self.ex.execute("DELETE FROM sites WHERE site = ?", (site,))
            return None
        n = 0
        hist: dict[int, int] = {}
        outcomes: dict[str, int] = {}
        flags: dict[str, int] = {}
        cmps: dict[str, int] = {}
        for r in rows:
            n += int(r["n"])
            for k, c in json.loads(r["hist"]).items():
                hist[int(k)] = hist.get(int(k), 0) + int(c)
            for src, dst in ((r["outcomes"], outcomes), (r["flags"], flags), (r["cmps"], cmps)):
                for k, c in json.loads(src).items():
                    dst[k] = dst.get(k, 0) + int(c)
        summary = scoring.site_summary(n, hist, outcomes, flags)
        weeks = sorted(r["week"] for r in rows)
        record = build_record(site, summary, weeks[0], weeks[-1], cmps, len(window))
        await self.ex.execute(
            "INSERT INTO sites (site, prefix, first_week, last_week, refreshed_week, reports, score, record) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (site) DO UPDATE SET first_week = excluded.first_week, last_week = excluded.last_week, "
            "refreshed_week = excluded.refreshed_week, reports = excluded.reports, score = excluded.score, record = excluded.record",
            (site, site_prefix(site), weeks[0], weeks[-1], current_week, n, record["score"], json.dumps(record, separators=(",", ":"), sort_keys=True)),
        )
        return record

    async def stale_sites(self, current_week: str, limit: int) -> list[str]:
        rows = await self.ex.fetchall("SELECT site FROM sites WHERE refreshed_week < ? ORDER BY site LIMIT ?", (current_week, limit))
        return [r["site"] for r in rows]

    async def prune(self, today: str, oldest_week_kept: str) -> None:
        await self.ex.batch([
            ("DELETE FROM day_salt WHERE day < ?", (today,)),
            ("DELETE FROM rate WHERE day < ?", (today,)),
            ("DELETE FROM site_week WHERE week < ?", (oldest_week_kept,)),
            ("DELETE FROM site_week WHERE scoring_version <> ?", (scoring.scoring_version(),)),
        ])

    # -- rate limiting --------------------------------------------------------

    async def day_salt(self, day: str, fresh_salt: str) -> str:
        await self.ex.execute("INSERT INTO day_salt (day, salt) VALUES (?, ?) ON CONFLICT (day) DO NOTHING", (day, fresh_salt))
        rows = await self.ex.fetchall("SELECT salt FROM day_salt WHERE day = ?", (day,))
        return rows[0]["salt"]

    async def bump_rate(self, day: str, key: str, by: int = 1) -> int:
        await self.ex.execute(
            "INSERT INTO rate (day, k, n) VALUES (?, ?, ?) ON CONFLICT (day, k) DO UPDATE SET n = n + excluded.n", (day, key, by)
        )
        rows = await self.ex.fetchall("SELECT n FROM rate WHERE day = ? AND k = ?", (day, key))
        return int(rows[0]["n"])

    # -- reads ----------------------------------------------------------------

    async def get_site(self, site: str) -> dict | None:
        rows = await self.ex.fetchall("SELECT record FROM sites WHERE site = ?", (site,))
        return json.loads(rows[0]["record"]) if rows else None

    async def by_prefix(self, prefix: str, min_reports: int) -> list[dict]:
        lo = prefix
        hi = prefix + "g"  # 'g' sorts after every hex digit
        rows = await self.ex.fetchall(
            "SELECT record FROM sites WHERE prefix >= ? AND prefix < ? AND reports >= ? ORDER BY site LIMIT 500", (lo, hi, min_reports)
        )
        return [json.loads(r["record"]) for r in rows]

    async def count_sites(self, min_reports: int) -> int:
        rows = await self.ex.fetchall("SELECT count(*) AS c FROM sites WHERE reports >= ?", (min_reports,))
        return int(rows[0]["c"])

    async def feed_page(self, after: str, since_week: str, min_reports: int, limit: int) -> list[dict]:
        rows = await self.ex.fetchall(
            "SELECT record FROM sites WHERE site > ? AND last_week >= ? AND reports >= ? ORDER BY site LIMIT ?",
            (after, since_week, min_reports, limit),
        )
        return [json.loads(r["record"]) for r in rows]

    async def leaderboard(self, worst: bool, min_reports: int, limit: int) -> list[dict]:
        order = "score ASC, site ASC" if worst else "score DESC, site ASC"
        rows = await self.ex.fetchall(
            f"SELECT record FROM sites WHERE reports >= ? ORDER BY {order} LIMIT ?", (min_reports, limit)
        )
        return [json.loads(r["record"]) for r in rows]


def build_record(site: str, summary: dict, first_week: str, last_week: str, cmps: dict[str, int], window_weeks: int) -> dict:
    n = summary["reports"]
    prior_n = 3
    rank_signal = round((summary["score"] / 100 * n + 0.5 * prior_n) / (n + prior_n), 4)
    from ..models import SCHEMA_VERSION

    return {
        "schema_version": SCHEMA_VERSION,
        "scoring_version": scoring.scoring_version(),
        "site": site,
        "score": summary["score"],
        "friction": summary["friction"],
        "grade": summary["grade"],
        "confidence": summary["confidence"],
        "reports": n,
        "rank_signal": rank_signal,
        "window_weeks": window_weeks,
        "first_seen_week": first_week,
        "last_seen_week": last_week,
        "outcomes": summary["outcomes"],
        "flags": summary["flags"],
        "dominant_flags": summary["dominant_flags"],
        "cmps": {k: round(c / n, 3) for k, c in sorted(cmps.items())},
    }
