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
        await db.execute("CREATE TABLE IF NOT EXISTS admins (platform TEXT NOT NULL, user_id TEXT NOT NULL, added_by TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(platform,user_id))")
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


async def add_admin(platform: str, user_id: int, added_by: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT OR IGNORE INTO admins(platform,user_id,added_by,created_at) VALUES(?,?,?,?)", (platform,str(user_id),str(added_by),now()))
        await db.commit()
        return cur.rowcount > 0


async def remove_admin(platform: str, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM admins WHERE platform=? AND user_id=?", (platform,str(user_id)))
        await db.commit()
        return cur.rowcount > 0


async def list_admins(platform: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM admins WHERE platform=? ORDER BY created_at", (platform,))
        return await cur.fetchall()


async def list_applications(status: str | None = None, limit: int = 20, offset: int = 0):
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            cur = await db.execute("SELECT * FROM applications WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?", (status, limit, offset))
        else:
            cur = await db.execute("SELECT * FROM applications ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        return await cur.fetchall()


async def count_applications(status: str | None = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        if status:
            cur = await db.execute("SELECT COUNT(*) FROM applications WHERE status=?", (status,))
        else:
            cur = await db.execute("SELECT COUNT(*) FROM applications")
        row = await cur.fetchone()
        return int(row[0])


async def application_stats() -> dict[str, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT status, COUNT(*) FROM applications GROUP BY status")
        rows = await cur.fetchall()
    result = {"pending": 0, "approved": 0, "rejected": 0, "total": 0}
    for status, count in rows:
        result[str(status)] = int(count)
        result["total"] += int(count)
    return result


async def clear_all_applications() -> int:
    """Delete all saved applications and return the number removed."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM applications")
        row = await cur.fetchone()
        count = int(row[0]) if row else 0
        await db.execute("DELETE FROM applications")
        await db.commit()
        return count
