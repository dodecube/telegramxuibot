import os
import aiosqlite
from typing import List

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    added_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

async def init_db(db_path: str, initial_admins: List[int]):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(DB_SCHEMA)
        for uid in initial_admins:
            await db.execute("INSERT OR IGNORE INTO admins(user_id) VALUES (?)", (uid,))
        await db.commit()

async def get_admins(db_path: str) -> List[int]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT user_id FROM admins")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

async def is_admin(db_path: str, user_id: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row is not None

async def add_admin(db_path: str, user_id: int, username: str = None, added_by: int = None):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("INSERT OR REPLACE INTO admins(user_id, username, added_by) VALUES (?,?,?)", (user_id, username, added_by))
        await db.commit()

async def remove_admin(db_path: str, user_id: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
        await db.commit()
        return cur.rowcount > 0

async def list_admins_detailed(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT user_id, username, added_by, created_at FROM admins ORDER BY created_at")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
