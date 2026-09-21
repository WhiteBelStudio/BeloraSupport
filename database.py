from __future__ import annotations

import os
from datetime import datetime, timezone
import aiosqlite

DB_PATH = os.getenv("DATABASE_PATH", "data/belora_support.db")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS applications (id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, user_id TEXT NOT NULL, username TEXT, name TEXT NOT NULL, age INTEGER NOT NULL, city TEXT NOT NULL, reason TEXT NOT NULL, interests TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reject_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_app_user_status ON applications(platform,user_id,status)")
        await db.commit()


async def has_pending(platform: str, user_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM applications WHERE platform=? AND user_id=? AND status='pending' LIMIT 1", (platform, user_id))
        return await cur.fetchone() is not None


async def create_application(platform: str, user_id: str, username: str | None, name: str, age: int, city: str, reason: str, interests: str) -> int:
    timestamp = now()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT INTO applications(platform,user_id,username,name,age,city,reason,interests,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'pending',?,?)", (platform,user_id,username,name,age,city,reason,interests,timestamp,timestamp))
        await db.commit()
        return int(cur.lastrowid)


async def get_application(application_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM applications WHERE id=?", (application_id,))
        return await cur.fetchone()


async def set_status(application_id: int, status: str, reject_reason: str | None = None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("UPDATE applications SET status=?,reject_reason=?,updated_at=? WHERE id=? AND status='pending'", (status,reject_reason,now(),application_id))
        await db.commit()
        return cur.rowcount > 0
