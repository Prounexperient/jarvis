"""Seleção de capacidades antes da inferência, preservando espaço contextual.

O LLM planeja chamadas entre as ferramentas relevantes, não entre todas as
39 funções em cada pergunta. Sem ferramentas para conhecimento geral. Os
bloqueios finais continuam em TaskController/ActionPolicy e nas ferramentas.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from intent_resolver import IntentResolver, normalize
from quote_intent import is_general_quotation_request


FILES = ('search_directories','search_files_in_directory','search_files',
         'open_file','open_directory','open_search_result','reveal_search_result',
         'read_document','read_search_result','inspect_document','inspect_search_result',
         'search_directories_by_content','get_system_capabilities',
         'open_application','read_text_file','create_word_document','replace_in_text_file')
DEVELOPMENT = ('developer_workspace_status','developer_select_project',
               'developer_inspect_project','developer_map_codebase','developer_read_code',
               'developer_create_project_structured','developer_add_project_files',
               'developer_create_python','developer_replace_function',
               'developer_replace_file','developer_verify_code',
               'developer_run_python','developer_run_derived_test',
               'developer_prepare_test_environment','developer_create_derived_test',
               'developer_rename_file','developer_delete_file',
               'developer_delete_derived_directory','developer_undo_file_operation')
CAPABILITIES = ('get_system_capabilities',)
CALCULATION = ('calculator',)

_LOCAL_NOUN = re.compile(r'\b(pasta|pastas|diretorio|diretorios|arquivos?|ficheiro|disco|unidade|video|videos|musica|audio|mp3|mp4|pdf|documentos?|documents|downloads|pagina|contexto)\b')
_LOCAL_ACTION = re.compile(r'\b(abra|abrir|abre|encontre|procure|pesquise|localize|busque|reproduza|reproduzir|toque|tocar|liste|listar|mostre|carregue|leia|leitura|edite|editar|salve|crie|criar|execute|exiba|entre|va|vai|volte|suba|avance|mude|troque)\b')
_DEVELOPMENT = re.compile(r'\b(python|script|codigo|codigos|funcao|funcoes|workspace|projeto|programa|teste|testes|refatorar|git|programacao)\b')
_CHANGE = re.compile(r'\b(crie|criar|corrija|corrigir|editar|edite|altere|implemente|implementar|modifique|refatore|refatorar|teste|testar|analise|analisar|revise|executar|execute|gere)\b')
_QUESTION = re.compile(r'\b(quem|quando|onde|porque|por\s+que|qual|quais|como|epoca|periodo|viveu|significa|explique|resuma|sabia|conhece|sabe)\b')
_EXPLICIT_PC = re.compile(r'\b(meu|minha|local|no|do|dentro\s+do|na)\s+(pc|computador|disco|diretorio|arquivo|pasta|projeto|documento)\b')
_CAP = re.compile(r'\b(quais\s+discos|quais\s+unidades|permissoes|capacidades\s+do\s+computador|acessar\s+meu\s+pc)\b')


@dataclass(frozen=True)
class ToolScope:
    category: str
    schemas: tuple

    @property
    def tools_enabled(self):
        return bool(self.schemas)

    def tool_names(self):
        return tuple(s['function']['name'] for s in self.schemas)


class AdaptiveToolset:
    def __init__(self, schemas):
        self.schemas_by_name={s['function']['name']:s for s in schemas}
        self.intent=IntentResolver()

    def route(self, text, *, has_media=False, has_workspace=False, has_workspace_choice=False):
        s=normalize(text)
        frame=self.intent.resolve(text)
        # A selection/page/directory move is a files operation whenever there
        # is a verified navigation workspace or a pending folder choice.
        if has_workspace_choice and re.fullmatch(
                r'(?:sim|nao|sem preferencia|sem preferencias|quero escolher|com preferencia|'
                r'(?:a|o|opcao|pasta|escolho|item|numero)?\s*(?:primeiro|primeira|segundo|segunda|'
                r'terceiro|terceira|quarto|quarta|\d+)|'
                r'(?:pasta\s+)?\w+\s+\d+)', s):
            return 'files'
        if has_workspace and re.search(r'\b(proxima|proximo|anterior|volte|voltar|suba|subir|avance|avancar|pagina)\b', s):
            if not _QUESTION.search(s) and len(s.split())<=9:
                return 'files'
        # Navegação de mídia confirmada tem precedência sobre 'reproduza' usado
        # isoladamente, que em outro contexto poderia significar citação literária.
        if has_media:
            from media_intent import MediaIntentResolver
            media=MediaIntentResolver().interpret(text,has_media_context=True)
            if media['wants_open'] and media['position'] is not None:
                return 'files'
        # Perguntas de cultura, história e citações não consultam o disco,
        # inclusive quando o ASR confundiu o nome de uma figura com arquivo.
        if is_general_quotation_request(text):
            return 'knowledge'
        if _CAP.search(s):
            return 'capabilities'
        local=frame.explicit_local_source or bool(_LOCAL_NOUN.search(s) and _LOCAL_ACTION.search(s))
        if _DEVELOPMENT.search(s) and _CHANGE.search(s):
            return 'development'
        if local:
            return 'files'
        # Um imperativo de operação pode ter como objeto um aplicativo ou
        # recurso não previsto pelos classificadores: ofereça o conjunto de
        # ferramentas locais e deixe o LLM interpretar, sem abrir permissões.
        if _LOCAL_ACTION.search(s) and not _QUESTION.search(s):
            return 'files'
        if has_media and re.search(r'\b(proximo|proxima|anterior|primeiro|segundo|terceiro|reproduza|toque)\b',s):
            return 'files'
        if _QUESTION.search(s) and not _EXPLICIT_PC.search(s):
            return 'knowledge'
        if re.search(r'\b(calcule|quanto\s+[eé]|soma|multiplique)\b',s) and not local:
            return 'calculation'
        return 'conversation'

    def select(self, text, *, has_media=False, has_workspace=False, has_workspace_choice=False):
        category=self.route(text,has_media=has_media,has_workspace=has_workspace,has_workspace_choice=has_workspace_choice)
        names={'files':FILES,'development':DEVELOPMENT,'capabilities':CAPABILITIES,
               'calculation':CALCULATION}.get(category,())
        # Não enviar ferramentas que não estejam realmente registradas.
        return ToolScope(category,tuple(self.schemas_by_name[n] for n in names if n in self.schemas_by_name))
