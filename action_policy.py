"""Política central de autorização de ferramentas por turno.

Faz parte do gateway de execução; não substitui validações de caminho,
confirmações de exclusão, limites de workspace ou segurança das ferramentas.
"""
import ntpath
import re
from intent_resolver import IntentResolver, normalize

MEDIA_EXTENSIONS = frozenset({'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma',
                              '.mp4', '.mkv', '.avi', '.mov', '.webm', '.wmv', '.mpeg', '.mpg', '.m4v'})
WRITE_TOOLS = frozenset({
    'developer_create_python', 'developer_create_project',
    'developer_create_project_structured', 'developer_add_project_files',
    'developer_patch_file', 'developer_replace_function', 'developer_replace_file',
    'developer_rename_file', 'replace_in_text_file', 'create_word_document',
    'developer_prepare_test_environment', 'developer_create_derived_test',
    'developer_delete_file', 'developer_delete_derived_directory',
    'developer_undo_file_operation',
})
DELETE_TOOLS = frozenset({'developer_delete_file', 'developer_delete_derived_directory'})
RUN_TOOLS = frozenset({'developer_run_python', 'developer_run_derived_test'})
_EXPLICIT_DELETE = re.compile(r'\b(?:exclu\w*|apag\w*|delet\w*|remov\w*|destru\w*)\b')
_EXPLICIT_RUN = re.compile(r'\b(?:execut\w*|rod\w*|test\w*|valid\w*|inici\w*)\b')
_EXPLICIT_UNDO = re.compile(r'\b(?:desfac\w*|desfaz\w*|revert\w*|restaur\w*)\b')
LOCAL_TOOLS = frozenset({
    'search_files', 'search_files_in_directory', 'search_directories',
    'search_directories_by_content', 'open_file', 'open_search_result',
    'open_directory', 'read_search_result', 'read_document', 'read_text_file',
    'inspect_document', 'inspect_search_result', 'reveal_search_result',
    'reveal_file', 'reveal_directory', 'open_application',
})
READ_TOOLS = frozenset({'read_document', 'read_search_result', 'read_text_file',
                        'inspect_document', 'inspect_search_result'})
OPEN_TOOLS = frozenset({'open_file', 'open_search_result', 'open_directory', 'open_application'})
OPEN_GENERAL = 'O usuário não pediu abertura. Apenas localize ou informe o caminho.'


