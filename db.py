import os
import sqlite3
from typing import Any, Dict, Optional, List

DB_NAME = os.getenv("TRASHBOT_DB", "trashbot.db")
BOT_USERNAME = os.getenv("BOT_USERNAME", "udveri_bot")  # для реф-ссылок

def _ensure_column(c: sqlite3.Cursor, table: str, name: str, decl: str):
    c.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in c.fetchall()]
    if name not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

def init_db():
    db_path = os.path.abspath(DB_NAME)
    print(f"🗄️ DB init at: {db_path}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            first_name  TEXT,
            last_name   TEXT,
            username    TEXT,
            street      TEXT,
            house       TEXT,
            flat        TEXT,
            entrance    TEXT,
            floor       TEXT,
            city        TEXT,
            phone       TEXT,
            comment     TEXT,
            tariff      TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            bags        INTEGER DEFAULT 1,
            comment     TEXT,
            status      TEXT DEFAULT 'new',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            user_id INTEGER PRIMARY KEY,
            count   INTEGER NOT NULL DEFAULT 0
        );
    """)

    # — защита от старых версий БД
    for col in [
        "first_name", "last_name", "username", "street", "house", "flat",
        "entrance", "floor", "city", "phone", "comment", "tariff", "created_at"
    ]:
        _ensure_column(c, "users", col, "TEXT")

    _ensure_column(c, "requests", "bags", "INTEGER DEFAULT 1")
    _ensure_column(c, "requests", "comment", "TEXT")
    _ensure_column(c, "requests", "status", "TEXT DEFAULT 'new'")
    _ensure_column(c, "requests", "created_at", "TEXT DEFAULT CURRENT_TIMESTAMP")

    conn.commit()
    conn.close()
    print("🗄️ DB ready")

_ALLOWED_USER_FIELDS = {
    "street", "house", "flat", "entrance", "floor", "phone",
    "city", "comment", "first_name", "last_name", "username", "tariff"
}

def save_user_info(user_id: int, **fields):
    clean = {k: v for k, v in fields.items() if k in _ALLOWED_USER_FIELDS}
    if not clean:
        return
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
    sets = ", ".join(f"{k}=?" for k in clean.keys())
    values = list(clean.values()) + [user_id]
    c.execute(f"UPDATE users SET {sets} WHERE user_id=?", values)
    conn.commit()
    conn.close()

def get_user_info(user_id: int) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_address(user_id: int) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT street, house, flat, entrance, floor, city, phone FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def add_request(user_id: int, bags: int = 1, comment: str = "") -> int:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # добавляем user, если нет
    c.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))

    try:
        c.execute(
            "INSERT INTO requests (user_id, bags, comment) VALUES (?, ?, ?)",
            (user_id, bags, comment)
        )
        request_id = c.lastrowid
        conn.commit()
        return request_id
    finally:
        conn.close()

def get_user_id_by_request_id(request_id: int) -> Optional[int]:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM requests WHERE id=?", (request_id,))
    row = c.fetchone()
    conn.close()
    return int(row[0]) if row else None

def get_all_requests() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT r.id, r.user_id, r.bags, r.comment, r.status, r.created_at,
               u.street, u.house, u.flat, u.entrance, u.floor, u.city, u.phone,
               u.first_name, u.last_name, u.username
        FROM requests r
        LEFT JOIN users u ON u.user_id = r.user_id
        ORDER BY r.created_at DESC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def mark_request_completed(request_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE requests SET status='done' WHERE id=?", (request_id,))
    conn.commit()
    conn.close()

def clear_all_data():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM requests")
    c.execute("DELETE FROM referrals")
    c.execute("DELETE FROM users")
    conn.commit()
    conn.close()

def add_ref_count(ref_owner_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "INSERT INTO referrals (user_id, count) VALUES (?, 0) "
        "ON CONFLICT(user_id) DO NOTHING",
        (ref_owner_id,)
    )
    c.execute("UPDATE referrals SET count = count + 1 WHERE user_id=?", (ref_owner_id,))
    conn.commit()
    conn.close()

def get_ref_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

def get_ref_count(user_id: int) -> int:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT count FROM referrals WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return int(row[0]) if row else 0

