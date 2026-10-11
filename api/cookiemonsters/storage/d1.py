"""Cloudflare D1 executor (Python Workers / Pyodide).

D1 is SQLite, so the statements in sql.py run unchanged. The binding API is
``env.DB.prepare(sql).bind(*params)`` → ``.run()`` / ``.all()``, and
``env.DB.batch([...])`` runs statements atomically in one transaction.
"""

from __future__ import annotations

from typing import Any, Sequence


def _to_py(value: Any) -> Any:
    to_py = getattr(value, "to_py", None)
    return to_py() if callable(to_py) else value


class D1Executor:
    def __init__(self, binding: Any):
        self._db = binding

    def _stmt(self, sql: str, params: Sequence[Any]) -> Any:
        if any(p is None for p in params):
            raise ValueError("NULL parameters are not supported by this layer")
        stmt = self._db.prepare(sql)
        return stmt.bind(*params) if params else stmt

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        await self._stmt(sql, params).run()

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        result = await self._stmt(sql, params).all()
        rows = _to_py(getattr(result, "results", None))
        if rows is None and isinstance(result, dict):
            rows = result.get("results")
        return [dict(_to_py(r)) for r in (rows or [])]

    async def batch(self, statements: Sequence[tuple[str, Sequence[Any]]]) -> None:
        stmts = [self._stmt(sql, params) for sql, params in statements]
        try:
            from pyodide.ffi import to_js  # type: ignore

            stmts = to_js(stmts)
        except ImportError:  # unit tests with a fake binding
            pass
        await self._db.batch(stmts)

    async def close(self) -> None:
        return None
