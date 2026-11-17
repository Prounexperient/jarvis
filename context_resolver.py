"""AAA 03: reference resolution against tool-observed entities, never guessed paths.

The resolver does not execute actions and does not infer a filesystem path from
natural-language fluency. Any returned directory comes from a tool result or
an active directory that NavigationContext registered from a tool result.
"""
import ntpath
import os
from pathlib import Path

from explicit_folder_controller import fold, parse_folder_request
from media_intent import MediaIntentResolver


VIDEO_EXTENSIONS = frozenset({'mp4', 'mkv', 'avi', 'mov', 'webm', 'wmv', 'mpeg', 'mpg', 'm4v'})
AUDIO_EXTENSIONS = frozenset({'mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac', 'wma'})
_REFERENTS = frozenset({'dela', 'dele', 'nela', 'nele', 'nessa', 'nessas', 'nesta',
                        'nestas', 'dessa', 'desta', 'daquela', 'naquela', 'mesma',
                        'anterior', 'ali', 'lá', 'la'})
_LIST_WORDS = frozenset({'liste', 'listar', 'lista', 'listagem', 'mostre', 'mostrar',
                         'exiba', 'exibir', 'relacione'})
_CANCEL = frozenset({'cancelar', 'cancele', 'desista', 'abandone'})


def windows_path_equal(a, b):
    if not a or not b:
        return False
    return ntpath.normcase(ntpath.normpath(str(a))) == ntpath.normcase(ntpath.normpath(str(b)))


def drive_of(path):
    return ntpath.splitdrive(str(path))[0].upper().rstrip(':')


def tokens(text):
    return set(fold(text).replace('-', ' ').replace('.', ' ').split())


class ContextResolver:
    def parse(self, text, *, has_media_context=False):
        request = MediaIntentResolver().interpret(text, has_media_context=has_media_context)
        words = tokens(text)
        normalized = fold(text).strip(' .!?')
        return {
            'folder_name': request['folder_name'],
            'drive': request['drive'],
            'position': request['position'],
            'extension': request['extension'],
            'wants_open': request['wants_open'],
            'open_directory': request['open_directory'],
            'explicit_new_origin': request['explicit_new_origin'],
            'list_files': bool(words & _LIST_WORDS and words & {'arquivo','arquivos','conteudo','pasta','diretorio'}),
            'reference': bool(words & _REFERENTS),
            'cancel': normalized in _CANCEL or normalized in {'cancele a tarefa', 'cancele essa tarefa'},
            'media_kind': request['media_kind'],
        }

    def grounded_directory(self, navigation, *, pending=None):
        if pending and pending.get('status') in {'awaiting_choice', 'awaiting_location'}:
            # Do not accidentally use a previous unrelated active folder.
            return None
        if pending and pending.get('selected_directory'):
            return pending['selected_directory']
        state = getattr(navigation, 'state', {}) or {}
        directory = state.get('active_directory')
        if not directory:
            return None
        search = state.get('last_search_results') or {}
        if search.get('kind') == 'directories' and len(search.get('results') or []) > 1:
            # A later ambiguous search supersedes the old active reference.
            return None
        return str(directory)

    def choose_folder(self, candidates, folder_name, *, drive=None, roots=()):
        """Return (path, reason) using only candidates from a completed tool call.

        Exact configured root is preferred over incidental subfolders with
        identical names. Otherwise multiple plausible candidates are ambiguous.
        """
        found = [str(x['path']) for x in candidates if isinstance(x, dict) and x.get('path')]
        if drive:
            found = [p for p in found if drive_of(p) == drive]
        if folder_name:
            exact = [p for p in found if fold(ntpath.basename(ntpath.normpath(p))) == fold(folder_name)]
            if exact:
                found = exact
        unique = {}
        for path in found:
            unique.setdefault(ntpath.normcase(ntpath.normpath(path)), path)
        found = list(unique.values())
        if not found:
            return None, 'missing'
        roots = [ntpath.normcase(ntpath.normpath(str(r))) for r in roots]
        standard = [p for p in found if ntpath.normcase(ntpath.normpath(p)) in roots]
        if len(standard) == 1:
            return standard[0], 'configured_root'
        if len(found) == 1:
            return found[0], 'unique_result'
        return None, 'ambiguous'

    def configured_roots(self, skills_manager):
        config = getattr(skills_manager, 'config', {}) or {}
        allowed = (config.get('paths') or {}).get('allowed_roots') or []
        roots = [str(Path(str(r)).expanduser()) for r in allowed]
        if os.name == 'nt':
            for label in ('Music', 'Videos', 'Documents', 'Downloads', 'Pictures'):
                folder = Path.home() / label
                if folder.is_dir():
                    roots.append(str(folder))
        return roots
