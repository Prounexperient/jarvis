"""AAA 06 — navegador contextual, fundamentado no sistema de arquivos.

Disco -> diretório -> vizinhos -> catálogo por categoria -> páginas/cursor.
Não executa shell, não cria nem exclui arquivos. Persistência é de referências
verificadas, não de caminhos sugeridos pelo modelo. Cada mudança é anunciada
somente depois de verificar que a origem pode ser acessada.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import RLock
import json
import ntpath
import os
import secrets
import re
import sqlite3
import time
import unicodedata
from uuid import uuid4

from explicit_folder_controller import fold, parse_folder_request
from media_intent import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, MediaIntentResolver
from task_controller import TaskController

AUDIO = frozenset('.' + x for x in AUDIO_EXTENSIONS)
VIDEO = frozenset('.' + x for x in VIDEO_EXTENSIONS)
DOCUMENT = frozenset({'.pdf', '.txt', '.doc', '.docx', '.odt', '.rtf', '.md', '.csv', '.xlsx', '.xls', '.pptx'})
CODE = frozenset({'.py', '.sql', '.java', '.js', '.jsx', '.ts', '.tsx', '.json', '.yaml', '.yml', '.html', '.css', '.xml'})
IMAGE = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tiff', '.svg'})
GROUPS = ('pastas', 'audio', 'video', 'documentos', 'codigo', 'imagens', 'outros')
NOUNS = {'audio': ('musica', 'musicas', 'audio', 'audios', 'faixa', 'faixas'),
         'video': ('video', 'videos', 'filme', 'filmes'),
         'documentos': ('documento', 'documentos', 'pdf', 'texto', 'textos'),
         'codigo': ('codigo', 'codigos', 'script', 'scripts'),
         'imagens': ('imagem', 'imagens', 'foto', 'fotos')}
IGNORED = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', '.idea', '.vs'}
NUMBER = {'primeira': 1, 'primeiro': 1, 'segunda': 2, 'segundo': 2,
          'terceira': 3, 'terceiro': 3, 'quarta': 4, 'quarto': 4,
          'quinta': 5, 'quinto': 5, 'sexta': 6, 'sexto': 6,
          'setima': 7, 'setimo': 7, 'oitava': 8, 'oitavo': 8,
          'nona': 9, 'nono': 9, 'decima': 10, 'decimo': 10}


def _norm(value):
    return unicodedata.normalize('NFKD', str(value or '').casefold()).encode('ascii', 'ignore').decode()


def _label(path):
    return os.path.basename(os.path.normpath(str(path))) or str(path)


def _drive(path):
    return ntpath.splitdrive(str(path))[0].upper() or 'local'


def _same_path(a, b):
    return bool(a and b and os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b)))


def _category(name):
    ext = os.path.splitext(name)[1].casefold()
    if ext in AUDIO: return 'audio'
    if ext in VIDEO: return 'video'
    if ext in DOCUMENT: return 'documentos'
    if ext in CODE: return 'codigo'
    if ext in IMAGE: return 'imagens'
    return 'outros'


def _group(text, *, exclude_folder=True):
    normalized = _norm(text)
    # 'pasta Vídeos e reproduza o primeiro áudio' -> audio, not video.
    if exclude_folder:
        matcher = list(re.finditer(r'\b(reproduza|reproduzir|reproduz|reproduzo|toque|tocar|carregue|abra\s+o|abra\s+a)\b', normalized))
        if matcher:
            normalized = normalized[matcher[-1].end():]
        normalized = re.split(r'\b(?:na|da|dessa|desta)\s+pasta\b', normalized)[0]
    for group in ('audio', 'video', 'documentos', 'codigo', 'imagens'):
        if any(re.search(r'\b'+x+r'\b', normalized) for x in NOUNS[group]):
            return group
    if re.search(r'\b(subpastas|diretorios|pastas)\b', normalized):
        return 'pastas'
    return None


def _ordinal(text):
    s = _norm(text)
    explicit = re.search(r'\b(?:arquivo|musica|video|audio|item|pasta|numero|documento|codigo|imagem|pdf|foto)\s+(\d+)\b', s)
    if explicit: return int(explicit.group(1))
    match = re.search(r'\b('+'|'.join(NUMBER)+r'|ultima|ultimo|proxima|proximo|anterior|precedente|seguinte)\b', s)
    if not match: return None
    value = match.group(1)
    if value in NUMBER: return NUMBER[value]
    if value in ('ultima', 'ultimo'): return 'last'
    if value in ('proxima', 'proximo', 'seguinte'): return 'next'
    return 'prev'


def _file_id(path):
    st = os.stat(path, follow_symlinks=True)
    # Some network filesystems report inode 0. Canonical path is the fallback.
    if st.st_ino:
        return f'{st.st_dev}:{st.st_ino}'
    return os.path.normcase(os.path.realpath(path))


class NavigationWorkspace:
    """Persistent foreground workspace. One active context, many resumable contexts.

    Search and catalogs are filesystem-backed, bounded, and nonrecursive per
    catalog. An incomplete catalog never claims an exact total or a last item.
    """

    def __init__(self, db_path, config):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.lock = RLock()
        limits = config.get('navigation_workspace', {})
        self.page_size = min(50, max(1, int(limits.get('page_size', 10))))
        self.max_scan = min(100000, max(50, int(limits.get('max_catalog_items', 30000))))
        self.scan_seconds = min(30, max(0.1, float(limits.get('scan_timeout_seconds', 6))))
        self.search_seconds = min(30, max(0.1, float(limits.get('search_timeout_seconds', 8))))
        self.max_candidates = min(100, max(2, int(limits.get('max_candidates', 30))))
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS aaa_navigation_workspace '
                       '(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        with self._db() as db:
            row = db.execute('SELECT value FROM aaa_navigation_workspace WHERE key=?', ('state',)).fetchone()
        try:
            self.state = json.loads(row[0]) if row else {}
        except (ValueError, TypeError):
            self.state = {}
        self.state.setdefault('active', None)
        self.state.setdefault('contexts', {})
        self.state.setdefault('history', [])
        self.state.setdefault('forward', [])
        self.state.setdefault('pending', None)
        self.state.setdefault('last_media_group', None)
        self.state.setdefault('media_preference', None)
        self.last_evidence=None

    @contextmanager
    def _db(self):
        with self.lock:
            db = sqlite3.connect(str(self.db_path), timeout=10)
            try:
                db.execute('PRAGMA busy_timeout=10000')
                with db:
                    yield db
            finally:
                db.close()

    def _save(self):
        # Context snapshots are bounded by max_scan and persist across restart.
        value = json.dumps(self.state, ensure_ascii=False, separators=(',', ':'))
        with self._db() as db:
            db.execute('INSERT OR REPLACE INTO aaa_navigation_workspace VALUES (?,?)', ('state', value))

    def _roots(self):
        from tools import _resolve_roots
        return [p.resolve() for p in _resolve_roots(self.config) if p.is_dir()]

    def _allowed_path(self, path, *, directory=True):
        # Resolve symlinks/junctions before authorization. No escape via ..
        p = Path(path).expanduser()
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise PermissionError('Atalhos e junctions não são selecionados como contexto.')
        real = p.resolve(strict=True)
        roots = self._roots()
        if not any(real == root or root in real.parents for root in roots):
            raise PermissionError('Diretório fora das áreas autorizadas.')
        if (directory and not real.is_dir()) or (not directory and not real.is_file()):
            raise FileNotFoundError('O caminho não está disponível.')
        return real

    def _catalog(self, path):
        p = self._allowed_path(path)
        files = {g: [] for g in GROUPS}
        start = time.monotonic()
        partial = False
        scanned = 0
        with os.scandir(p) as iterator:
            for entry in iterator:
                if scanned >= self.max_scan or time.monotonic() - start > self.scan_seconds:
                    partial = True
                    break
                scanned += 1
                try:
                    if entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction()):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.casefold() not in IGNORED:
                            files['pastas'].append(entry.name)
                    elif entry.is_file(follow_symlinks=False):
                        files[_category(entry.name)].append(entry.name)
                except (OSError, PermissionError):
                    partial = True
        for value in files.values():
            value.sort(key=lambda x: (_norm(x), x))
        return files, partial

    def _context(self, path, *, refresh=True):
        real = self._allowed_path(path)
        ident = _file_id(real)
        for ctx in self.state['contexts'].values():
            if ctx.get('identity') == ident or _same_path(ctx['path'], real):
                if refresh:
                    files, partial = self._catalog(real)
                    ctx.update(files=files, partial=partial, path=str(real), identity=ident)
                    for group, cursor in list(ctx.get('cursor', {}).items()):
                        if cursor and cursor not in ctx['files'].get(group, []):
                            ctx['cursor'][group] = None
                return ctx
        files, partial = self._catalog(real)
        ctx = {'id': uuid4().hex, 'identity': ident, 'path': str(real),
               'drive': _drive(real), 'folder': _label(real),
               'files': files, 'partial': partial,
               'page': {g: 1 for g in GROUPS}, 'cursor': {g: None for g in GROUPS},
               'last_group': 'pastas'}
        self.state['contexts'][ctx['id']] = ctx
        return ctx

    def current(self):
        return self.state['contexts'].get(self.state['active'])

    def _find_by_path(self, path):
        for ctx in self.state['contexts'].values():
            if _same_path(ctx['path'], path):
                return ctx
        return None

    def _summary(self, ctx):
        labels = [('pastas', 'pastas'), ('video', 'vídeos'), ('audio', 'músicas'),
                  ('documentos', 'documentos'), ('codigo', 'códigos'),
                  ('imagens', 'imagens'), ('outros', 'outros arquivos')]
        line = ', '.join(f"{len(ctx['files'][group])} {description}" for group, description in labels)
        if ctx['partial']:
            line = 'Inventário parcial: pelo menos ' + line
        return line

    def _activate(self, ctx, *, navigation=None):
        old = self.current()
        if old and old['id'] != ctx['id']:
            self.state['history'].append(old['id'])
            self.state['history'] = self.state['history'][-100:]
            self.state['forward'].clear()
        self.state['active'] = ctx['id']
        self.state['pending'] = None
        self.state['media_preference'] = None
        if navigation:
            navigation._set('active_directory', ctx['path'])
            # Do not allow the previous folder's media cursor to leak into this one.
            previous = navigation.state.get('media_sequence') or {}
            if previous.get('directory') and not _same_path(previous['directory'],ctx['path']):
                navigation._set('media_sequence', {})
        self._save()
        self.last_evidence=('verified','Contexto ativado a partir de diretório acessível.')
        if old and old['id'] != ctx['id']:
            return ('Estou deixando o contexto {} no disco {} e entrando no contexto {} no disco {}. '.format(
                old['folder'],old['drive'],ctx['folder'],ctx['drive']))
        if old and old['id'] == ctx['id']:
            return 'Mantive o contexto {}. '.format(ctx['folder'])
        return 'Entrei no contexto {} no disco {}. '.format(ctx['folder'],ctx['drive'])

    def _page(self, ctx, group, page=None):
        if group not in GROUPS:
            return 'Categoria desconhecida.'
        items = ctx['files'][group]
        total = len(items)
        pages = max(1, (total + self.page_size - 1) // self.page_size)
        selected = page if page is not None else ctx['page'].get(group, 1)
        if not 1 <= selected <= pages:
            return 'Essa página não existe no catálogo atual.'
        ctx['page'][group] = selected
        ctx['last_group'] = group
        self._save()
        self.last_evidence=('verified','Página exibida do catálogo persistido anteriormente verificado.')
        start = (selected-1)*self.page_size
        prefix = 'Pelo menos ' if ctx['partial'] else ''
        heading = '{}{} itens em {}. Página {} de {}. '.format(prefix, total, group, selected,
                                                  str(pages) if not ctx['partial'] else 'pelo menos '+str(pages))
        rows = '; '.join('{}: {}'.format(i+1, name)
                         for i,name in enumerate(items[start:start+self.page_size],start))
        return heading + (rows if rows else 'Nenhum item nesta categoria.')

    def _candidates(self, name, drive=None):
        """Prefer current children/siblings; explicit drive searches all allowed roots."""
        name = _norm(name).strip()
        if name.startswith('de '): name = name[3:]
        # Translate display names without assuming an exact filesystem spelling.
        aliases = {'video': {'video','videos'}, 'videos': {'video','videos'},
                   'musica': {'musica','music','musicas'},
                   'documentos': {'documentos','documents'},
                   'fotos': {'fotos','pictures','imagens'}}
        values = aliases.get(name, {name})
        seen = set()
        selected = []
        deadline = time.monotonic()+self.search_seconds
        incomplete = False
        roots = self._roots()
        if drive:
            roots = [p for p in roots if _drive(p) == drive.upper().rstrip(':')+':']
        def add(p):
            if len(selected) >= self.max_candidates: return False
            try:
                validated = self._allowed_path(p)
                if _norm(validated.name) not in values:
                    return True
                ident = _file_id(validated)
                if ident not in seen:
                    seen.add(ident)
                    selected.append(str(validated))
            except (PermissionError, FileNotFoundError, OSError):
                return True
            return True
        # When a drive is given, all same-name folders on that drive compete.
        if not drive and self.current():
            active = Path(self.current()['path'])
            nearby = [active]
            for base in (active, active.parent):
                try:
                    self._allowed_path(base)
                    nearby.extend(base.iterdir())
                except (OSError, PermissionError):
                    pass
            for p in nearby:
                if p.is_dir() and _norm(p.name) in values:
                    add(p)
            if selected:
                return selected, False
        for ctx in self.state['contexts'].values():
            p = Path(ctx['path'])
            if (not drive or _drive(p)==drive.upper().rstrip(':')+':') and _norm(p.name) in values:
                add(p)
        for root in roots:
            if time.monotonic()>deadline:
                incomplete = True
                break
            if _norm(root.name) in values:
                add(root)
            for base, folders, _ in os.walk(root, followlinks=False):
                if time.monotonic()>deadline or len(selected)>=self.max_candidates:
                    incomplete=True
                    break
                folders[:] = [f for f in folders if f.casefold() not in IGNORED and not f.startswith('.')
                              and not (Path(base)/f).is_symlink()]
                for folder in folders:
                    if _norm(folder) in values:
                        add(Path(base)/folder)
            if incomplete: break
        selected.sort(key=lambda p: (p.casefold(),p))
        return selected,incomplete

    def _choose(self, candidates, original, *, navigation=None, skills=None, incomplete=False):
        # Catalog each candidate to provide user-grounded counts (no assumptions).
        prepared = []
        for path in candidates:
            try:
                prepared.append(self._context(path))
            except (OSError, ValueError, PermissionError):
                continue
        if not prepared:
            self.state['pending'] = None
            self._save()
            return 'As pastas encontradas não estão acessíveis. Mantive o contexto anterior.'
        if len(prepared)>1:
            self.state['pending'] = {'ids':[c['id'] for c in prepared], 'request':original,
                                     'incomplete':incomplete, 'created':time.time()}
            self._save()
            rows = ['Pasta {}: {} — {}.'.format(i,c['path'],self._summary(c))
                    for i,c in enumerate(prepared,1)]
            self.state['pending']['page']=1
            self._save()
            return self._pending_page()
        return self._enter(prepared[0], original, navigation=navigation, skills=skills)

    def _pending_page(self):
        pending = self.state.get('pending') or {}
        ids = pending.get('ids') or []
        page = pending.get('page',1)
        pages = max(1,(len(ids)+self.page_size-1)//self.page_size)
        page=max(1,min(page,pages))
        pending['page']=page
        self._save()
        self.last_evidence=('partial','Há múltiplas pastas verificadas; aguardando escolha do usuário.')
        start=(page-1)*self.page_size
        rows=[]
        for i,cid in enumerate(ids[start:start+self.page_size],start+1):
            c=self.state['contexts'][cid]
            rows.append('Pasta {}: {} — {}.'.format(i,c['path'],self._summary(c)))
        quantity=('pelo menos {}' if pending.get('incomplete') else '{}').format(len(ids))
        return ('Encontrei {} pastas candidatas. Página {} de {}. {} '
                'Qual delas deseja utilizar?'.format(quantity,page,pages,' '.join(rows)))

    def _enter(self, ctx, original, *, navigation=None, skills=None):
        # A user explicitly asking Explorer opening gets an actual tool result.
        words = _norm(original)
        wants_explorer = bool(re.search(r'\b(abri?r?|abra|abre)\s+(?:a\s+)?pasta\b', words))
        if wants_explorer and skills is not None:
            result = skills.execute('open_directory', {'path':ctx['path']})
            if not isinstance(result,dict) or result.get('error') or not _same_path(result.get('opened_directory'),ctx['path']):
                return 'Não consegui abrir a pasta no Explorador; mantive o contexto anterior.'
            if navigation:
                navigation.observe('open_directory',result,{'path':ctx['path']})
        msg = self._activate(ctx,navigation=navigation)
        # Compound user request must complete without an extra question.
        if self._wants_media(original):
            output = self._play(original, skills, navigation)
            return msg + output
        return msg + self._summary(ctx)+'.'

    @staticmethod
    def _wants_media(text):
        s = _norm(text)
        return bool(re.search(r'\b(reproduz\w*|toque|tocar|carregue|produza)\b',s) or
                    re.search(r'\babra\s+(?:o\s+)?(?:primeiro|segundo|ultimo|video|audio|arquivo|musica)\b',s))

    def _play(self, text, skills, navigation, *, authorization_text=None):
        ctx = self.current()
        if ctx is None or skills is None:
            return 'Não há contexto de pasta selecionado.'
        kind = _group(text) or ctx.get('last_media_group') or self.state.get('last_media_group')
        if kind not in ('video','audio'):
            kinds = [g for g in ('audio','video') if ctx['files'][g]]
            if len(kinds)!=1:
                return 'Informe se deseja música ou vídeo; existem categorias diferentes nesta pasta.'
            kind = kinds[0]
        entries = ctx['files'][kind]
        if not entries:
            return 'Não há {} nesta pasta.'.format('músicas' if kind=='audio' else 'vídeos')
        ordinal = _ordinal(text)
        if ctx['partial']:
            return ('O inventário é parcial. Não posso garantir a numeração global '
                    'nem identificar com segurança o primeiro ou último arquivo.')
        if 'aleatori' in _norm(text) or 'sortei' in _norm(text):
            target = secrets.randbelow(len(entries))
        elif ordinal in ('next','prev'):
            current_name=ctx['cursor'].get(kind)
            if current_name not in entries:
                return 'Não há posição ativa nessa categoria. Escolha um arquivo primeiro.'
            target = entries.index(current_name)+(1 if ordinal=='next' else -1)
        elif ordinal=='last':
            if ctx['partial']:
                return 'O inventário é parcial; não posso identificar o último arquivo.'
            target = len(entries)-1
        elif isinstance(ordinal,int):
            target = ordinal-1
        else:
            # Do not automatically start playback just because a folder was mentioned.
            self.state['media_preference']={'context':ctx['id'],'group':kind,'request':text,
                                            'created':time.time()}
            self._save()
            return ('Há {} {} nesta pasta. Prefere escolher pelo número? '
                    'Se não tiver preferência, diga sem preferência para reprodução aleatória.'.format(
                        len(entries),'músicas' if kind=='audio' else 'vídeos'))
        if not 0 <= target < len(entries):
            return 'O índice solicitado está fora dos limites de {}.'.format(kind)
        path = Path(ctx['path'])/entries[target]
        try:
            verified=self._allowed_path(path,directory=False)
            if verified.parent != Path(ctx['path']):
                return 'O arquivo não está diretamente na pasta selecionada.'
        except (OSError,PermissionError):
            return 'O arquivo não está mais disponível; atualize o catálogo.'
        # TaskController receives an evidence-backed cursor for contextual media.
        if navigation is not None:
            previous = ctx['cursor'].get(kind)
            rows=[{'path':str(Path(ctx['path'])/x)} for x in entries]
            at = entries.index(previous) if previous in entries else None
            navigation._set('media_sequence',{'directory':ctx['path'], 'results':rows,
                'current_index':at,'truncated':ctx['partial']})
            navigation._set('active_directory',ctx['path'])
        guard=TaskController(authorization_text or text,navigation=navigation)
        denial=guard.inspect('open_file',{'path':str(verified)},
                             verified_origin=ctx['path'], verified_media_context=True)
        if denial:
            return 'A abertura não foi autorizada: '+denial
        result=skills.execute('open_file',{'path':str(verified)})
        if not isinstance(result,dict) or result.get('error') or not _same_path(result.get('opened'),verified):
            return 'Não foi possível confirmar a abertura do arquivo.'
        self.state['media_preference']=None
        ctx['cursor'][kind]=entries[target]
        ctx['last_media_group']=kind
        self.state['last_media_group']=kind
        ctx['page'][kind]=1+target//self.page_size
        if navigation:
            navigation.observe('open_file',result,{'path':str(verified)})
        self._save()
        return 'Abri {} número {}: {}.'.format('música' if kind=='audio' else 'vídeo',target+1,entries[target])

    def _document_action(self, text, skills, navigation):
        """Index-based reading/opening of non-media, never execute code files."""
        ctx=self.current()
        if not ctx or skills is None:
            return 'Não há contexto de pasta verificado.'
        group=_group(text) or ctx['last_group']
        if group not in ('documentos','codigo','imagens'):
            return None
        ordinal=_ordinal(text)
        entries=ctx['files'][group]
        if not entries:
            return 'Não encontrei itens dessa categoria na pasta.'
        if ordinal=='last':
            if ctx['partial']:
                return 'O catálogo é parcial; não há um último item confirmado.'
            index=len(entries)-1
        elif isinstance(ordinal,int):
            index=ordinal-1
        else:
            return None
        if not 0<=index<len(entries):
            return 'O índice está fora dos limites dessa categoria.'
        try:
            path=self._allowed_path(Path(ctx['path'])/entries[index],directory=False)
            if path.parent != Path(ctx['path']):
                return 'Esse arquivo não pertence ao diretório confirmado.'
        except (OSError,PermissionError):
            return 'O arquivo não está mais disponível; atualize o catálogo.'
        read=bool(re.search(r'\b(leia|ler|leitura|analise|analisar|examine|resuma)\b',_norm(text)))
        if group=='codigo' and not read:
            return 'Arquivos de código não serão abertos pelo aplicativo padrão, pois isso poderia executá-los. Peça para ler ou inspecionar o item.'
        name='read_document' if read else 'open_file'
        guard=TaskController(text,navigation=navigation)
        denial=guard.inspect(name,{'path':str(path)},verified_origin=ctx['path'])
        if denial:
            return 'A operação não foi autorizada: '+denial
        response=skills.execute(name,{'path':str(path)})
        if not isinstance(response,dict) or response.get('error'):
            return 'Não foi possível confirmar a operação com esse documento.'
        if read:
            if response.get('path') and not _same_path(response['path'],path):
                return 'A ferramenta devolveu outro caminho; não vou apresentar o conteúdo.'
            content=response.get('content',response.get('text'))
            if not isinstance(content,str):
                return 'A ferramenta não conseguiu extrair texto verificável.'
            ctx['last_group']=group
            ctx['page'][group]=index//self.page_size+1
            self._save()
            suffix=' O trecho é parcial.' if response.get('truncated') or len(content)>420 else ''
            return 'Li {}. Trecho: {}{}'.format(path.name,content[:420],suffix)
        if not _same_path(response.get('opened'),path):
            return 'A ferramenta não confirmou a abertura do arquivo solicitado.'
        if navigation: navigation.observe('open_file',response,{'path':str(path)})
        ctx['last_group']=group
        ctx['page'][group]=index//self.page_size+1
        self._save()
        return 'Abri {} número {}: {}.'.format(group,index+1,path.name)

    def _restore(self, target_id, *, forward=False, navigation=None):
        ctx = self.state['contexts'].get(target_id)
        if not ctx:
            return 'O contexto anterior não está mais disponível.'
        try:
            self._context(ctx['path'],refresh=True)
        except (OSError,PermissionError):
            return 'Não consegui acessar o contexto anterior; mantive o contexto atual.'
        previous = self.current()
        if previous and previous['id'] != ctx['id']:
            (self.state['forward'] if forward else self.state['history']).append(previous['id'])
        # Remove a posição do histórico apenas após validar a origem.
        stack = self.state['history'] if forward else self.state['forward']
        if stack and stack[-1] == target_id:
            stack.pop()
        self.state['active']=ctx['id']
        self.state['pending']=None
        if navigation:
            navigation._set('active_directory',ctx['path'])
            navigation._set('media_sequence',{})
        self._save()
        self.last_evidence=('verified','Diretório anterior foi revalidado antes da restauração.')
        before = previous['folder'] if previous else 'anterior'
        return ('Estou deixando o contexto {} e retornando a {} no disco {}. '.format(
            before,ctx['folder'],ctx['drive']) + self._summary(ctx)+'.')

    def handle(self, text, skills, navigation):
        """Return a complete spoken response, or None for unrelated utterances.

        Pending candidate selection is interpreted before media ordinals, so
        'a segunda' is a folder choice and not media item 2.
        """
        self.last_evidence=None
        s = _norm(text).strip(' .!?')
        if not s:
            return None
        # Simulation gateways may supply Windows paths without creating them;
        # preserve the existing AAA03/04 mechanism in that case.
        if not self._roots():
            return None
        with self.lock:
            media_pref=self.state.get('media_preference')
            if media_pref and (time.time()-float(media_pref.get('created',0))>180):
                self.state['media_preference']=None
                self._save()
                media_pref=None
            if media_pref and not self.state.get('pending'):
                ctx_pref=self.current()
                if ctx_pref and ctx_pref['id']==media_pref['context']:
                    if s in ('nao','não','sem preferencia','sem preferencias','aleatorio','aleatoria','escolha voce','pode escolher'):
                        phrase=('Reproduza aleatoriamente uma música' if media_pref['group']=='audio'
                                else 'Reproduza aleatoriamente um vídeo')
                        return self._play(phrase,skills,navigation,authorization_text=media_pref['request'])
                    if _ordinal(s) is not None and re.fullmatch(
                            r'(?:(?:o|a|numero|item)\s+)?(?:primeiro|primeira|segundo|segunda|terceiro|terceira|quarto|quarta|ultimo|ultima|\d+)',s):
                        label='música' if media_pref['group']=='audio' else 'vídeo'
                        return self._play('Reproduza o {} {}'.format(s,label),skills,navigation,authorization_text=media_pref['request'])
                    if s in ('sim','quero escolher','com preferencia'):
                        return ('Você tem {} {}. '.format(len(ctx_pref['files'][media_pref['group']]),
                                  'músicas' if media_pref['group']=='audio' else 'vídeos')+
                                'Diga o índice que deseja ou peça a lista paginada.')
            pending = self.state.get('pending')
            if pending and time.time()-float(pending.get('created',0))>300:
                self.state['pending']=None
                self._save()
                pending=None
            if pending:
                if re.search(r'\b(cancelar|cancele|desista)\b',s):
                    self.state['pending']=None
                    self._save()
                    return 'Cancelei a seleção de pasta. O contexto anterior permanece ativo.'
                # Ordinals inside unrelated questions ('segundo livro') are NOT
                # selections of the second folder.
                choice_language = bool(re.match(
                    r'^(?:(?:a|o|escolho|opcao|escolha|quero|a pasta|pasta)\s+)?'
                    r'(?:primeiro|primeira|segundo|segunda|terceiro|terceira|quarto|quarta|\d+)'
                    r'(?:\s+(?:pasta|opcao))?(?:[,. ]|$)',s))
                idx = _ordinal(text) if choice_language else None
                choice = None
                if isinstance(idx,int) and 1 <= idx <= len(pending['ids']):
                    choice = idx-1
                elif re.fullmatch(r'(?:pasta\s+)?[\w-]+\s+(\d+)',s):
                    number=int(re.search(r'(\d+)$',s).group(1))
                    if 1<=number<=len(pending['ids']): choice=number-1
                elif re.search(r'\b(essa|a|opcao|escolho)\s+\d+\b',s):
                    digit = int(re.search(r'\b(\d+)\b',s).group(1))
                    if 1<=digit<=len(pending['ids']): choice=digit-1
                else:
                    for i,cid in enumerate(pending['ids']):
                        p=self.state['contexts'][cid]['path']
                        if _norm(p) in s:
                            choice=i
                            break
                if choice is not None:
                    ctx=self.state['contexts'].get(pending['ids'][choice])
                    if not ctx:
                        return 'Essa opção deixou de existir.'
                    try:
                        self._context(ctx['path'])
                    except (OSError,PermissionError):
                        return 'A pasta escolhida deixou de estar acessível; mantenho o contexto anterior.'
                    original=pending['request']
                    # A selection may also carry an explicit new action:
                    # 'a segunda e reproduza o primeiro vídeo'.
                    extra=re.search(r'\b(?:e\s+)?(reproduz\w*|toque|tocar|carregue)\b.*$',s)
                    if extra and not self._wants_media(original):
                        original += ' e ' + extra.group(0)
                    return self._enter(ctx,original,navigation=navigation,skills=skills)
                if re.search(r'\b(proxima|anterior)\s+pagina|pagina\s+(proxima|anterior)\b',s):
                    inc = -1 if 'anterior' in s else 1
                    total=max(1,(len(pending['ids'])+self.page_size-1)//self.page_size)
                    pending['page']=min(total,max(1,pending.get('page',1)+inc))
                    return self._pending_page()
                # An unrelated conversation never gets trapped in a pending choice.
                if not re.search(r'\b(vai|va|entre|abra|procure|busque|localize|encontre|disco|pasta)\b',s):
                    return None
                # A new explicit navigation request supersedes candidate selection.
                self.state['pending']=None
                self._save()

            ctx=self.current()
            # Another verified tool/skill may have moved the navigation focus.
            # Never replay an old cursor against the previous workspace path.
            observed=(getattr(navigation,'state',{}) or {}).get('active_directory') if navigation else None
            if (ctx and observed and not _same_path(observed,ctx['path'])):
                try:
                    newer=self._context(observed,refresh=True)
                except (OSError,PermissionError):
                    return 'A pasta ativa mudou para outro local, mas não tenho acesso a ele. Não reutilizei a sequência anterior.'
                announced=self._activate(newer,navigation=navigation)
                continued=self.handle(text,skills,navigation)
                return announced+(continued if continued is not None else self._summary(newer)+'.')
            # Do not hijack unrelated knowledge, quotes, code or unrestricted searches.
            is_nav=bool(re.search(r'\b(pasta|pastas|diretorio|diretorios|disco|unidade|contexto|pagina)\b',s) and
                        re.search(r'\b(abri?r?|abra|abre|va|vai|entre|entrar|volte|voltar|suba|subir|avance|avancar|listar|liste|mostre|mostrar|procure|encontre|troque|mude|pagina)\b',s))
            if ctx and re.search(r'^(?:va|vai|entre|volte|retorne|mude|troque)\s+(?:para\s+)?(?:a\s+|o\s+|ao\s+|na\s+|no\s+)?[a-z]',s):
                is_nav=True
            if ctx and re.search(r'\b(liste|listar|mostre|mostrar|exiba)\b',s) and _group(text,exclude_folder=False):
                is_nav=True
            if ctx and re.search(r'\b(atualize|atualizar|recarregue|reindexe)\s+(?:o\s+)?(?:catalogo|conteudo|lista)\b',s):
                is_nav=True
            is_document=bool(ctx and re.search(r'\b(abra|abrir|leia|ler|analise|examine|resuma)\b',s)
                             and (_group(text) in ('documentos','codigo','imagens') or
                                  ctx['last_group'] in ('documentos','codigo','imagens'))
                             and _ordinal(text) is not None)
            if is_document: is_nav=True
            is_page=bool(ctx and re.search(r'\bpagina\b',s) and re.search(r'\b(proxima|anterior|mostre|pagina|ir|va|abrir|abra)\b',s))
            relative=bool(re.fullmatch(r'(?:(?:e|agora|o|a|entao|por|favor)\s+)*(?:proximo|proxima|anterior|precedente|seguinte)(?:\s+(?:arquivo|video|musica|audio))?',s))
            is_play=bool(ctx and (self._wants_media(text) or relative) and
                         (re.search(r'\b(proxim\w*|anteri\w*|primeir\w*|segund\w*|terceir\w*|ultim\w*|\d+|aleatori\w*|sortei\w*)\b',s)))
            is_play_request=bool(ctx and self._wants_media(text) and
                                 (_group(text) in ('audio','video') or
                                  ctx.get('last_media_group') in ('audio','video')))
            if not is_nav and not is_page and not is_play and not is_play_request:
                return None
            if not ctx and not is_nav:
                return None
            if is_page:
                group = _group(text,exclude_folder=False) or ctx['last_group']
                value = re.search(r'\bpagina\s+(\d+)\b',s)
                step = -1 if re.search(r'\bpagina\s+anterior|anterior\s+pagina\b',s) else 1
                number = int(value.group(1)) if value else ctx['page'].get(group,1)+step
                return self._page(ctx,group,number)
            if ctx and re.search(r'\b(?:liste|listar|mostre|mostrar|exiba)\b',s) and not re.search(r'\b(?:entre|va|vai|mude|troque)\b',s):
                group=_group(text,exclude_folder=False)
                if group is None:
                    if 'arquivos' in s or 'conteudo' in s:
                        return self._summary(ctx)+'. Diga qual categoria deseja listar ou solicite uma página.'
                    group=ctx['last_group']
                return self._page(ctx,group)
            if ctx and re.search(r'\b(volte|voltar|suba|subir)\s+(?:uma?\s+)?(?:pasta|nivel|diretorio)\b',s):
                parent = Path(ctx['path']).parent
                try:
                    next_ctx = self._context(parent)
                except (PermissionError,OSError,FileNotFoundError):
                    return 'Não tenho autorização para subir além desta pasta; mantive o contexto atual.'
                return self._activate(next_ctx,navigation=navigation)+self._summary(next_ctx)+'.'
            if ctx and re.search(r'\b(volte|voltar)\s+(?:ao|para\s+o)?\s*(?:contexto\s+)?anterior\b',s):
                if not self.state['history']: return 'Não há contexto anterior no histórico.'
                target=self.state['history'][-1]
                return self._restore(target,forward=True,navigation=navigation)
            if ctx and re.search(r'\b(avance|avancar)\s+(?:(?:uma|a)\s+)?(?:pasta|para\s+o\s+(?:proximo\s+)?contexto|contexto)\b',s):
                if not self.state['forward']: return 'Não há contexto seguinte no histórico.'
                target=self.state['forward'][-1]
                return self._restore(target,navigation=navigation)
            if is_document and not re.search(r'\b(vai|va|entre|procure|encontre|busque)\b',s):
                doc=self._document_action(text,skills,navigation)
                if doc is not None: return doc
            if (is_play or is_play_request) and not (re.search(r'\b(pasta|disco|diretorio)\b',s) and
                                re.search(r'\b(vai|va|entre|procure|encontre|busque)\b',s)):
                return self._play(text,skills,navigation)
            # Explicit absolute paths are validated, never inferred from speech.
            path_request=re.search(r'([A-Za-z]:[\\/][^\n]+)$',text.strip())
            if path_request and re.search(r'\b(?:abra|abrir|entre|va|vai|mude|troque|procure|encontre)\b',s):
                wanted=path_request.group(1).strip(' ."')
                try:
                    direct=self._context(wanted)
                except (OSError,PermissionError):
                    return 'Não consegui validar o caminho informado; o contexto anterior permanece ativo.'
                return self._enter(direct,text,navigation=navigation,skills=skills)
            req=parse_folder_request(text)
            drive=req.drive
            # A request specifying only a drive scopes the roots of that disk.
            drive_alone = re.search(r'\b(?:disco|unidade)\s+(?:local\s+)?([a-z])\b',s)
            if not drive and drive_alone: drive=drive_alone.group(1).upper()
            name=req.folder_name
            if not name:
                m = re.search(r'\b(?:entre|entrar|va|vai|mude|troque|retorne|volte)\s+(?:para\s+|na\s+|no\s+|a\s+|ao\s+)?(?:a\s+|o\s+)?(?:pasta\s+)?([\w\- ]{1,65})', s)
                if m:
                    name=re.split(r'\b(?:do|da|no|na|e|para|disco|unidade)\b',m.group(1))[0].strip()
                    if name.startswith('pasta '):name=name[6:]
            if name and name in {'pasta','contexto','disco','arquivos','video','musica'} and ctx:
                # A bare 'abra pasta' references the current context.
                name=None
            if name:
                try:
                    candidates,incomplete=self._candidates(name,drive)
                except OSError:
                    return 'Não consegui completar a busca; mantive o contexto atual.'
                if not candidates:
                    return 'Não encontrei a pasta {} nas áreas autorizadas{}; mantive o contexto anterior.'.format(
                        name, ' da unidade '+drive if drive else '')
                if incomplete and len(candidates)==1:
                    return 'A pesquisa foi interrompida com um único resultado; preciso de uma localização mais específica.'
                return self._choose(candidates,text,navigation=navigation,skills=skills,incomplete=incomplete)
            if ctx and re.search(r'\b(?:atualize|atualizar|recarregue|reindexe)\s+(?:o\s+)?(?:catalogo|conteudo|lista)\b',s):
                try:
                    ctx=self._context(ctx['path'],refresh=True)
                    self._save()
                    self.last_evidence=('verified','Catálogo da pasta atual revalidado no sistema de arquivos.')
                except (OSError,PermissionError):
                    return 'Não consegui atualizar o catálogo. Mantive a versão anterior.'
                return 'Atualizei o catálogo de {}. {}.'.format(ctx['folder'],self._summary(ctx))
            if drive and not name and re.search(r'\b(?:disco|unidade)\b',s):
                roots=[str(p) for p in self._roots() if _drive(p)==drive+':']
                roots.sort(key=lambda v:(len(v),v.casefold()))
                if not roots:
                    return 'Não encontrei uma raiz autorizada no disco {}. Mantive o contexto anterior.'.format(drive)
                return self._choose(roots,text,navigation=navigation,skills=skills)
            if ctx and re.search(r'\b(?:abra|abrir|abre)\s+(?:a\s+)?pasta\b',s):
                return self._enter(ctx,text,navigation=navigation,skills=skills)
            if ctx and (is_play or is_play_request):
                return self._play(text,skills,navigation)
            return None
