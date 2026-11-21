import json
import os
import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

# A reported change stays in `pending` until the batch that reported it is acknowledged. Only an
# acknowledgement moves fingerprints into `seen`, so a reply lost between the server and the parents
# is reported again on the next call instead of being dropped.


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
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS pending (source TEXT NOT NULL, item_id TEXT NOT NULL,"
                " fingerprint TEXT NOT NULL, payload TEXT NOT NULL, sort_key TEXT NOT NULL,"
                " first_reported_at TEXT NOT NULL, report_count INTEGER NOT NULL,"
                " PRIMARY KEY (source, item_id))"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS batches (cursor TEXT PRIMARY KEY, created_at TEXT NOT NULL,"
                " items TEXT NOT NULL, unread INTEGER NOT NULL, acked_at TEXT)"
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

    def record_batch(
        self,
        cursor: str,
        now: datetime,
        observed: list[tuple[str, str, str]],
        reported: list[tuple[str, str, str, dict, str]],
        unread: int,
    ) -> list[dict]:
        """Store a whats_new batch in one transaction and return every pending item.

        observed: (source, item_id, fingerprint) of everything read; marked seen when the batch is acknowledged.
        reported: (source, item_id, fingerprint, payload, sort_key) of the changes to show the caller.
        Pending items not re-read this time (out of the window, deleted) are returned and acknowledged too.
        """
        stamp = now.isoformat()
        with self._lock, self._db:
            for source, item_id, fingerprint, payload, sort_key in reported:
                row = self._db.execute(
                    "SELECT fingerprint FROM pending WHERE source = ? AND item_id = ?", (source, item_id)
                ).fetchone()
                data = json.dumps(payload, ensure_ascii=False)
                if row and row[0] == fingerprint:
                    self._db.execute(
                        "UPDATE pending SET payload = ?, sort_key = ? WHERE source = ? AND item_id = ?",
                        (data, sort_key, source, item_id),
                    )
                else:  # first report, or changed again since the last unacknowledged report
                    self._db.execute(
                        "INSERT OR REPLACE INTO pending (source, item_id, fingerprint, payload, sort_key,"
                        " first_reported_at, report_count) VALUES (?, ?, ?, ?, ?, ?, 0)",
                        (source, item_id, fingerprint, data, sort_key, stamp),
                    )
            self._db.execute("UPDATE pending SET report_count = report_count + 1")
            pending = self._db.execute("SELECT source, item_id, fingerprint FROM pending").fetchall()
            self._db.execute(
                "INSERT INTO batches (cursor, created_at, items, unread) VALUES (?, ?, ?, ?)",
                (cursor, stamp, json.dumps([list(o) for o in observed] + [list(p) for p in pending]), unread),
            )
            return self._pending_rows()

    def pending_items(self) -> list[dict]:
        with self._lock:
            return self._pending_rows()

    def ack(self, cursor: str, now: datetime) -> dict | None:
        """Acknowledge a batch. Idempotent; returns None for an unknown cursor."""
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT items, unread, acked_at FROM batches WHERE cursor = ?", (cursor,)
            ).fetchone()
            if row is None:
                return None
            items, unread, acked_at = row
            if acked_at is not None:
                return {"acknowledged": 0, "already_acknowledged": True}
            done = 0
            for source, item_id, fingerprint in json.loads(items):
                current = self._db.execute(
                    "SELECT fingerprint FROM pending WHERE source = ? AND item_id = ?", (source, item_id)
                ).fetchone()
                if current and current[0] != fingerprint:
                    continue  # changed after this batch: the newer version is still owed, keep it unseen
                self._db.execute(
                    "INSERT OR REPLACE INTO seen (source, item_id, fingerprint) VALUES (?, ?, ?)",
                    (source, item_id, fingerprint),
                )
                if current:
                    self._db.execute("DELETE FROM pending WHERE source = ? AND item_id = ?", (source, item_id))
                    done += 1
            self._db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('chat_unread', ?)", (str(unread),))
            self._db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('initialized', '1')")
            self._db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('cards_initialized', '1')")
            self._db.execute("UPDATE batches SET acked_at = ? WHERE cursor = ?", (now.isoformat(), cursor))
            return {"acknowledged": done, "already_acknowledged": False}

    def prune_batches(self, before: datetime) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM batches WHERE created_at < ?", (before.isoformat(),))

    def _pending_rows(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT source, item_id, payload, first_reported_at, report_count FROM pending"
            " ORDER BY sort_key DESC, item_id"
        ).fetchall()
        return [
            {"source": s, "id": i, "payload": json.loads(p), "first_reported_at": f, "report_count": c}
            for s, i, p, f, c in rows
        ]
