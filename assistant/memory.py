"""Persistent memory: facts, notes, reminders and todos stored in SQLite.

Everything the assistant learns lives in one small SQLite file so it survives
restarts and can be inspected or backed up trivially.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    key       TEXT UNIQUE NOT NULL,
    value     TEXT NOT NULL,
    updated   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    body      TEXT NOT NULL,
    tags      TEXT NOT NULL DEFAULT '',
    created   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    body      TEXT NOT NULL,
    due       REAL NOT NULL,
    repeat    TEXT NOT NULL DEFAULT 'none',
    done      INTEGER NOT NULL DEFAULT 0,
    created   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS todos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    body      TEXT NOT NULL,
    done      INTEGER NOT NULL DEFAULT 0,
    created   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    role      TEXT NOT NULL,
    content   TEXT NOT NULL,
    session   TEXT NOT NULL DEFAULT 'default',
    created   REAL NOT NULL
);
"""


@dataclass
class Reminder:
    id: int
    body: str
    due: float
    repeat: str
    done: int
    created: float

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["due_iso"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.due))
        return d


class Memory:
    """Thread-safe SQLite-backed long-term memory."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or settings.data_dir / "memory.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---------- facts ----------
    def remember(self, key: str, value: str) -> None:
        key = key.strip().lower()
        with self._lock:
            self._conn.execute(
                "INSERT INTO facts(key, value, updated) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                (key, value, time.time()),
            )
            self._conn.commit()

    def forget(self, key: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM facts WHERE key=?", (key.strip().lower(),))
            self._conn.commit()
            return cur.rowcount > 0

    def facts(self, query: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if query:
                like = f"%{query.lower()}%"
                rows = self._conn.execute(
                    "SELECT * FROM facts WHERE key LIKE ? OR value LIKE ? ORDER BY key",
                    (like, like),
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM facts ORDER BY key").fetchall()
        return [dict(r) for r in rows]

    # ---------- notes ----------
    def add_note(self, body: str, tags: str = "") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO notes(body, tags, created) VALUES(?,?,?)",
                (body, tags, time.time()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def notes(self, query: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            if query:
                like = f"%{query.lower()}%"
                rows = self._conn.execute(
                    "SELECT * FROM notes WHERE lower(body) LIKE ? OR lower(tags) LIKE ? "
                    "ORDER BY created DESC LIMIT ?",
                    (like, like, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM notes ORDER BY created DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    # ---------- reminders ----------
    def add_reminder(self, body: str, due: float, repeat: str = "none") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO reminders(body, due, repeat, done, created) VALUES(?,?,?,0,?)",
                (body, due, repeat, time.time()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def reminders(self, include_done: bool = False) -> list[Reminder]:
        with self._lock:
            sql = "SELECT * FROM reminders"
            if not include_done:
                sql += " WHERE done=0"
            sql += " ORDER BY due"
            rows = self._conn.execute(sql).fetchall()
        return [Reminder(**dict(r)) for r in rows]

    def due_reminders(self, now: float | None = None) -> list[Reminder]:
        now = now or time.time()
        return [r for r in self.reminders() if r.due <= now]

    def complete_reminder(self, rid: int) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone()
            if not row:
                return False
            r = Reminder(**dict(row))
            if r.repeat and r.repeat != "none":
                next_due = _advance(r.due, r.repeat)
                self._conn.execute("UPDATE reminders SET due=? WHERE id=?", (next_due, rid))
            else:
                self._conn.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))
            self._conn.commit()
            return True

    # ---------- todos ----------
    def add_todo(self, body: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO todos(body, done, created) VALUES(?,0,?)", (body, time.time())
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def todos(self, include_done: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            sql = "SELECT * FROM todos"
            if not include_done:
                sql += " WHERE done=0"
            sql += " ORDER BY created"
            rows = self._conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def complete_todo(self, tid: int) -> bool:
        with self._lock:
            cur = self._conn.execute("UPDATE todos SET done=1 WHERE id=?", (tid,))
            self._conn.commit()
            return cur.rowcount > 0

    # ---------- conversation history ----------
    def log_message(self, role: str, content: str, session: str = "default") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO history(role, content, session, created) VALUES(?,?,?,?)",
                (role, content, session, time.time()),
            )
            self._conn.commit()

    def recent_messages(self, session: str = "default", limit: int = 20) -> list[dict[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM history WHERE session=? ORDER BY id DESC LIMIT ?",
                (session, limit),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear_history(self, session: str = "default") -> None:
        with self._lock:
            self._conn.execute("DELETE FROM history WHERE session=?", (session,))
            self._conn.commit()

    # ---------- context for the model ----------
    def context_block(self) -> str:
        """A compact snapshot of memory to inject into the system prompt."""
        facts = self.facts()
        todos = self.todos()
        notes = self.notes(limit=8)
        upcoming = [r for r in self.reminders() if not r.done][:8]
        parts: list[str] = []
        if facts:
            parts.append(
                "Known facts about the user:\n"
                + "\n".join(f"- {f['key']}: {f['value']}" for f in facts[:40])
            )
        if todos:
            parts.append("Open todos:\n" + "\n".join(f"- [#{t['id']}] {t['body']}" for t in todos[:20]))
        if upcoming:
            parts.append(
                "Upcoming reminders:\n"
                + "\n".join(f"- [#{r.id}] {r.body} at {r.to_dict()['due_iso']}" for r in upcoming)
            )
        if notes:
            parts.append(
                "Recent notes:\n"
                + "\n".join(f"- [#{n['id']}] {n['body'][:200]}" for n in notes)
            )
        return "\n\n".join(parts) if parts else "(memory is empty)"

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _advance(ts: float, repeat: str) -> float:
    day = 86400.0
    mapping = {"daily": day, "weekly": 7 * day, "monthly": 30 * day}
    return ts + mapping.get(repeat, day)
