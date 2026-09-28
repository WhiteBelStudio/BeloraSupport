from __future__ import annotations

import os
from datetime import datetime, timezone
import aiosqlite

DB_PATH = os.getenv("DATABASE_PATH", "data/belora_support.db")

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _platform(platform: str) -> str:
    return "telegram" if str(platform).lower() in {"tg", "telegram"} else "vk"

async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS applications (id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, user_id TEXT NOT NULL, username TEXT, name TEXT NOT NULL, age INTEGER NOT NULL, city TEXT NOT NULL, reason TEXT NOT NULL, interests TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reject_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_app_user_status ON applications(platform,user_id,status)")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (platform TEXT NOT NULL, user_id TEXT NOT NULL, added_by TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(platform,user_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS bans (platform TEXT NOT NULL, user_id TEXT NOT NULL, reason TEXT NOT NULL, banned_by TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(platform,user_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS conversations (platform TEXT NOT NULL, application_id INTEGER NOT NULL, admin_id TEXT NOT NULL, user_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, started_at TEXT NOT NULL, ended_at TEXT, PRIMARY KEY(platform, application_id))")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_conversations_admin ON conversations(platform,admin_id,active)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(platform,user_id,active)")
        await db.execute("CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, user_id TEXT NOT NULL, username TEXT, subject TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', admin_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_user_status ON support_tickets(platform,user_id,status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON support_tickets(platform,status)")
        await db.execute("CREATE TABLE IF NOT EXISTS support_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL, platform TEXT NOT NULL, sender_type TEXT NOT NULL, sender_id TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ticket_messages ON support_messages(ticket_id,id)")
        await db.commit()

