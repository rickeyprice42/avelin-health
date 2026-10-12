"""Persistent local conversation. Private data lives beside the health database."""
import sqlite3
from contextlib import contextmanager


@contextmanager
def connection(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL, content TEXT NOT NULL,
            mode TEXT, model TEXT, error TEXT,
            complete INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        with conn:
            yield conn
    finally:
        conn.close()


def history(path):
    with connection(path) as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM chat_messages ORDER BY id")]
    for row in rows:
        row["complete"] = bool(row["complete"])
        if not row["complete"] and not row["error"]:
            row["error"] = "Ответ не завершён. Попробуй отправить вопрос ещё раз."
    return rows


def start_turn(path, content):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Нужно непустое сообщение.")
    with connection(path) as conn:
        conn.execute("INSERT INTO chat_messages(role, content) VALUES('user', ?)", (content.strip(),))
        cursor = conn.execute("INSERT INTO chat_messages(role, content, complete) VALUES('assistant', '', 0)")
        return cursor.lastrowid


def finish_turn(path, message_id, content, mode=None, model=None, error=None):
    with connection(path) as conn:
        conn.execute("UPDATE chat_messages SET content=?, mode=?, model=?, error=?, complete=? WHERE id=?",
                     (content, mode, model, error, int(error is None), message_id))


def context(path):
    return [{"role": row["role"], "content": row["content"]}
            for row in history(path) if row["complete"] and not row["error"]]
