"""AAA 03 — durable foreground task and grounded cross-turn continuation.

The stored objective is an action the user actually requested. Clarifications
change parameters, not authorization. An unrelated turn does not execute a
pending task. Deletion and code execution are never inferred or handled here.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import ntpath
import re
from pathlib import Path
import sqlite3
from threading import RLock
from uuid import uuid4

from context_resolver import (AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, ContextResolver,
                              drive_of, windows_path_equal)
from media_intent import MediaIntentResolver
from explicit_folder_controller import fold
from task_controller import TaskController


DEFAULT_DB_PATH = Path(__file__).resolve().parent / 'data' / 'jarvis.db'


class TaskContinuityManager:
    def __init__(self, db_path=None, resolver=None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.resolver = resolver or ContextResolver()
        self._lock = RLock()
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS aaa_conversation_state '
                       '(key TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_utc TEXT NOT NULL)')

    @contextmanager
    def _db(self):
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            try:
                conn.execute('PRAGMA busy_timeout=10000')
                with conn:
                    yield conn
            finally:
                conn.close()

    def _get(self, key):
        with self._db() as db:
            row = db.execute('SELECT payload FROM aaa_conversation_state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _put(self, key, value):
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            if value is None:
                db.execute('DELETE FROM aaa_conversation_state WHERE key=?', (key,))
            else:
                db.execute('INSERT OR REPLACE INTO aaa_conversation_state(key,payload,updated_utc) '
                           'VALUES (?,?,?)', (key, json.dumps(value, ensure_ascii=False), timestamp))

    def pending(self):
        return self._get('pending')

    def selected_directory(self):
        return self._get('selected_directory')

    def clear_pending(self):
        self._put('pending', None)

    def instruction(self):
        """For the LLM pathway, include the original goal without invented paths."""
        pending = self.pending()
        if not pending:
            return ''
        candidates = [r['path'] for r in pending.get('candidates', []) if r.get('path')]
        return ('\nAAA / TAREFA PENDENTE VERIFICADA: objetivo=' + str(pending['request'])[:400]
                + '; estado=' + str(pending['status'])
                + '; pasta=' + str(pending.get('folder_name'))
                + '; unidade=' + str(pending.get('drive'))
                + '; candidatos de ferramenta=' + json.dumps(candidates[:8], ensure_ascii=False)
                + '. Um esclarecimento atualiza a tarefa, não inicia outra. '
                'NUNCA declare um caminho que não veio da ferramenta. '
                'Só finalize após cumprir o objetivo e verificar a ação.')

    @staticmethod
    def _new_task(text, intent):
        return {
            'id': uuid4().hex,
            'request': text,
            'action': 'open' if intent['wants_open'] and intent['position'] is not None else 'list',
            'open_directory': bool(intent.get('open_directory')),
            'folder_name': intent['folder_name'],
            'drive': intent['drive'],
            'media_kind': intent['media_kind'],
            'extension': intent['extension'],
            'position': intent['position'],
            'status': 'locating',
            'candidates': [],
            'selected_directory': None,
            'search_incomplete': False,
            'turns': 1,
        }

    def _execute(self, skills, guard, name, args, *, verified_origin=None, verified_media_context=False):
        deny = guard.inspect(name, args, verified_origin=verified_origin,
                             verified_media_context=verified_media_context)
        if deny:
            return {'error': deny}
        try:
            response = skills.execute(name, args)
        except Exception as exc:
            return {'error': type(exc).__name__ + ': ' + str(exc)}
        return response if isinstance(response, dict) else {'error': 'Resposta não estruturada.'}

    def _search_directory(self, task, skills, nav):
        query = task.get('folder_name')
        if not query:
            task['status'] = 'awaiting_location'
            self._put('pending', task)
            return None, 'Preciso do nome da pasta para continuar a tarefa.'
        search_args = {'query': query}
        if task.get('drive'):
            search_args['drive'] = task['drive']
        guard = TaskController(task['request'], navigation=nav)
        result = self._execute(skills, guard, 'search_directories', search_args)
        if result.get('error'):
            task['status'] = 'search_failed'
            self._put('pending', task)
            return None, 'A pesquisa falhou: ' + str(result['error'])
        found = result.get('results')
        if not isinstance(found, list):
            task['status'] = 'search_failed'
            self._put('pending', task)
            return None, 'A pesquisa não devolveu resultados verificáveis.'
        # If a voice-transcribed name differs slightly, one conservative retry
        # increases recall without guessing a candidate from prior searches.
        if not found and not result.get('timed_out'):
            extra = dict(search_args, minimum_score=50)
            alternative = self._execute(skills, guard, 'search_directories', extra)
            if isinstance(alternative.get('results'), list):
                result = alternative
                found = alternative['results']
        task['candidates'] = [dict(x) for x in found if isinstance(x, dict) and x.get('path')]
        task['search_incomplete'] = bool(result.get('truncated') or result.get('timed_out'))
        task['status'] = 'selecting'
        self._put('pending', task)
        return result, None

    def _select(self, task, skills, nav):
        path, reason = self.resolver.choose_folder(
            task.get('candidates') or [], task.get('folder_name'),
            drive=task.get('drive'), roots=self.resolver.configured_roots(skills))
        if path and task.get('search_incomplete') and reason == 'unique_result':
            task['status'] = 'awaiting_location'
            self._put('pending', task)
            return None, 'A busca foi interrompida; preciso de uma localização mais específica.'
        if path:
            task['selected_directory'] = path
            task['status'] = 'folder_selected'
            self._put('pending', task)
            return path, None
        task['status'] = 'awaiting_choice' if reason == 'ambiguous' else 'awaiting_location'
        self._put('pending', task)
        if reason == 'ambiguous':
            choices = [str(x['path']) for x in (task.get('candidates') or [])[:6] if x.get('path')]
            return None, ('Encontrei mais de uma pasta. Escolha pelo caminho completo ou informe '
                          'a localização: ' + '; '.join(choices))
        if task.get('search_incomplete'):
            return None, 'A busca foi incompleta. Informe uma localização mais específica.'
        return None, 'Não encontrei essa pasta na unidade indicada. Informe outro local.'

    def _list(self, task, skills, nav, *, original_request=None):
        directory = task.get('selected_directory')
        if not directory:
            return 'Ainda não existe uma pasta selecionada e validada.'
        args = {'directory': directory}
        if task.get('extension'):
            args['extension'] = task['extension']
        elif task.get('media_kind') == 'video':
            args['extensions'] = ','.join(sorted(VIDEO_EXTENSIONS))
        elif task.get('media_kind') == 'audio':
            args['extensions'] = ','.join(sorted(AUDIO_EXTENSIONS))
        guard = TaskController(original_request or task['request'], navigation=nav)
        found = self._execute(skills, guard, 'search_files_in_directory', args)
        if found.get('error'):
            task['status'] = 'list_failed'
            self._put('pending', task)
            return 'Não consegui listar os arquivos: ' + str(found['error'])
        if not isinstance(found.get('results'), list) or not windows_path_equal(found.get('scope'), directory):
            task['status'] = 'list_failed'
            self._put('pending', task)
            return 'A listagem não confirmou a origem solicitada. Nenhum arquivo foi aberto.'
        items = found['results']
        # Defence in depth: the directory tool may return unexpected entries.
        # A requested audio file must NEVER silently become a video (or vice versa).
        permitted = (VIDEO_EXTENSIONS if task.get('media_kind') == 'video' else
                     AUDIO_EXTENSIONS if task.get('media_kind') == 'audio' else None)
        if permitted is not None and any(
                ntpath.splitext(str(item.get('path','')))[1].lower().lstrip('.') not in permitted
                for item in items):
            task['status'] = 'list_failed'
            self._put('pending', task)
            return 'A listagem retornou um tipo de mídia diferente do solicitado. Nenhum arquivo foi aberto.'
        # Partial traversal cannot prove the first/last item in global order.
        if task.get('action') == 'open' and found.get('timed_out'):
            task['status'] = 'list_incomplete'
            self._put('pending', task)
            return 'A busca de arquivos foi interrompida; não posso determinar a posição com segurança.'
        task['status'] = 'listed'
        self._put('pending', task)
        nav.observe('search_files_in_directory', found, args)
        self._put('selected_directory', directory)
        folder_warning = ''
        if task.get('open_directory'):
            response = self._execute(skills,guard,'open_directory',{'path':directory},verified_origin=directory)
            if response.get('error') or not windows_path_equal(response.get('opened_directory'),directory):
                folder_warning = ' Porém não consegui confirmar a abertura da pasta no Explorador.'
            else:
                nav.observe('open_directory',response,{'path':directory})
        if task.get('action') == 'list':
            self.clear_pending()
            if not items:
                return 'A pasta selecionada está vazia ou não contém arquivos do tipo solicitado.'
            names = [ntpath.basename(str(i['path'])) for i in items[:12]]
            suffix = ' A listagem é parcial.' if found.get('truncated') or found.get('timed_out') else ''
            return 'Encontrei {} arquivo(s) nessa pasta: {}.{}'.format(len(items), ', '.join(names), suffix)
        if not items:
            task['status'] = 'awaiting_location'
            self._put('pending', task)
            return 'Não encontrei arquivos do tipo solicitado nessa pasta. A tarefa continua pendente.'
        pos = task.get('position')
        if pos in ('ultimo', 'ultima'):
            if found.get('truncated') or found.get('timed_out'):
                return 'A listagem está incompleta; não posso identificar o último arquivo.'
            index = len(items)-1
        elif isinstance(pos, int):
            index = pos-1
        else:
            return 'Preciso de uma posição válida para abrir o arquivo solicitado.'
        if not 0 <= index < len(items):
            return 'A posição solicitada não está na listagem da pasta.'
        file = str(items[index].get('path') or '')
        try:
            root_norm = ntpath.normcase(ntpath.normpath(directory))
            file_norm = ntpath.normcase(ntpath.normpath(file))
            if ntpath.commonpath([root_norm, file_norm]) != root_norm:
                return 'A listagem apresentou um arquivo fora da pasta selecionada. Não vou abri-lo.'
        except ValueError:
            return 'A listagem apresentou um arquivo de outra unidade. Não vou abri-lo.'
        if ntpath.splitext(file)[1].lower() in {'.exe','.bat','.cmd','.ps1','.vbs','.js','.msi','.scr','.com','.lnk'}:
            return 'O arquivo selecionado é executável; não vou abri-lo como mídia.'
        # Authorization for opening is inherited strictly from the original
        # request, which contained the opening instruction.
        opened = self._execute(skills, guard, 'open_file', {'path': file}, verified_origin=directory)
        if opened.get('error') or not windows_path_equal(opened.get('opened'), file):
            task['status'] = 'open_failed'
            self._put('pending', task)
            return 'Não foi possível confirmar a abertura: ' + str(opened.get('error') or 'retorno não corresponde ao arquivo')
        nav.observe('open_file', opened, {'path': file})
        self.clear_pending()
        print('[AAA_CONTINUITY] concluída tarefa=' + task['id'][:8] + ' arquivo=' + ntpath.basename(file))
        return ('Abri o arquivo {} da pasta {}.{}'.format(
            index+1, ntpath.basename(ntpath.normpath(directory)),folder_warning))

    @staticmethod
    def _same_folder(path, name, drive=None):
        if not path or not name:
            return False
        return (fold(ntpath.basename(ntpath.normpath(str(path)))) == fold(name)
                and (not drive or drive_of(path) == drive))

    def _cursor_action(self, text, skills, nav, intent, directory):
        """Play from the last *verified* list, without a second global search."""
        seq = (nav.state.get('media_sequence') or {})
        if not (directory and windows_path_equal(seq.get('directory'), directory)):
            return None
        # The navigation memory alone never grants a new origin or write access.
        # Already-selected named folders are not new origins semantically.
        if intent.get('explicit_new_origin') and not self._same_folder(
                directory,intent.get('folder_name'),intent.get('drive')):
            return None
        ref = nav.media_navigation(text, verified_directory=directory)
        if ref is None:
            return None
        if ref.get('error'):
            return ref['error']
        file = str(ref['path'])
        try:
            path_norm = ntpath.normcase(ntpath.normpath(file))
            root_norm = ntpath.normcase(ntpath.normpath(str(directory)))
            if ntpath.commonpath((path_norm,root_norm)) != root_norm:
                return 'A sequência contém um arquivo fora da pasta confirmada. Não vou abri-lo.'
        except ValueError:
            return 'A sequência contém um arquivo de outra unidade. Não vou abri-lo.'
        guard = TaskController(text, navigation=nav)
        opened = self._execute(skills, guard, 'open_file', {'path':file},
                               verified_origin=directory, verified_media_context=True)
        if opened.get('error') or not windows_path_equal(opened.get('opened'),file):
            return 'Não consegui confirmar a reprodução: ' + str(opened.get('error') or 'resultado divergente')
        nav.observe('open_file',opened,{'path':file})
        self._put('selected_directory',directory)
        print('[AAA_MEDIA] pasta={} pos={} tipo={}'.format(directory,ref['position'],ref.get('media_kind')))
        return 'Abri o arquivo {} da pasta {}.'.format(ref['position'],ntpath.basename(ntpath.normpath(directory)))

    def _selected_media_action(self, text, skills, nav, intent, directory):
        """Act on a confirmed folder, preserving position and media filters.

        An explicit media type requires a fresh scoped listing if the saved
        sequence is of another kind. A relative command cannot jump between
        incompatible types without identifying a starting file.
        """
        if not (intent['wants_open'] and intent['position'] is not None):
            return None
        current = (nav.state.get('media_sequence') or {})
        position = intent['position']
        # If no explicit new type, retain the type of the file that was opened.
        kind = intent.get('media_kind')
        if kind is None and windows_path_equal(current.get('directory'), directory):
            active_path = str(nav.state.get('active_file') or '')
            if any(windows_path_equal(row.get('path'),active_path)
                   for row in current.get('results', [])):
                kind_name = nav._kind(active_path)
                if kind_name in ('last_audio','last_video'):
                    kind = kind_name.removeprefix('last_')
        if isinstance(position,str) and position in {'proximo','proxima','seguinte','anterior','precedente'}:
            # For a positional move, the current index must be verified and
            # belong to the specified media type; otherwise stop safely.
            if intent.get('explicit_new_origin'):
                return 'Para navegar nessa pasta, abra primeiro um arquivo dela.'
            return self._cursor_action(text,skills,nav,intent,directory)
        task = self._new_task(text,intent)
        task.update(selected_directory=directory,status='folder_selected',media_kind=kind)
        self._put('pending',task)
        return self._list(task,skills,nav)

    def handle(self, text, skills, nav):
        """Unified state-machine entry for both Agent.ask and Agent.ask_stream.

        The user may change a parameter of an existing task, use a verified
        reference, or start a new explicit task. No LLM text is allowed to
        impersonate a tool observation.
        """
        sequence = nav.state.get('media_sequence') or {}
        context_ready = bool(sequence.get('results') and sequence.get('current_index') is not None)
        intent = self.resolver.parse(text, has_media_context=context_ready)
        pending = self.pending()
        if intent['cancel']:
            if pending:
                self.clear_pending()
                return 'Cancelei a tarefa pendente. Nenhum arquivo foi excluído.'
            return None

        # Pending ambiguity takes precedence over any old cursor. A location
        # clarification only changes parameters of the original request.
        if pending and pending['status'] not in {'complete','cancelled'}:
            explicit = bool(intent['explicit_new_origin'] and intent['folder_name'])
            new_command = bool(explicit and intent['wants_open'] and intent['position'] is not None)
            # The user is issuing a distinct full command, not just specifying
            # a drive/name for a previously pending action.
            if new_command:
                pending = None
            elif intent['drive'] or (intent['folder_name'] and
                    fold(intent['folder_name']) == fold(pending.get('folder_name'))):
                pending['drive'] = intent['drive'] or pending.get('drive')
                pending['turns'] += 1
                pending['selected_directory'] = None
                pending['candidates'] = []
                pending['status'] = 'locating'
                self._put('pending',pending)
            elif pending.get('status') == 'awaiting_choice' and pending.get('candidates'):
                options = [x['path'] for x in pending['candidates'] if x.get('path')]
                chosen = next((p for p in options if fold(p) in fold(text)), None)
                words = re.findall(r'[a-z0-9]+',fold(text))
                ordinal = any((words[i+1] in ('pasta','diretorio') and
                               words[i] in ('primeira','primeiro','segunda','segundo',
                                             'terceira','terceiro','quarta','quarto'))
                              or (words[i] in ('pasta','diretorio') and words[i+1].isdigit())
                              for i in range(len(words)-1))
                if not chosen and ordinal and isinstance(intent['position'],int):
                    idx = intent['position']-1
                    if 0 <= idx < len(options) and not pending.get('search_incomplete'):
                        chosen = options[idx]
                if chosen:
                    pending['selected_directory'] = chosen
                    pending['status'] = 'folder_selected'
                    self._put('pending',pending)
                    return self._list(pending,skills,nav)
                if intent['wants_open'] or intent['reference'] or intent['list_files']:
                    return 'Ainda há mais de uma pasta candidata. Escolha pelo caminho ou número da pasta.'
                return None
            elif intent['list_files'] and intent['reference']:
                verified = pending.get('selected_directory')
                if not verified:
                    return 'Ainda há mais de uma pasta candidata. Informe qual delas devo utilizar.'
                listing = dict(pending,action='list',request=text,media_kind=None,extension=None)
                return self._list(listing,skills,nav,original_request=text)
            elif intent['wants_open'] and intent['position'] is not None:
                return 'A tarefa anterior ainda depende da seleção da pasta. Informe sua localização.'
            else:
                return None

        if pending and pending.get('status') == 'locating':
            found,error = self._search_directory(pending,skills,nav)
            if error:
                return error
            _,error = self._select(pending,skills,nav)
            if error:
                return error
            return self._list(pending,skills,nav)

        selected = self.selected_directory() or self.resolver.grounded_directory(nav)
        explicit_new = bool(intent['explicit_new_origin'] and intent['folder_name'])
        matching_selected = (self._same_folder(selected,intent.get('folder_name'),intent.get('drive'))
                             and 'outra' not in fold(text).split())
        # Repeated reference to the SAME confirmed directory is not a new
        # search, even when the user says "da pasta Vídeos" again.
        if explicit_new and matching_selected and intent['wants_open'] and intent['position'] is not None:
            updated = dict(intent,explicit_new_origin=False)
            return self._selected_media_action(text,skills,nav,updated,selected)
        if explicit_new and (intent['wants_open'] and intent['position'] is not None or intent['list_files']):
            pending = self._new_task(text,intent)
            self._put('pending',pending)
            found,error = self._search_directory(pending,skills,nav)
            if error:
                return error
            _,error = self._select(pending,skills,nav)
            if error:
                return error
            return self._list(pending,skills,nav)

        if intent['list_files'] and intent['reference']:
            if not selected:
                return None
            listing = self._new_task(text,dict(intent,folder_name=ntpath.basename(selected)))
            listing.update(selected_directory=selected,action='list')
            self._put('pending',listing)
            return self._list(listing,skills,nav,original_request=text)

        if selected and intent['wants_open'] and intent['position'] is not None:
            active_directory = nav.state.get('active_directory')
            if active_directory and not windows_path_equal(active_directory,selected):
                # The user opened or selected another directory. The stored
                # media position must not silently jump back to a stale folder.
                return 'A pasta ativa mudou. Informe qual pasta devo utilizar para reproduzir arquivos.'
            # An explicitly changed type must refresh the scoped list. A
            # video-only cursor is not proof of which audio is the first.
            if intent.get('media_kind'):
                seq = nav.state.get('media_sequence') or {}
                at = seq.get('current_index')
                items = seq.get('results') or []
                current_path = (str(items[at].get('path','')) if isinstance(at,int)
                                and 0 <= at < len(items) else '')
                current_kind = nav._kind(current_path)
                expected = 'last_' + intent['media_kind']
                if current_kind != expected:
                    if intent['position'] in ('proximo','proxima','seguinte','anterior','precedente'):
                        return 'Para mudar o tipo de mídia, abra primeiro um arquivo desse tipo na pasta.'
                    return self._selected_media_action(text,skills,nav,intent,selected)
            # Cursor actions (including isolated "o próximo") never depend
            # on the last tool search index, which may now be a directory.
            result = self._cursor_action(text,skills,nav,intent,selected)
            if result is not None:
                return result
            # A new requested media type requires a scoped fresh listing.
            if not isinstance(intent['position'],str) or intent['position'] in ('ultimo','ultima'):
                return self._selected_media_action(text,skills,nav,intent,selected)
        return None
