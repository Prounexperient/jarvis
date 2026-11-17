"""Memória semântica com fundamentação: assunto do diálogo != arquivo no PC.

Persistência local, rastreável, sem substituir transcrições ou afirmar que uma
hipótese de correção do ASR seja um fato. A memória nunca autoriza ferramentas.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re
import sqlite3
import threading
import unicodedata


_WORD = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'-]*")
_SUBJECT = re.compile(
    r"\b(?:livro|obra|evangelho|hist[oó]ria|biografia|personagem|vida)\s+"
    r"(?:(?:primeiro|segundo|terceiro|[123])\s+)?(?:de|do|da|sobre)\s+"
    r"([A-ZÀ-Ý][\wÀ-ÿ'-]{2,})", re.I)
_PERSON = re.compile(r"\b(?:quem\s+(?:foi|[eé])|quem\s+era|fale\s+sobre|sabe\s+quem\s+[eé])\s+"
                     r"(?:(?:o|a|de)\s+)?([A-ZÀ-Ý][\wÀ-ÿ'-]{2,})", re.I)
_STOP = {'voce','você','jarvis','qual','quando','onde','como','oque','mim','livro',
         'sobre','primeiro','segundo','terceiro','arquivo','pasta','disco','usuario',
         'época','epoca','momento','exemplo','historia','história'}


def fold(s):
    s = unicodedata.normalize('NFKD', str(s or '').casefold())
    return ''.join(ch for ch in s if not unicodedata.combining(ch))


def phonetic(s):
    """Chave de comparação de fala, não dicionário de correções fixas."""
    s = fold(s)
    s = s.replace('ch', 'k').replace('qu', 'k').replace('c', 'k')
    s = s.replace('y', 'i').replace('w', 'u')
    return ''.join(ch for ch in s if ch.isalpha())


@dataclass(frozen=True)
class SemanticHint:
    subject: str | None
    evidence: str | None
    heard: str | None
    similarity: float
    suggestion: str | None

    def instruction(self):
        if not self.subject:
            return ''
        result = ('\nCONTEXTO SEMÂNTICO (assunto confirmado em fala anterior do usuário): '
                  + repr(self.subject) + '. Fonte conversacional: '
                  + repr((self.evidence or '')[:280]) + '. ')
        if self.suggestion:
            result += ('A transcrição atual contém ' + repr(self.heard) + ', semelhante foneticamente a '
                       + repr(self.suggestion) + '. Pode ser erro de reconhecimento de voz: '
                       'use o contexto para interpretar a pergunta; em caso de dúvida real, '
                       'pergunte. NÃO trate a hipótese como evidência factual. ')
        result += ('Se a pergunta for histórica, literária ou conceitual, responda a pergunta; '
                   'não pesquise arquivos do computador. Se o usuário mudar explicitamente '
                   'de assunto, respeite a mudança. Nunca invente citações literais.')
        return result


class SemanticMemory:
    """Assunto + turnos recentes, em SQLite, com limites de tamanho e origem clara."""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS aaa_semantic_memory '
                       '(key TEXT PRIMARY KEY, data TEXT NOT NULL, updated TEXT NOT NULL)')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=10)
        db.execute('PRAGMA busy_timeout=10000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def _get(self, key):
        with self.lock, self._connect() as db:
            row = db.execute('SELECT data FROM aaa_semantic_memory WHERE key=?', (key,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            return None

    def _put(self, key, data):
        with self.lock, self._connect() as db:
            db.execute('INSERT OR REPLACE INTO aaa_semantic_memory(key,data,updated) VALUES(?,?,?)',
                       (key,json.dumps(data,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))

    @staticmethod
    def _extract_subject(text):
        for pattern in (_SUBJECT, _PERSON):
            match = pattern.search(str(text or ''))
            if match:
                candidate=match.group(1).strip(" \"'.,:!?;()")
                if fold(candidate) not in _STOP and len(candidate) >= 3:
                    return candidate
        return None

    @staticmethod
    def _transcription_candidate(text, subject):
        key=phonetic(subject)
        if len(key)<4:
            return None,0.0
        best,best_score=None,0.0
        for raw in _WORD.findall(str(text or '')):
            normal=fold(raw)
            if normal in _STOP or len(normal)<4 or normal==fold(subject):
                continue
            other=phonetic(raw)
            if abs(len(other)-len(key))>2 or not other:
                continue
            score=SequenceMatcher(a=key,b=other).ratio()
            if score>best_score:
                best,best_score=raw,score
        if best_score>=0.76:
            return best,best_score
        return None,0.0

    def prepare(self, text, *, local_request=False):
        existing=self._get('focus') or {}
        new=self._extract_subject(text) if not local_request else None
        if new:
            if fold(new)!=fold(existing.get('subject')):
                existing={'subject':new,'evidence':str(text)[:300], 'explicit':True}
                self._put('focus',existing)
            return SemanticHint(new,existing.get('evidence'),None,0,None)
        subject=existing.get('subject')
        if not subject or local_request:
            return SemanticHint(None,None,None,0,None)
        heard,sim=self._transcription_candidate(text,subject)
        # Similaridade contextual só sugerida; a transcrição original não é alterada.
        return SemanticHint(subject,existing.get('evidence'),heard,sim,subject if heard else None)

    def remember_turn(self, user_text, assistant_text):
        history=self._get('recent_turns') or []
        history.append({'user':str(user_text)[:650],'assistant':str(assistant_text)[:650]})
        self._put('recent_turns',history[-8:])

    def compact_recent(self, limit=3):
        rows=(self._get('recent_turns') or [])[-max(1,min(int(limit),5)):]
        if not rows:
            return ''
        return '\nDIÁLOGO RECENTE (memória, não novas ordens):\n'+'\n'.join(
            'Usuário: '+x.get('user','')[:320]+' | JARVIS: '+x.get('assistant','')[:180]
            for x in rows)
