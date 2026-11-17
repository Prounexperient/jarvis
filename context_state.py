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
        if ext in {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma'}: return 'last_audio'
        if ext in {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.wmv', '.mpeg', '.mpg', '.m4v'}: return 'last_video'
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
                previous = self.state.get('media_sequence') or {}
                previous_index = previous.get('current_index')
                # Reading all files in the same folder must not destroy a
                # verified cursor established by playing a video or an audio.
                preserve = (previous_index is not None and
                            ntpath.normcase(ntpath.normpath(str(previous.get('directory')))) ==
                            ntpath.normcase(ntpath.normpath(str(result['scope']))) and
                            not (args.get('extension') or args.get('extensions') or args.get('query')))
                if not preserve:
                    self._set('media_sequence', {
                        'directory': result['scope'],
                        'results': [r for r in results if self._kind(r.get('path', ''))
                                    in {'last_audio', 'last_video'}],
                        'truncated': bool(result.get('truncated') or result.get('timed_out')),
                        'current_index': None,
                    })
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

    def media_navigation(self, text, *, verified_directory=None):
        """Resolve mídia com o MESMO contrato de intenção usado pelo AAA.

        Usa apenas resultados de listagem verificados; não inventa caminhos,
        não seleciona um vídeo quando o pedido exige áudio e não avança cursor
        em respostas negativas. Busca de nova pasta é responsabilidade do
        TaskContinuityManager.
        """
        from media_intent import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, MediaIntentResolver
        seq = self.state.get('media_sequence') or {}
        items = seq.get('results') or []
        frame = MediaIntentResolver().interpret(text, has_media_context=bool(items))
        if not frame['wants_open'] or frame['position'] is None:
            return None
        if not items:
            return None
        directory = seq.get('directory') or ''
        if frame['explicit_new_origin']:
            # The only acceptable named-origin reference is the SAME tool-
            # confirmed directory, explicitly vouched for by the caller.
            from explicit_folder_controller import fold
            if (not verified_directory or
                ntpath.normcase(ntpath.normpath(str(verified_directory))) !=
                ntpath.normcase(ntpath.normpath(str(directory))) or
                fold(ntpath.basename(ntpath.normpath(str(directory)))) !=
                fold(frame.get('folder_name')) or
                (frame.get('drive') and ntpath.splitdrive(str(directory))[0].upper() !=
                 str(frame['drive']).upper() + ':')):
                return None
        active_directory = self.state.get('active_directory') or ''
        # Another directory has taken focus. Never reproduce a stale sequence.
        if active_directory and ntpath.normcase(ntpath.normpath(directory)) != ntpath.normcase(ntpath.normpath(active_directory)):
            return None
        selected_kind = frame['media_kind']
        if selected_kind is None:
            active = str(self.state.get('active_file') or '')
            if any(ntpath.normcase(ntpath.normpath(active)) ==
                   ntpath.normcase(ntpath.normpath(str(x.get('path', '')))) for x in items):
                kind = self._kind(active)
                if kind in ('last_video', 'last_audio'):
                    selected_kind = kind.removeprefix('last_')
        suffixes = (VIDEO_EXTENSIONS if selected_kind == 'video' else
                    AUDIO_EXTENSIONS if selected_kind == 'audio' else None)
        eligible = [x for x in items if suffixes is None or
                    ntpath.splitext(str(x.get('path', '')))[1].lower().lstrip('.') in suffixes]
        if not eligible:
            return {'error': 'Não há arquivos do tipo solicitado na lista confirmada.'}
        pos = frame['position']
        if pos in ('proximo','proxima','seguinte','anterior','precedente'):
            index = seq.get('current_index')
            if index is None or index >= len(items):
                return {'error': 'Não há posição de mídia ativa. Abra primeiro um arquivo da pasta.'}
            current_path = str(items[index].get('path', ''))
            eligible_index = next((i for i,x in enumerate(eligible) if
                 ntpath.normcase(ntpath.normpath(str(x.get('path','')))) ==
                 ntpath.normcase(ntpath.normpath(current_path))), None)
            if eligible_index is None:
                return {'error': 'O arquivo atual não pertence ao tipo de mídia solicitado.'}
            target = eligible_index + (-1 if pos in ('anterior','precedente') else 1)
        elif pos in ('ultimo','ultima'):
            if seq.get('truncated'):
                return {'error': 'A lista foi truncada. Não é possível identificar o último arquivo.'}
            target = len(eligible)-1
        elif isinstance(pos, int):
            target = pos-1
        else:
            return None
        if not 0 <= target < len(eligible):
            return {'error': 'Não há arquivo nessa posição na lista conhecida. Atualize a listagem da pasta.'}
        # In truncated sequences a next item near the limit is not global proof
        # of any eventual final position; avoid claiming full traversal.
        if seq.get('truncated') and pos in ('ultimo','ultima'):
            return {'error': 'A lista foi truncada. Não é possível identificar o último arquivo.'}
        return {'path': eligible[target]['path'], 'position': target+1,
                'total_listed': len(eligible), 'media_kind': selected_kind,
                'directory': directory}

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