async def has_pending(platform: str, user_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM applications WHERE platform=? AND user_id=? AND status='pending' LIMIT 1", (_platform(platform), user_id)); return await cur.fetchone() is not None

async def create_application(platform: str, user_id: str, username: str | None, name: str, age: int, city: str, reason: str, interests: str) -> int:
    timestamp=now()
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("INSERT INTO applications(platform,user_id,username,name,age,city,reason,interests,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'pending',?,?)",(_platform(platform),user_id,username,name,age,city,reason,interests,timestamp,timestamp)); await db.commit(); return int(cur.lastrowid)

async def get_application(application_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM applications WHERE id=?",(application_id,)); return await cur.fetchone()

async def set_status(application_id: int,status: str,reject_reason: str|None=None)->bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("UPDATE applications SET status=?,reject_reason=?,updated_at=? WHERE id=? AND status='pending'",(status,reject_reason,now(),application_id)); await db.commit(); return cur.rowcount>0

async def add_admin(platform: str,user_id: int,added_by: int)->bool:
    platform=_platform(platform)
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("INSERT OR IGNORE INTO admins(platform,user_id,added_by,created_at) VALUES(?,?,?,?)",(platform,str(user_id),str(added_by),now())); await db.commit(); added=cur.rowcount>0
    from config import register_admin; register_admin(platform,user_id); return added

async def remove_admin(platform: str,user_id: int)->bool:
    platform=_platform(platform)
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("DELETE FROM admins WHERE platform=? AND user_id=?",(platform,str(user_id))); await db.commit(); removed=cur.rowcount>0
    from config import unregister_admin; unregister_admin(platform,user_id); return removed

async def list_admins(platform: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM admins WHERE platform=? ORDER BY created_at",(_platform(platform),)); return await cur.fetchall()

async def list_applications(status: str|None=None,limit:int=20,offset:int=0):
    limit=max(1,min(int(limit),100)); offset=max(0,int(offset))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row
        cur=await db.execute("SELECT * FROM applications WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?",(status,limit,offset)) if status else await db.execute("SELECT * FROM applications ORDER BY id DESC LIMIT ? OFFSET ?",(limit,offset)); return await cur.fetchall()

async def count_applications(status: str|None=None)->int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT COUNT(*) FROM applications" if not status else "SELECT COUNT(*) FROM applications WHERE status=?",() if not status else (status,)); row=await cur.fetchone(); return int(row[0])

async def application_stats()->dict[str,int]:
    async with aiosqlite.connect(DB_PATH) as db: cur=await db.execute("SELECT status,COUNT(*) FROM applications GROUP BY status"); rows=await cur.fetchall()
    result={"pending":0,"approved":0,"rejected":0,"total":0}
    for status,count in rows: result[str(status)]=int(count); result["total"]+=int(count)
    return result

async def clear_all_applications()->int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT COUNT(*) FROM applications"); row=await cur.fetchone(); count=int(row[0]); await db.execute("DELETE FROM applications"); await db.commit(); return count

async def ban_user(platform:str,user_id:int,reason:str,banned_by:int)->bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("INSERT OR REPLACE INTO bans(platform,user_id,reason,banned_by,created_at) VALUES(?,?,?,?,?)",(_platform(platform),str(user_id),str(reason).strip(),str(banned_by),now())); await db.commit(); return cur.rowcount>0

async def unban_user(platform:str,user_id:int)->bool:
    async with aiosqlite.connect(DB_PATH) as db: cur=await db.execute("DELETE FROM bans WHERE platform=? AND user_id=?",(_platform(platform),str(user_id))); await db.commit(); return cur.rowcount>0

async def get_ban(platform:str,user_id:str|int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM bans WHERE platform=? AND user_id=?",(_platform(platform),str(user_id))); return await cur.fetchone()

async def is_banned(platform:str,user_id:str|int)->bool: return await get_ban(platform,user_id) is not None

async def list_bans(platform:str|None=None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM bans WHERE platform=? ORDER BY created_at DESC",(_platform(platform),)) if platform else await db.execute("SELECT * FROM bans ORDER BY created_at DESC"); return await cur.fetchall()

async def start_conversation(platform:str,application_id:int,admin_id:int,user_id:int)->bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE conversations SET active=0,ended_at=? WHERE platform=? AND admin_id=? AND active=1",(now(),_platform(platform),str(admin_id)))
        await db.execute("INSERT OR REPLACE INTO conversations(platform,application_id,admin_id,user_id,active,started_at,ended_at) VALUES(?,?,?,?,1,?,NULL)",(_platform(platform),int(application_id),str(admin_id),str(user_id),now())); await db.commit(); return True

async def get_active_conversation_by_admin(platform:str,admin_id:int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM conversations WHERE platform=? AND admin_id=? AND active=1 LIMIT 1",(_platform(platform),str(admin_id))); return await cur.fetchone()

async def get_active_conversation_by_user(platform:str,user_id:int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM conversations WHERE platform=? AND user_id=? AND active=1 LIMIT 1",(_platform(platform),str(user_id))); return await cur.fetchone()

async def close_conversation(platform:str,application_id:int)->bool:
    async with aiosqlite.connect(DB_PATH) as db: cur=await db.execute("UPDATE conversations SET active=0,ended_at=? WHERE platform=? AND application_id=? AND active=1",(now(),_platform(platform),int(application_id))); await db.commit(); return cur.rowcount>0

async def create_ticket(platform:str,user_id:int,username:str|None,subject:str)->int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("INSERT INTO support_tickets(platform,user_id,username,subject,status,created_at,updated_at) VALUES(?,?,?,?, 'open',?,?)",(_platform(platform),str(user_id),username,subject.strip(),now(),now())); await db.commit(); return int(cur.lastrowid)

async def get_open_ticket_by_user(platform:str,user_id:int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM support_tickets WHERE platform=? AND user_id=? AND status='open' ORDER BY id DESC LIMIT 1",(_platform(platform),str(user_id))); return await cur.fetchone()

async def get_ticket(ticket_id:int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM support_tickets WHERE id=?",(int(ticket_id),)); return await cur.fetchone()

async def list_tickets(status:str='open',limit:int=20,offset:int=0):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM support_tickets WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?",(status,max(1,min(int(limit),100)),max(0,int(offset)))); return await cur.fetchall()

async def count_tickets(status:str|None='open')->int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT COUNT(*) FROM support_tickets" if status is None else "SELECT COUNT(*) FROM support_tickets WHERE status=?",() if status is None else (status,)); row=await cur.fetchone(); return int(row[0])

async def add_ticket_message(ticket_id:int,platform:str,sender_type:str,sender_id:int,text:str)->int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("INSERT INTO support_messages(ticket_id,platform,sender_type,sender_id,text,created_at) VALUES(?,?,?,?,?,?)",(int(ticket_id),_platform(platform),sender_type,str(sender_id),text,now())); await db.execute("UPDATE support_tickets SET updated_at=? WHERE id=?",(now(),int(ticket_id))); await db.commit(); return int(cur.lastrowid)

async def list_ticket_messages(ticket_id:int,limit:int=50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row; cur=await db.execute("SELECT * FROM support_messages WHERE ticket_id=? ORDER BY id ASC LIMIT ?",(int(ticket_id),max(1,min(int(limit),200)))); return await cur.fetchall()

async def assign_ticket(ticket_id:int,admin_id:int)->bool:
    async with aiosqlite.connect(DB_PATH) as db: cur=await db.execute("UPDATE support_tickets SET admin_id=?,updated_at=? WHERE id=? AND status='open'",(str(admin_id),now(),int(ticket_id))); await db.commit(); return cur.rowcount>0

async def close_ticket(ticket_id:int)->bool:
    async with aiosqlite.connect(DB_PATH) as db: cur=await db.execute("UPDATE support_tickets SET status='closed',closed_at=?,updated_at=? WHERE id=? AND status='open'",(now(),now(),int(ticket_id))); await db.commit(); return cur.rowcount>0
