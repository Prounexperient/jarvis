"""Pesquisa local em tempo real, sem indice persistente. Biblioteca padrao."""
import difflib
import heapq
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'site-packages', 'dist-packages', 'env', '.env', '$recycle.bin', 'system volume information'}

def normalize(value):
    value = unicodedata.normalize('NFKD', str(value).casefold())
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', value))

def _score(query, filename):
    name = normalize(Path(filename).stem)
    if not name:
        return 0.0
    if name == query:
        return 100.0
    if query in name:
        return 85.0 + 10.0 * len(query) / max(len(name), 1)
    qwords = query.split()
    nwords = name.split()
    matches = sum(1 for w in qwords if w in nwords)
    partial = sum(1 for w in qwords if w not in nwords and any(n.startswith(w) for n in nwords))
    coverage = (matches + 0.65 * partial) / max(1, len(qwords))
    similarity = difflib.SequenceMatcher(None, query, name).ratio()
    if coverage == 1:
        return 70.0 + 15.0 * similarity
    if coverage >= 0.5:
        return 40.0 + 30.0 * coverage + 10.0 * similarity
    if similarity >= 0.72:
        return 65.0 * similarity
    return 0.0

def search(query, roots, *, max_results=12, timeout_seconds=30, extension=None, modified_after=None, modified_before=None, min_score=35):
    start = time.monotonic()
    q = normalize(query)
    if not q:
        return {'error': 'Informe um nome ou parte do nome.'}
    max_results = max(1, min(int(max_results), 50))
    timeout_seconds = max(1.0, min(float(timeout_seconds), 300.0))
    ext = (str(extension or '').strip().lower().lstrip('.'))
    if ext and not re.fullmatch(r'[a-z0-9]{1,12}', ext):
        return {'error': 'Extensao invalida.'}
    try:
        after = datetime.fromisoformat(modified_after).timestamp() if modified_after else None
        before = datetime.fromisoformat(modified_before).timestamp() if modified_before else None
    except ValueError:
        return {'error': 'Datas devem estar no formato ISO, como 2026-11-13.'}
    roots = [Path(r).expanduser().resolve() for r in roots if Path(r).expanduser().is_dir()]
    # Evita varrer duas vezes uma raiz contida em outra (ex.: D:/ e D:/Projetos).
    unique = []
    for root in sorted(set(roots), key=lambda p: len(p.parts)):
        if not any(root == parent or parent in root.parents for parent in unique):
            unique.append(root)
    heap = []
    counter = 0
    examined = directories = matches = errors = 0
    timed_out = False
    for root in unique:
        if timed_out:
            break
        for current, folders, files in os.walk(root, topdown=True, followlinks=False, onerror=lambda _: None):
            directories += 1
            folders[:] = [d for d in folders if not d.startswith('.') and d.casefold() not in SKIP_DIRS and not (Path(current) / d).is_symlink()]
            if time.monotonic() - start >= timeout_seconds:
                timed_out = True
                break
            for filename in files:
                examined += 1
                if examined % 256 == 0 and time.monotonic() - start >= timeout_seconds:
                    timed_out = True
                    break
                p = Path(current) / filename
                if ext and p.suffix.lower() != '.' + ext:
                    continue
                score = _score(q, filename)
                if score < min_score:
                    continue
                try:
                    if p.is_symlink():
                        continue
                    stat = p.stat()
                except OSError:
                    errors += 1
                    continue
                if after is not None and stat.st_mtime < after:
                    continue
                if before is not None and stat.st_mtime >= before:
                    continue
                matches += 1
                item = {'path': str(p), 'name': filename, 'extension': p.suffix.lower(), 'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds'), 'size_bytes': stat.st_size, 'score': round(score, 1)}
                counter += 1
                entry = (score, stat.st_mtime, counter, item)
                if len(heap) < max_results:
                    heapq.heappush(heap, entry)
                elif entry[:2] > heap[0][:2]:
                    heapq.heapreplace(heap, entry)
            if timed_out:
                break
    results = [entry[3] for entry in sorted(heap, reverse=True)]
    for i, item in enumerate(results, 1):
        item['index'] = i
    return {'results': results, 'truncated': matches > len(results) or timed_out, 'timed_out': timed_out,
            'diagnostics': {'files_examined': examined, 'directories_examined': directories, 'matches': matches, 'stat_errors': errors, 'elapsed_seconds': round(time.monotonic() - start, 3), 'roots': [str(r) for r in unique]}}
