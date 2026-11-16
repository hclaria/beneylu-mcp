import os
import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path


class StateStore:
    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        path.touch(mode=0o600, exist_ok=True)
        os.chmod(path, 0o600)
        self._lock = threading.Lock()
        # MCPServer may run sync tools on worker threads.
        self._db = sqlite3.connect(path, check_same_thread=False)
        with self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS seen (source TEXT NOT NULL, item_id TEXT NOT NULL,"
                " fingerprint TEXT NOT NULL, PRIMARY KEY (source, item_id))"
            )

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set(self, key: str, value: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))

    def delete(self, key: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM kv WHERE key = ?", (key,))

    def seen_fingerprint(self, source: str, item_id: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT fingerprint FROM seen WHERE source = ? AND item_id = ?", (source, item_id)
            ).fetchone()
        return row[0] if row else None

    def mark_seen(self, items: Iterable[tuple[str, str, str]]) -> None:
        with self._lock, self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO seen (source, item_id, fingerprint) VALUES (?, ?, ?)", list(items)
            )
