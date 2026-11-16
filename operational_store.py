"""SQLite operacional; banco relativo ao código JARVIS, sem credenciais."""
from pathlib import Path
import sqlite3
import json
from threading import RLock

_LOCK = RLock()
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent / 'data' / 'jarvis.db'


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, project TEXT, state TEXT NOT NULL, request TEXT, updated TEXT NOT NULL, metadata TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, kind TEXT NOT NULL, created TEXT NOT NULL, payload TEXT)')
    db.commit()
    return db


def save_task(task_id, state, project=None, request=None, metadata=None):
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK, connect() as db:
        db.execute('INSERT INTO tasks (id,project,state,request,updated,metadata) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state, updated=excluded.updated, metadata=excluded.metadata', (task_id, project, state, request, now, json.dumps(metadata or {}, ensure_ascii=False)))


def add_event(task_id, kind, payload=None):
    with _LOCK, connect() as db:
        db.execute('INSERT INTO events(task_id,kind,created,payload) VALUES (?,?,?,?)', (task_id, kind, datetime.now(timezone.utc).isoformat(), json.dumps(payload or {}, ensure_ascii=False)))


def pending_tasks():
    with _LOCK, connect() as db:
        return [dict(id=row[0], project=row[1], state=row[2], request=row[3]) for row in db.execute("SELECT id,project,state,request FROM tasks WHERE state IN ('pending','waiting_confirmation','running') ORDER BY updated DESC")]
