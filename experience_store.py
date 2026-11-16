"""AAA 02 — registro passivo de experiências de ferramentas no SQLite existente.

Salva apenas metadados operacionais de baixo risco (sem argumentos, conteúdo de
arquivos, prompts ou nomes/caminhos privados). Nunca altera políticas sozinho.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

DEFAULT_DB = Path(__file__).resolve().parent / 'data' / 'jarvis.db'


class ExperienceStore:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS aaa_tool_experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    created_utc TEXT NOT NULL
                )""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=5)
        try:
            db.execute('PRAGMA busy_timeout=5000')
            with db:
                yield db
        finally:
            db.close()

    def record(self, session_id, tool, status, attempts):
        if not session_id or not tool:
            return
        if status not in {'verified','partial','failed','unverified'}:
            return
        with self._connect() as db:
            db.execute(
                'INSERT INTO aaa_tool_experiences '
                '(session_id,tool,status,attempts,created_utc) VALUES (?,?,?,?,?)',
                (str(session_id)[:64], str(tool)[:128], status,
                 max(1, min(int(attempts), 10)), datetime.now(timezone.utc).isoformat()),
            )

    def recent(self, limit=20):
        limit = max(1, min(int(limit), 100))
        with self._connect() as db:
            return [dict(session_id=r[0], tool=r[1], status=r[2],
                         attempts=r[3], created_utc=r[4])
                    for r in db.execute(
                        'SELECT session_id,tool,status,attempts,created_utc '
                        'FROM aaa_tool_experiences ORDER BY id DESC LIMIT ?', (limit,))]
