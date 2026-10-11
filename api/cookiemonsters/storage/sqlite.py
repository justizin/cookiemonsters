"""sqlite3 executor for the standalone server and tests."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Sequence


class SQLiteExecutor:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL" if str(path) != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.Lock()

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self._lock:
            self._db.execute(sql, tuple(params))

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, tuple(params)).fetchall()]

    async def batch(self, statements: Sequence[tuple[str, Sequence[Any]]]) -> None:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for sql, params in statements:
                    self._db.execute(sql, tuple(params))
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    async def close(self) -> None:
        with self._lock:
            self._db.close()
