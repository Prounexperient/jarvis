"""Memória operacional persistente: referências de arquivos, pastas e páginas.

A memória é evidência de ferramentas bem-sucedidas, nunca suposição do LLM.
"""
import json
import ntpath
import re
import unicodedata
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / 'data' / 'jarvis.db'


class NavigationContext:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS navigation_memory (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.state = self._load()
        self.active_directory = self.state.get('active_directory')

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _load(self):
        with self._db() as db:
            return {key: json.loads(value) for key, value in db.execute('SELECT key, value FROM navigation_memory')}

    def _set(self, key, value):
        self.state[key] = value
        with self._db() as db:
            db.execute('INSERT OR REPLACE INTO navigation_memory(key,value) VALUES (?,?)',
                       (key, json.dumps(value, ensure_ascii=False)))
        if key == 'active_directory':
            self.active_directory = value

    @staticmethod
    def _kind(path):
        ext = Path(path).suffix.lower()
        if ext == '.pdf': return 'last_pdf'
        if ext in {'.mp3', '.wav', '.flac', '.ogg', '.m4a'}: return 'last_audio'
        if ext in {'.mp4', '.mkv', '.avi', '.mov', '.webm'}: return 'last_video'
        if ext in {'.py', '.js', '.ts', '.java', '.sql'}: return 'last_code_file'
        return None

    def _focus_file(self, path):
        path = str(path)
        self._set('active_file', path)
        kind = self._kind(path)
        if kind:
            self._set(kind, path)

    def observe(self, name, result, args=None):
        if not isinstance(result, dict) or result.get('error') or result.get('cancelled'):
            return
        args = args if isinstance(args, dict) else {}
        results = result.get('results')
        if name in {'search_directories', 'search_directories_by_content'} and isinstance(results, list):
            self._set('last_dir_search', {'query': args.get('query'), 'results': results})
            self._set('last_search_results', {'kind': 'directories', 'results': results})
            if len(results) == 1 and results[0].get('path'):
                self._set('active_directory', results[0]['path'])
        elif name in {'search_files', 'search_files_in_directory'} and isinstance(results, list):
            self._set('last_search_results', {'kind': 'files', 'results': results, 'scope': result.get('scope'), 'truncated': bool(result.get('truncated') or result.get('timed_out'))})
            if name == 'search_files_in_directory' and result.get('scope'):
                self._set('media_sequence', {'directory': result['scope'], 'results': [r for r in results if self._kind(r.get('path', '')) in {'last_audio', 'last_video'}], 'truncated': bool(result.get('truncated') or result.get('timed_out')), 'current_index': None})
            # Uma nova busca de arquivos com vários resultados não deve trocar o arquivo em foco.
            if len(results) == 1 and results[0].get('path'):
                self._focus_file(results[0]['path'])
        if result.get('scope'):
            self._set('active_directory', result['scope'])
        if result.get('opened_directory'):
            self._set('active_directory', result['opened_directory'])
        if result.get('opened'):
            self._track_media_position(result['opened'])
            self._focus_file(result['opened'])
            self._set('active_directory', ntpath.dirname(str(result['opened'])))
        if result.get('revealed'):
            path = result['revealed']
            if Path(path).suffix:
                self._focus_file(path)
            else:
                self._set('active_directory', path)
        if name in {'read_document', 'read_search_result', 'inspect_document', 'inspect_search_result', 'read_text_file'}:
            path = result.get('path') or args.get('path')
            if path:
                self._focus_file(path)
            if name.startswith('inspect_') and args.get('page') is not None and not result.get('error'):
                self._set('last_document_page', int(args['page']))
        if name == 'developer_create_project_structured' and result.get('success') and result.get('directory'):
            self._set('active_project', result['directory'])

    def _track_media_position(self, path):
        seq = self.state.get('media_sequence') or {}
        for i, item in enumerate(seq.get('results') or []):
            if ntpath.normcase(ntpath.normpath(str(item.get('path', '')))) == ntpath.normcase(ntpath.normpath(str(path))):
                seq = dict(seq, current_index=i)
                self._set('media_sequence', seq)
                return

    def media_navigation(self, text):
        """Resolve navegação de mídia, absoluta ou relativa, sem inferência do LLM.

        Somente devolve caminhos já presentes na listagem confirmada.
        """
        # Nova origem explícita sempre prevalece sobre a sequência anterior.
        # Esta regra também cobre comandos ainda não resolvidos pelo controlador.
        from explicit_folder_controller import parse_folder_request
        if parse_folder_request(text).explicit_new_origin:
            return None
        norm = unicodedata.normalize('NFKD', str(text).casefold())
        norm = ''.join(ch for ch in norm if not unicodedata.combining(ch))
        norm = re.sub(r'[^\w\s]', ' ', norm)
        if re.search(r'\b(nao|nunca|jamais|sem|se|quando)\b', norm):
            return None
        if not re.search(r'\b(reproduza|reproduzir|reproduz|toque|tocar|abra|abrir|abre|carregue|carregar|carrega)\b', norm):
            return None
        if re.search(r'\b(pagina|capitulo|projeto|codigo|texto|documento|modelo)\b', norm):
            return None
        seq = self.state.get('media_sequence') or {}
        items = seq.get('results') or []
        if not items:
            return None
        # Uma pasta explicitamente diferente não deve ser atendida usando a lista anterior.
        directory = seq.get('directory') or ''
        folder_match = re.search(r'\b(?:da|na|dessa|desta) pasta\s+([\w -]+)', norm)
        if folder_match:
            named = folder_match.group(1).strip()
            basename = ntpath.basename(ntpath.normpath(directory)).casefold()
            basename = ''.join(c for c in unicodedata.normalize('NFKD', basename) if not unicodedata.combining(c))
            if named != basename:
                return None
        direction = re.search(r'\b(proximo|proxima|seguinte|anterior|precedente)\b', norm)
        ordinals = {'primeiro': 0, 'primeira': 0, 'segundo': 1, 'segunda': 1,
                    'terceiro': 2, 'terceira': 2, 'quarto': 3, 'quarta': 3,
                    'quinto': 4, 'quinta': 4, 'sexto': 5, 'sexta': 5,
                    'setimo': 6, 'setima': 6, 'oitavo': 7, 'oitava': 7,
                    'nono': 8, 'nona': 8, 'decimo': 9, 'decima': 9}
        absolute = re.search(r'\b(' + '|'.join(ordinals) + r'|ultimo|ultima)\b', norm)
        numbered = re.search(r'\b(?:arquivo|musica|audio|faixa|video|midia)\s+(\d+)\b', norm)
        if not direction and not absolute and not numbered:
            return None
        if not re.search(r'\b(arquivo|musica|audio|faixa|video|midia|proximo|proxima|seguinte|anterior|precedente)\b', norm):
            return None
        if direction and (absolute or numbered):
            return None
        if direction:
            index = seq.get('current_index')
            if index is None:
                return {'error': 'Não há posição de mídia ativa. Abra primeiro um arquivo da pasta.'}
            target = index + (-1 if direction.group() in ('anterior', 'precedente') else 1)
        elif absolute:
            if absolute.group() in ('ultimo', 'ultima'):
                if seq.get('truncated'):
                    return {'error': 'A lista foi truncada. Não é possível identificar o último arquivo.'}
                target = len(items) - 1
            else:
                target = ordinals[absolute.group()]
        else:
            target = int(numbered.group(1)) - 1
        if target < 0 or target >= len(items):
            return {'error': 'Não há arquivo nessa posição na lista conhecida. Atualize a listagem da pasta.'}
        if seq.get('truncated') and direction and target == len(items) - 1 and target > seq.get('current_index', -1):
            return {'error': 'A lista de arquivos foi truncada. Atualize a listagem antes de continuar.'}
        return {'path': items[target]['path'], 'position': target + 1, 'total_listed': len(items)}

    def resolve(self, text):
        """Resolve referências anafóricas sem inventar caminhos nem executar ações."""
        import re
        normalized = text.casefold()
        if re.search(r'\b(pr[oó]xima p[aá]gina|p[aá]gina seguinte)\b', normalized):
            path = self.state.get('last_pdf') or self.state.get('active_file')
            if path and Path(path).suffix.lower() == '.pdf':
                return {'path': path, 'page': int(self.state.get('last_document_page') or 1) + 1}
        if re.search(r'\b(pdf|documento)\b', normalized):
            path = self.state.get('last_pdf')
            if path:
                return {'path': path, 'page': 1 if 'primeira p' in normalized else None}
        if re.search(r'\b(m[uú]sica|[aá]udio|mp3|faixa)\b', normalized):
            path = self.state.get('last_audio')
            if path: return {'path': path}
        if re.search(r'\b(v[ií]deo|filme)\b', normalized):
            path = self.state.get('last_video')
            if path: return {'path': path}
        if re.search(r'\b(pasta|diret[oó]rio)\b', normalized):
            path = self.state.get('active_directory')
            if path: return {'path': path}
        if re.search(r'\b(arquivo|ele|dele|esse|este|desse|deste)\b', normalized):
            path = self.state.get('active_file')
            if path: return {'path': path}
        return None

    def instruction(self, text=''):
        from explicit_folder_controller import parse_folder_request
        origin = parse_folder_request(text) if text else None
        if origin and origin.explicit_new_origin:
            # Não apresentar o caminho antigo como referência para a nova pergunta.
            return ('\nNOVA ORIGEM EXPLICITAMENTE SOLICITADA: '
                    + (origin.folder_name or 'nome ainda não identificado')
                    + (', unidade ' + origin.drive if origin.drive else '')
                    + '. Localize e valide esta origem antes de abrir arquivos; '
                    'NÃO utilize active_directory, last_audio nem media_sequence '
                    'de buscas anteriores para atender este pedido.')
        reference = self.resolve(text) if text else None
        if not reference and not self.state:
            return ''
        lines = ['\nMEMÓRIA OPERACIONAL CONFIRMADA (ferramentas; não inventar resultados):']
        for key in ('active_directory', 'active_file', 'last_pdf', 'last_audio', 'last_video',
                    'active_project', 'last_code_file', 'last_document_page'):
            if self.state.get(key) is not None:
                lines.append(f'{key}: {self.state[key]}')
        seq = self.state.get('media_sequence') or {}
        if seq.get('current_index') is not None:
            lines.append('sequência de mídia ativa: pasta=' + str(seq.get('directory')) + '; posição=' + str(seq['current_index'] + 1) + '; itens=' + str(len(seq.get('results') or [])) + '; ordenação da última busca. Próximo/anterior refere-se a esta lista.')
        search = self.state.get('last_search_results') or {}
        if search.get('results'):
            lines.append('última busca: ' + search.get('kind', '?') + '; resultados: ' +
                         json.dumps([{'index': x.get('index'), 'path': x.get('path')}
                                     for x in search['results'][:12]], ensure_ascii=False))
        if reference:
            lines.append('REFERÊNCIA RESOLVIDA PARA A MENSAGEM ATUAL: ' + json.dumps(reference, ensure_ascii=False) +
                         '. Use esse caminho em ferramenta apropriada, sem nova busca. Não afirme leitura ou execução sem retorno real.')
        lines.append('Para "próxima página", use inspect_document com a página resolvida; '
                     'para "resuma primeira página", leia a página 1 do PDF. '
                     'Não peça o nome do arquivo quando a referência estiver resolvida. '
                     'Não confunda índices de pastas com índices de arquivos. '
                     'Se o caminho não existir mais, informe o erro e peça novo caminho.')
        return '\n'.join(lines)
