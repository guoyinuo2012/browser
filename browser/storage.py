"""SQLite storage layer for browser.

One database, plain schema, no network. Tables:
    history     — visited URLs (never written for private tabs)
    bookmarks   — hierarchical bookmarks
    downloads   — download records
    visits      — (reserved for grouping) history is grouped in queries

The connection is opened with WAL and a busy timeout, and all access is
funnelled through one thread-safe API.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    host TEXT NOT NULL DEFAULT '',
    visit_time REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_time ON history(visit_time DESC);
CREATE INDEX IF NOT EXISTS idx_history_host ON history(host);

CREATE TABLE IF NOT EXISTS bookmarks (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    title TEXT NOT NULL,
    url TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    is_folder INTEGER NOT NULL DEFAULT 0,
    added_time REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_parent ON bookmarks(parent_id, position);

CREATE TABLE IF NOT EXISTS downloads (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    path TEXT NOT NULL,
    state TEXT NOT NULL,             -- in_progress | completed | cancelled | failed
    received_bytes INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT -1,
    mime TEXT DEFAULT '',
    started REAL NOT NULL,
    finished REAL,
    danger TEXT DEFAULT ''           -- '' or reason
);
"""

_ROOT_BOOKMARK_FOLDER = "root"


class Store:
    """SQLite-backed history, bookmarks and downloads storage."""
    def __init__(self, db_path: Path):
        self._path = Path(db_path)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()

    def _connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        if not conn.execute(
            "SELECT 1 FROM bookmarks WHERE id=?", (_ROOT_BOOKMARK_FOLDER,)
        ).fetchone():
            conn.execute(
                "INSERT INTO bookmarks (id, parent_id, title, url, position, is_folder, added_time)"
                " VALUES (?, NULL, ?, NULL, 0, 1, ?)",
                (_ROOT_BOOKMARK_FOLDER, "Bookmarks", time.time()),
            )
        conn.commit()
        self._conn = conn

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    # ------------------------------------------------------------------ #
    # History
    # ------------------------------------------------------------------ #
    def add_history(self, url: str, title: str, visit_time: float | None = None) -> None:
        host = ""
        try:
            from urllib.parse import urlparse
            host = urlparse(url).hostname or ""
        except Exception:
            pass        # unparseable URLs are simply stored without a host
        self._exec(
            "INSERT INTO history (url, title, host, visit_time) VALUES (?,?,?,?)",
            (url, title, host, visit_time if visit_time is not None else time.time()),
        )

    def update_history_title(self, url: str, title: str) -> None:
        """Set the title of every history row for this URL (titles arrive
        after navigation, so they are usually stored empty first)."""
        self._exec("UPDATE history SET title = ? WHERE url = ?", (title, url))

    def search_history(self, q: str, limit: int = 400) -> List[sqlite3.Row]:
        q = q.strip()
        if q:
            like = f"%{q}%"
            return self._query(
                "SELECT * FROM history WHERE url LIKE ? OR title LIKE ? "
                "ORDER BY visit_time DESC LIMIT ?", (like, like, limit))
        return self._query(
            "SELECT * FROM history ORDER BY visit_time DESC LIMIT ?", (limit,))

    def history_grouped_by_day(self, q: str = "", limit: int = 800) -> List[Tuple[str, List[sqlite3.Row]]]:
        rows = self.search_history(q, limit)
        import datetime as _dt
        groups: List[Tuple[str, List[sqlite3.Row]]] = []
        index: dict[str, int] = {}
        for r in rows:
            day = _dt.datetime.fromtimestamp(r["visit_time"]).strftime("%A, %d %B %Y")
            if day not in index:
                index[day] = len(groups)
                groups.append((day, []))
            groups[index[day]][1].append(r)
        return groups

    def delete_history(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        self._exec(f"DELETE FROM history WHERE id IN ({marks})", ids)

    def delete_history_range(self, start: float, end: float) -> int:
        cur = self._exec("DELETE FROM history WHERE visit_time BETWEEN ? AND ?", (start, end))
        return cur.rowcount

    def clear_history(self) -> None:
        self._exec("DELETE FROM history")

    def history_count(self) -> int:
        row = self._query("SELECT COUNT(*) AS c FROM history")
        return row[0]["c"] if row else 0

    def prune_history(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400
        cur = self._exec("DELETE FROM history WHERE visit_time < ?", (cutoff,))
        return cur.rowcount

    def top_hosts(self, limit: int = 10) -> List[sqlite3.Row]:
        return self._query(
            "SELECT host, COUNT(*) AS visits FROM history WHERE host != '' "
            "GROUP BY host ORDER BY visits DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------ #
    # Bookmarks
    # ------------------------------------------------------------------ #
    def get_bookmark(self, bid: str) -> Optional[sqlite3.Row]:
        rows = self._query("SELECT * FROM bookmarks WHERE id=?", (bid,))
        return rows[0] if rows else None

    def find_bookmark_by_url(self, url: str) -> Optional[sqlite3.Row]:
        rows = self._query(
            "SELECT * FROM bookmarks WHERE url=? ORDER BY rowid LIMIT 1", (url,))
        return rows[0] if rows else None

    def children(self, parent_id: Optional[str]) -> List[sqlite3.Row]:
        if parent_id is None:
            parent_id = _ROOT_BOOKMARK_FOLDER
        return self._query(
            "SELECT * FROM bookmarks WHERE parent_id=? ORDER BY position, title",
            (parent_id,))

    def walk(self, parent_id: Optional[str] = None, _depth: int = 0) -> List[sqlite3.Row]:
        """Pre-order traversal of the bookmark tree."""
        out: List[sqlite3.Row] = []
        for row in self.children(parent_id):
            out.append(row)
            if row["is_folder"] and _depth < 20:
                out.extend(self.walk(row["id"], _depth + 1))
        return out

    def add_bookmark(self, title: str, url: str, parent_id: Optional[str] = None) -> str:
        bid = uuid.uuid4().hex[:12]
        pos = self._next_position(parent_id)
        self._exec(
            "INSERT INTO bookmarks (id, parent_id, title, url, position, is_folder, added_time)"
            " VALUES (?,?,?,?,0,0,?)", (bid, parent_id or _ROOT_BOOKMARK_FOLDER, title, url, time.time()))
        self._exec("UPDATE bookmarks SET position=? WHERE id=?", (pos, bid))
        return bid

    def add_folder(self, title: str, parent_id: Optional[str] = None) -> str:
        bid = uuid.uuid4().hex[:12]
        self._exec(
            "INSERT INTO bookmarks (id, parent_id, title, url, position, is_folder, added_time)"
            " VALUES (?,?,?,NULL,?,1,?)",
            (bid, parent_id or _ROOT_BOOKMARK_FOLDER, title, self._next_position(parent_id), time.time()))
        return bid

    def _next_position(self, parent_id: Optional[str]) -> int:
        rows = self._query(
            "SELECT COALESCE(MAX(position)+1, 0) AS p FROM bookmarks WHERE parent_id=?",
            (parent_id or _ROOT_BOOKMARK_FOLDER,))
        return rows[0]["p"] if rows else 0

    def update_bookmark(self, bid: str, title: str | None = None, url: str | None = None) -> None:
        if title is not None:
            self._exec("UPDATE bookmarks SET title=? WHERE id=?", (title, bid))
        if url is not None:
            self._exec("UPDATE bookmarks SET url=? WHERE id=?", (url, bid))

    def move_bookmark(self, bid: str, new_parent: Optional[str], position: int | None = None) -> None:
        parent = new_parent or _ROOT_BOOKMARK_FOLDER
        if position is None:
            position = self._next_position(new_parent)
        self._exec("UPDATE bookmarks SET parent_id=?, position=? WHERE id=?",
                   (parent, position, bid))

    def delete_bookmark(self, bid: str) -> int:
        """Deletes a node and everything beneath it."""
        to_delete: List[str] = [bid]
        i = 0
        while i < len(to_delete):
            rows = self._query("SELECT id FROM bookmarks WHERE parent_id=?",
                               (to_delete[i],))
            for r in rows:
                to_delete.append(r["id"])
            i += 1
        marks = ",".join("?" * len(to_delete))
        cur = self._exec(f"DELETE FROM bookmarks WHERE id IN ({marks})", to_delete)
        return cur.rowcount

    def duplicate_url_exists(self, url: str, exclude: str | None = None) -> bool:
        rows = self._query("SELECT id FROM bookmarks WHERE url=? AND url IS NOT NULL", (url,))
        return any(r["id"] != exclude for r in rows)

    # ------------------------------------------------------------------ #
    # Downloads
    # ------------------------------------------------------------------ #
    def add_download(self, did: str, url: str, path: str, state: str = "in_progress",
                     total: int = -1, mime: str = "") -> None:
        self._exec(
            "INSERT INTO downloads (id, url, path, state, received_bytes, total_bytes, mime, started)"
            " VALUES (?,?,?,?,-1,?,?,?)", (did, url, path, state, total, mime, time.time()))

    def update_download(self, did: str, *, state: str | None = None,
                        received: int | None = None, total: int | None = None,
                        finished: bool = False, danger: str | None = None) -> None:
        sets, params = [], []
        if state is not None:
            sets.append("state=?"); params.append(state)
        if received is not None:
            sets.append("received_bytes=?"); params.append(received)
        if total is not None:
            sets.append("total_bytes=?"); params.append(total)
        if finished:
            sets.append("finished=?"); params.append(time.time())
        if danger is not None:
            sets.append("danger=?"); params.append(danger)
        if not sets:
            return
        params.append(did)
        self._exec(f"UPDATE downloads SET {', '.join(sets)} WHERE id=?", params)

    def downloads(self, limit: int = 200) -> List[sqlite3.Row]:
        return self._query("SELECT * FROM downloads ORDER BY started DESC LIMIT ?", (limit,))

    def get_download(self, did: str) -> Optional[sqlite3.Row]:
        rows = self._query("SELECT * FROM downloads WHERE id=?", (did,))
        return rows[0] if rows else None

    def remove_download(self, did: str) -> None:
        self._exec("DELETE FROM downloads WHERE id=?", (did,))

    def clear_downloads(self) -> None:
        self._exec("DELETE FROM downloads")