class ActionPolicy:
    """Uma política só para atalhos determinísticos e chamadas do LLM."""
    def __init__(self, navigation=None):
        self.navigation = navigation
        self.resolver = IntentResolver()

    def _is_media_target(self, name, args):
        if name == 'open_directory':
            return False
        if not isinstance(args, dict):
            return False
        if name == 'open_file':
            path = str(args.get('path') or '').lower()
            return ntpath.splitext(path)[1] in MEDIA_EXTENSIONS
        if name == 'open_search_result':
            try:
                index = int(args['index'])
            except (KeyError, ValueError, TypeError):
                return False
            if index < 1:
                return False
            # O índice é o índice da última busca (não da sequência de mídia).
            # Não autorizar com base em posição correspondente de outra busca.
            search = getattr(self.navigation, 'state', {}).get('last_search_results') or {}
            results = search.get('results') or []
            if search.get('kind') != 'files':
                return False
            selected = next((r for r in results if r.get('index') == index), None)
            return bool(selected and ntpath.splitext(str(selected.get('path') or ''))[1].lower() in MEDIA_EXTENSIONS)
        return False

    def _grounded_media_followup(self, name, args, request, verified_origin):
        """Authorize only a confirmed positional media action.

        Does not authorize writes, deletions, execution, generic file opening
        or opening anything outside an already confirmed media sequence.
        """
        if name != 'open_file' or not verified_origin or not self._is_media_target(name,args):
            return False
        from media_intent import MediaIntentResolver
        state = getattr(self.navigation,'state',{}) or {}
        sequence = state.get('media_sequence') or {}
        idx = sequence.get('current_index')
        if not isinstance(idx,int) or not 0 <= idx < len(sequence.get('results') or []):
            return False
        if ntpath.normcase(ntpath.normpath(str(sequence.get('directory') or ''))) != ntpath.normcase(ntpath.normpath(str(verified_origin))):
            return False
        target = str(args.get('path') or '')
        if not any(ntpath.normcase(ntpath.normpath(str(x.get('path') or ''))) ==
                   ntpath.normcase(ntpath.normpath(target)) for x in sequence.get('results') or []):
            return False
        frame = MediaIntentResolver().interpret(request,has_media_context=True)
        if not frame.get('wants_open') or frame.get('position') is None:
            return False
        if frame.get('explicit_new_origin'):
            from explicit_folder_controller import fold
            if (fold(ntpath.basename(ntpath.normpath(str(verified_origin)))) !=
                fold(frame.get('folder_name')) or
                (frame.get('drive') and ntpath.splitdrive(str(verified_origin))[0].upper() !=
                 frame['drive'] + ':')):
                return False
        expected = self.navigation.media_navigation(request,verified_directory=verified_origin)
        return bool(expected and not expected.get('error') and
                    ntpath.normcase(ntpath.normpath(str(expected.get('path') or ''))) ==
                    ntpath.normcase(ntpath.normpath(target)))

    def deny_reason(self, name, args, request, *, edit_requested=False,
                    write_authorized=False, confirmed_request=None,
                    verified_origin=None, verified_media_context=False):
        intent = self.resolver.resolve(request)
        media_allowed = bool(verified_media_context and self._grounded_media_followup(
            name,args,request,verified_origin))
        if intent.general_quotation and not media_allowed and (name in LOCAL_TOOLS or
                                         name in WRITE_TOOLS or name in RUN_TOOLS or
                                         name.startswith('developer_')):
            return ('A solicitação é uma citação de conhecimento geral, sem pedido de acesso '
                    'a arquivos locais. Responda sem pesquisar o computador.')
        if name in WRITE_TOOLS:
            if intent.negative_command and not confirmed_request:
                return 'Operação cancelada pelo usuário neste turno.'
            if not write_authorized:
                return 'O usuário não autorizou criação ou edição neste turno.'
        if name in DELETE_TOOLS and not _EXPLICIT_DELETE.search(intent.normalized):
            return 'Exclusão exige pedido explícito para excluir o alvo e confirmação da ferramenta.'
        if name == 'developer_undo_file_operation' and not _EXPLICIT_UNDO.search(intent.normalized):
            return 'Reversão exige solicitação explícita do usuário.'
        if name in RUN_TOOLS and (intent.negative_command or not _EXPLICIT_RUN.search(intent.normalized)):
            return 'A execução de código ou testes não foi solicitada explicitamente.'
        if name in READ_TOOLS and not edit_requested and not intent.requested_read:
            return 'O usuário não solicitou leitura ou inspeção do conteúdo. Apenas localize ou informe o arquivo.'
        if name in OPEN_TOOLS:
            # Não permitir que o LLM contorne a precedência de uma nova origem
            # abrindo um arquivo pertencente à busca/cursor anterior.
            from explicit_folder_controller import parse_folder_request, fold
            request_origin = parse_folder_request(request)
            if request_origin.explicit_new_origin and request_origin.folder_name:
                target = None
                if name in ('open_file', 'open_directory'):
                    target = str(args.get('path') or '') if isinstance(args, dict) else ''
                elif name == 'open_search_result' and isinstance(args, dict):
                    results = (getattr(self.navigation, 'state', {}).get('last_search_results') or {})
                    if results.get('kind') == 'files':
                        for entry in results.get('results') or []:
                            if entry.get('index') == args.get('index'):
                                target = str(entry.get('path') or '')
                                break
                if name == 'open_directory' and target and not ntpath.isabs(target):
                    # A validação de caminho absoluto pertence à ferramenta.
                    # Não impor correspondência nominal sobre um token relativo.
                    target = None
                if target:
                    norm_target = ntpath.normcase(ntpath.normpath(target))
                    if verified_origin:
                        norm_root = ntpath.normcase(ntpath.normpath(str(verified_origin)))
                        try:
                            if ntpath.commonpath([norm_root, norm_target]) != norm_root:
                                return 'Arquivo fora da pasta localizada e validada.'
                        except ValueError:
                            return 'Arquivo fora da unidade da pasta validada.'
                    else:
                        parts = [fold(piece) for piece in ntpath.normpath(target).split('\\') if piece]
                        if request_origin.folder_name not in parts:
                            return 'A abertura pertence a outra pasta, diferente da origem pedida agora.'
                    drive = ntpath.splitdrive(target)[0].upper()
                    if request_origin.drive and drive != request_origin.drive + ':':
                        return 'A abertura pertence a uma unidade diferente da solicitada.'
                elif name == 'open_search_result':
                    return 'Não há resultado verificado para a nova pasta; pesquise a origem primeiro.'
            if intent.negative_command:
                return 'A solicitação não autoriza abertura de arquivos.'
            if media_allowed:
                return None
            if intent.requested_open:
                return None
            if intent.requested_load and self._is_media_target(name, args):
                return None
            return OPEN_GENERAL
        return None
