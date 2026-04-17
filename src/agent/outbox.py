"""Persistent outbox for agent-to-server messages.

SQLite-backed FIFO queue. Survives reboots. Supports retry with exponential
backoff: 6s, 30s, 120s, 300s, capped at retry_max_sec.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

_BACKOFF_SCHEDULE = [6, 30, 120, 300]


def _backoff_for(retries: int, cap: float) -> float:
    if retries <= 0:
        return 0.0
    idx = min(retries - 1, len(_BACKOFF_SCHEDULE) - 1)
    return min(_BACKOFF_SCHEDULE[idx], cap)


@dataclass
class OutboxRow:
    seq: int
    kind: str
    payload: str
    enqueued_at: float
    last_try_at: float
    retries: int
    acked: int


class Outbox:
    def __init__(self, path: str, retry_max_sec: float = 900.0):
        self._path = path
        self._retry_max_sec = retry_max_sec
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(
            path, timeout=5.0, isolation_level=None,
            check_same_thread=False,
        )
        self._conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            CREATE TABLE IF NOT EXISTS outbox (
                seq         INTEGER PRIMARY KEY,
                kind        TEXT NOT NULL,
                payload     TEXT NOT NULL,
                enqueued_at REAL NOT NULL,
                last_try_at REAL NOT NULL DEFAULT 0,
                retries     INTEGER NOT NULL DEFAULT 0,
                acked       INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_due ON outbox(acked, last_try_at);
        """)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def enqueue(self, kind: str, payload: str) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM outbox")
            last = cur.fetchone()[0]
            seq = int(last) + 1
            self._conn.execute(
                "INSERT INTO outbox(seq, kind, payload, enqueued_at) VALUES (?, ?, ?, ?)",
                (seq, kind, payload, time.time()),
            )
            return seq

    def next_due(self, now: float) -> Optional[OutboxRow]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT seq, kind, payload, enqueued_at, last_try_at, retries, acked "
                "FROM outbox WHERE acked=0 ORDER BY seq ASC"
            )
            for row in cur:
                seq, kind, payload, enq, last_try, retries, acked = row
                if last_try == 0 or (now - last_try) >= _backoff_for(retries, self._retry_max_sec):
                    return OutboxRow(seq, kind, payload, enq, last_try, retries, acked)
            return None

    def mark_tried(self, seq: int, now: float) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE outbox SET last_try_at=?, retries=retries+1 WHERE seq=?",
                (now, seq),
            )

    def ack(self, seq: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE outbox SET acked=1 WHERE seq=?", (seq,))

    def depth(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM outbox WHERE acked=0")
            return int(cur.fetchone()[0])

    def get(self, seq: int) -> Optional[OutboxRow]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT seq, kind, payload, enqueued_at, last_try_at, retries, acked "
                "FROM outbox WHERE seq=?", (seq,)
            )
            row = cur.fetchone()
            if row is None:
                return None
            return OutboxRow(*row)

    def vacuum_acked(self, older_than_sec: float = 86400.0) -> int:
        cutoff = time.time() - older_than_sec
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM outbox WHERE acked=1 AND enqueued_at < ?",
                (cutoff,),
            )
            return cur.rowcount or 0
