"""
memory/store.py — SQLite-backed memory for the agent.

Stores:
  - Conversation history (last N messages per user)
  - User preferences
  - Error log
  - Activity log (mirrors Google Sheets for offline access)

Why SQLite and not Redis?
  For a personal agent (1-5 users) SQLite is zero-infra, fast, and reliable.
  Swap to Redis/Postgres when you go multi-user.
"""
import json
from datetime import datetime
from pathlib import Path

import aiosqlite

DB_PATH = "./data/agent.db"


async def init_db() -> None:
    """Create all tables if they don't exist. Called once at startup."""
    Path("./data").mkdir(exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                role        TEXT NOT NULL,      -- 'user' | 'assistant'
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id     INTEGER PRIMARY KEY,
                prefs_json  TEXT NOT NULL DEFAULT '{}',
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS activity_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                tool        TEXT NOT NULL,
                action      TEXT NOT NULL,
                result      TEXT,
                status      TEXT NOT NULL,     -- 'success' | 'error'
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS error_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                task          TEXT NOT NULL,
                error_type    TEXT NOT NULL,
                error_message TEXT NOT NULL,
                traceback     TEXT,
                created_at    TEXT NOT NULL
            );
        """)
        await db.commit()


class MemoryStore:
    """Simple async interface to the SQLite memory store."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    async def add_message(self, user_id: int, role: str, content: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (user_id, role, content, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def get_history(self, user_id: int, limit: int = 20) -> list[dict]:
        """Return the last `limit` messages for a user, oldest first."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT role, content FROM messages
                WHERE user_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (user_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        # Reverse so oldest is first (correct for LLM context)
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    async def clear_history(self, user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            await db.commit()

    async def get_preferences(self, user_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT prefs_json FROM user_preferences WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return json.loads(row[0]) if row else {}

    async def set_preferences(self, user_id: int, prefs: dict) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO user_preferences (user_id, prefs_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    prefs_json = excluded.prefs_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, json.dumps(prefs), datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def log_activity(
        self,
        user_id: int,
        tool: str,
        action: str,
        result: str | None,
        status: str,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO activity_log (user_id, tool, action, result, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, tool, action, result, status, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def get_recent_activities(self, user_id: int, limit: int = 10) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT tool, action, result, status, created_at
                FROM activity_log WHERE user_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (user_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {"tool": r[0], "action": r[1], "result": r[2], "status": r[3], "at": r[4]}
            for r in rows
        ]
