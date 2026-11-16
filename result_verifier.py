"""AAA 02 — Verificação baseada na resposta efetiva de cada ferramenta.

Não confunde retorno sem erro com confirmação de operação. Não substitui
testes funcionais de projetos, o Windows nem a política de autorização.
"""
from dataclasses import dataclass
import ntpath


@dataclass(frozen=True)
class Verification:
    status: str  # verified | partial | failed | unverified
    detail: str

    @property
    def confirmed(self):
        return self.status == 'verified'


def _windows_equal(a, b):
    return ntpath.normcase(ntpath.normpath(str(a))) == ntpath.normcase(ntpath.normpath(str(b)))


class ResultVerifier:
    _SEARCH = frozenset({'search_files', 'search_directories',
                         'search_directories_by_content', 'search_files_in_directory'})
    _OPEN_FILE = frozenset({'open_file'})
    _OPEN_DIR = frozenset({'open_directory'})
    _OPEN_SEARCH = frozenset({'open_search_result'})
    _WRITE = frozenset({
        'developer_create_python', 'developer_create_project',
        'developer_create_project_structured', 'developer_add_project_files',
        'developer_patch_file', 'developer_replace_function', 'developer_replace_file',
        'developer_rename_file', 'developer_delete_file',
        'developer_delete_derived_directory', 'developer_create_derived_test',
        'developer_prepare_test_environment',
    })
    _TEST = frozenset({'developer_run_python', 'developer_run_derived_test'})
    _READ = frozenset({'read_text_file', 'read_document', 'read_search_result'})

    def verify(self, name, args, result):
        args = args if isinstance(args, dict) else {}
        if not isinstance(result, dict):
            return Verification('failed', 'Ferramenta devolveu resposta não estruturada.')
        if result.get('error'):
            return Verification('failed', str(result['error'])[:300])
        if result.get('cancelled') or result.get('success') is False:
            return Verification('failed', 'Operação não confirmada ou cancelada.')
        if name in self._SEARCH:
            items = result.get('results')
            if not isinstance(items, list):
                return Verification('failed', 'Busca não retornou uma lista verificável.')
            if name == 'search_files_in_directory':
                if not result.get('scope') or not _windows_equal(
                        result['scope'], args.get('directory') or ''):
                    return Verification('failed', 'Busca devolveu escopo diferente da pasta solicitada.')
            if result.get('truncated') or result.get('timed_out'):
                return Verification('partial', 'Busca parcial: limite/tempo interrompeu a listagem.')
            return Verification('verified', 'Busca concluída no escopo permitido; itens=' + str(len(items)))
        if name in self._OPEN_FILE:
            opened = result.get('opened')
            if not opened or not _windows_equal(opened, args.get('path') or ''):
                return Verification('failed', 'Abertura do arquivo solicitado não foi confirmada.')
            return Verification('verified', 'Ferramenta confirmou a abertura do caminho solicitado.')
        if name in self._OPEN_DIR:
            opened = result.get('opened_directory')
            if not opened or not _windows_equal(opened, args.get('path') or ''):
                return Verification('failed', 'Abertura da pasta solicitada não foi confirmada.')
            return Verification('verified', 'Ferramenta confirmou a abertura da pasta.')
        if name in self._OPEN_SEARCH:
            if result.get('opened') or result.get('opened_directory'):
                return Verification('verified', 'Ferramenta confirmou a abertura do resultado.')
            return Verification('failed', 'Resultado selecionado não foi aberto.')
        if name == 'open_application':
            if result.get('launched'):
                return Verification('verified', 'Ferramenta confirmou o lançamento.')
            return Verification('failed', 'Aplicativo não foi iniciado.')
        if name in self._READ:
            # Um arquivo vazio pode ser lido corretamente. Mas conteúdo vazio de
            # um PDF pode indicar extração parcial ou ilegível.
            if 'content' not in result and 'text' not in result:
                return Verification('failed', 'Leitura não devolveu conteúdo nem campo de texto.')
            if args.get('path') and result.get('path') and not _windows_equal(
                    result['path'], args['path']):
                return Verification('failed', 'Leitura retornou um caminho diferente do solicitado.')
            if result.get('truncated') or (name != 'read_text_file' and
                    not (result.get('content') or result.get('text'))):
                return Verification('partial', 'Documento com conteúdo parcial ou vazio; não afirmar leitura integral.')
            return Verification('verified', 'Leitura textual concluída conforme retorno da ferramenta.')
        if name == 'developer_verify_code':
            if result.get('syntax_valid') is not True:
                return Verification('failed', 'Sintaxe não confirmada.')
            if result.get('structural_verified') is False or result.get('functions_missing'):
                return Verification('failed', 'Verificação estrutural indicou funções ausentes.')
            return Verification('verified', 'Estrutura AST verificada; comportamento funcional não testado.')
        if name == 'developer_read_code':
            if 'content' not in result or not result.get('path'):
                return Verification('failed', 'Código-fonte não foi devolvido pela ferramenta.')
            if args.get('path') and not _windows_equal(result['path'], args['path']):
                return Verification('failed', 'Leitura de código retornou outro caminho.')
            return Verification('verified', 'Ferramenta devolveu conteúdo de código-fonte.')
        if name == 'developer_inspect_project':
            if not isinstance(result.get('files'), list):
                return Verification('failed', 'A inspeção não devolveu lista de arquivos.')
            if result.get('truncated'):
                return Verification('partial', 'Inspeção parcial: limite de arquivos atingido.')
            return Verification('verified', 'Estrutura listada; conteúdo dos arquivos ainda não foi lido.')
        if name in self._TEST:
            if result.get('executed') is not True or 'exit_code' not in result:
                return Verification('failed', 'Execução de teste não comprovada.')
            if result['exit_code'] != 0 or result.get('passed') is False:
                return Verification('failed', 'Execução terminou com falha, código=' + str(result['exit_code']))
            if result.get('truncated'):
                return Verification('partial', 'Execução aprovada, mas a saída foi truncada.')
            return Verification('verified', 'Processo executado e encerrado com código zero.')
        if name in self._WRITE:
            if result.get('success') is True and result.get('verified') is False:
                return Verification('failed', 'Ferramenta não confirmou a verificação da alteração.')
            if result.get('success') is True:
                if name in ('developer_create_project_structured', 'developer_add_project_files'):
                    expected = [item.get('path') for item in args.get('files', [])
                                if isinstance(item, dict)]
                    confirmed = result.get('files')
                    if expected and isinstance(confirmed, list) and not set(expected).issubset(set(confirmed)):
                        return Verification('partial', 'Nem todos os arquivos solicitados foram confirmados.')
                    if expected and not isinstance(confirmed, list):
                        return Verification('partial', 'A criação não devolveu a relação de arquivos confirmados.')
                return Verification('verified', 'Ferramenta confirmou operação de arquivos; testes funcionais ainda não comprovados.')
            return Verification('unverified', 'Sem confirmação explícita de operação; não anunciar conclusão.')
        if name == 'calculator':
            if 'result' in result:
                return Verification('verified', 'Resultado numérico devolvido.')
            return Verification('unverified', 'Cálculo sem campo de resultado esperado.')
        # Ferramentas legadas possuem contratos próprios; não criar erro fictício.
        return Verification('unverified', 'Ferramenta não possui contrato de verificação específico.')
