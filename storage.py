import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

class BuildStorage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 30000")
        return con

    @contextmanager
    def connection(self):
        con = self.connect()
        try:
            with con:
                yield con
        finally:
            con.close()

    def initialize(self):
        with self.connection() as con:
            con.execute("PRAGMA journal_mode = WAL")
            con.execute("""
                CREATE TABLE IF NOT EXISTS builds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    app_name TEXT NOT NULL,
                    package_id TEXT NOT NULL,
                    version_name TEXT NOT NULL,
                    version_code INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    status_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_builds_user_created ON builds(user_id, created_at DESC)")

    def create_build(self, user_id, chat_id, app_name, package_id, version_name, version_code):
        stamp = now_iso()
        with self.connection() as con:
            cur = con.execute(
                "INSERT INTO builds (user_id, chat_id, app_name, package_id, version_name, version_code, status, status_message, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', 'Build queued', ?, ?)",
                (user_id, chat_id, app_name, package_id, version_name, version_code, stamp, stamp)
            )
            return cur.lastrowid

    def update_status(self, build_id, status, message="", finished=False):
        stamp = now_iso()
        with self.connection() as con:
            con.execute(
                "UPDATE builds SET status=?, status_message=?, updated_at=?, finished_at=CASE WHEN ? THEN ? ELSE finished_at END WHERE id=?",
                (status, str(message)[:1500], stamp, int(finished), stamp, build_id)
            )

    def history(self, user_id, limit=10):
        with self.connection() as con:
            rows = con.execute(
                "SELECT id, app_name, package_id, version_name, status, status_message, created_at FROM builds WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def latest_active(self, user_id):
        with self.connection() as con:
            row = con.execute(
                "SELECT id, app_name, status, status_message FROM builds WHERE user_id=? AND status IN ('queued','preparing','building','signing') ORDER BY id DESC LIMIT 1",
                (user_id,)
            ).fetchone()
            return dict(row) if row else None
