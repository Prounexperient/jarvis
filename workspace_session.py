"""Estado local de workspace e diário recuperável; sem dependência de LLM."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid

STATE = Path.home() / '.jarvis_workspace_state.json'
BACKUP_DIR = Path.home() / '.jarvis_workspace_backups'

def load():
    try:
        data = json.loads(STATE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def save(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=str(STATE.parent), prefix='.jarvis_state_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(name, STATE)
    finally:
        if os.path.exists(name): os.unlink(name)

def activate(root):
    data = load(); data['active_root'] = str(root); data.setdefault('events', []); save(data)

def record(operation, root, path, **extra):
    data = load(); data['active_root'] = str(root)
    events = data.setdefault('events', [])
    events.append(dict(id=uuid.uuid4().hex, operation=operation, root=str(root), path=str(path), timestamp=time.time(), **extra))
    data['events'] = events[-300:]
    save(data)

def backup(path):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / (uuid.uuid4().hex + '.bak')
    shutil.copy2(path, target)
    return str(target)

def resolve_reference(root, reference):
    """Resolve referência ordinal apenas de arquivos criados neste workspace."""
    data = load(); events = data.get('events', [])
    names = []
    for event in events:
        if event.get('root') != str(root): continue
        if event.get('operation') == 'create':
            p = event['path']
            if p in names: names.remove(p)
            names.append(p)
        elif event.get('operation') == 'rename':
            old = event.get('old_path')
            if old in names: names[names.index(old)] = event['path']
        elif event.get('operation') == 'delete':
            if event['path'] in names: names.remove(event['path'])
    indexes = {'ultimo': -1, 'último': -1, 'penultimo': -2, 'penúltimo': -2}
    if reference not in indexes: return None
    index = indexes[reference]
    return names[index] if len(names) >= abs(index) else None
