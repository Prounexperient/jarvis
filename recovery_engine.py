"""AAA 02 — Recuperação conservadora para resultados de ferramentas.

Nunca repete automaticamente edição, criação, exclusão, execução de código,
abertura de arquivos ou chamadas não idempotentes.
"""
from dataclasses import dataclass
import re


READ_ONLY_RETRY = frozenset({
    'search_files', 'search_directories', 'search_files_in_directory',
    'search_directories_by_content', 'read_text_file', 'read_document',
    'read_search_result', 'developer_read_code', 'developer_inspect_project',
    'developer_map_codebase', 'get_system_capabilities',
})
_TRANSIENT = re.compile(
    r'\b(?:Connection(?:Reset|Aborted|Refused)?Error|TimeoutError|'
    r'BrokenPipeError|temporar(?:y|ily) unavailable)\b', re.I
)


@dataclass(frozen=True)
class RecoveryDecision:
    retry: bool
    advice: str


class RecoveryEngine:
    def decide(self, name, args, result, verification, attempts):
        error = str(result.get('error', '')) if isinstance(result, dict) else ''
        if verification.status == 'verified':
            return RecoveryDecision(False, '')
        if verification.status == 'partial':
            return RecoveryDecision(
                False,
                'Resultado parcial: informe o limite; para completar, refine a busca '
                'ou consulte o restante, sem inventar itens.',
            )
        if verification.status == 'unverified':
            return RecoveryDecision(
                False, 'Não há confirmação verificável da ação. Não declare sucesso.',
            )
        if ('PermissionError' in error or 'fora das pastas autorizadas' in error or
                'não autorizad' in error.lower() or 'nao autorizad' in error.lower()):
            return RecoveryDecision(
                False, 'Bloqueio por permissão/política. Não repita nem contorne a restrição.',
            )
        if 'FileNotFoundError' in error or 'não existe' in error.lower():
            return RecoveryDecision(
                False, 'O caminho não existe. Localize-o novamente dentro dos limites autorizados.',
            )
        if name in READ_ONLY_RETRY and attempts == 1 and _TRANSIENT.search(error):
            return RecoveryDecision(True, 'Falha temporária em ferramenta somente de leitura; uma repetição controlada é permitida.')
        return RecoveryDecision(
            False,
            'A chamada não foi comprovada. Use outra estratégia autorizada '
            'ou informe a falha; não repita os mesmos argumentos sem progresso.',
        )
