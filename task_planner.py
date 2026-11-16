"""AAA 02 — Planejamento leve, baseado no pedido vigente e em evidências reais.

O planejador não concede permissões, não inventa caminhos e não executa
ferramentas. Etapas só são marcadas como concluídas por resultados verificados.
"""
from dataclasses import dataclass, field
import re
from intent_resolver import IntentResolver, normalize


_FIND = frozenset({'search_files', 'search_directories', 'search_directories_by_content'})
_LIST = frozenset({'search_files_in_directory', 'developer_inspect_project',
                   'developer_map_codebase'})
_OPEN = frozenset({'open_file', 'open_search_result', 'open_directory'})
_READ = frozenset({'read_text_file', 'read_document', 'read_search_result',
                   'inspect_document', 'inspect_search_result', 'developer_read_code'})
_WRITE = frozenset({'developer_create_python', 'developer_create_project_structured',
                    'developer_add_project_files', 'developer_replace_function',
                    'developer_replace_file', 'developer_patch_file',
                    'developer_create_derived_test', 'developer_rename_file',
                    'developer_delete_file', 'developer_delete_derived_directory'})
_TEST = frozenset({'developer_verify_code', 'developer_run_python',
                   'developer_run_derived_test'})


@dataclass
class PlannedStage:
    name: str
    status: str = 'pending'
    evidence: list = field(default_factory=list)


@dataclass
class TaskPlan:
    request: str
    category: str
    stages: list
    tool_events: list = field(default_factory=list)
    max_tool_calls: int = 50

    def needs_tool_guidance(self):
        return self.category != 'conversation'

    def instruction(self):
        if not self.needs_tool_guidance():
            return ''
        stages = ' -> '.join(stage.name for stage in self.stages)
        return (
            '\nAAA / PLANO DO TURNO (objetivos, não evidência de conclusão): '
            + stages
            + '. Execute apenas operações autorizadas pelo pedido. '
            'Use resultados de ferramentas para avançar de etapa; '
            'não afirme abertura, leitura, edição ou teste sem confirmação verificável. '
            'Se a busca falhar, não reutilize uma origem antiga ou invente um caminho. '
            'Se uma etapa não puder ser concluída, informe precisamente qual falhou.'
        )

    @staticmethod
    def _stage_for_tool(tool):
        if tool in _FIND:
            return 'localizar'
        if tool in _LIST:
            return 'listar'
        if tool in _OPEN:
            return 'abrir'
        if tool in _READ:
            return 'inspecionar'
        if tool in _WRITE:
            return 'modificar'
        if tool in _TEST:
            return 'validar'
        return 'executar'

    def record(self, tool, args, verification, *, attempts=1):
        stage_name = self._stage_for_tool(tool)
        event = {
            'tool': tool,
            'status': verification.status,
            'detail': verification.detail,
            'attempts': attempts,
        }
        self.tool_events.append(event)
        stage = next((s for s in self.stages if s.name == stage_name), None)
        if stage:
            stage.evidence.append(event)
            if verification.status == 'verified':
                stage.status = 'complete'
            elif verification.status in ('failed', 'partial') and stage.status != 'complete':
                stage.status = 'blocked' if verification.status == 'failed' else 'partial'
        return event

    def guard_final_claim(self, answer):
        """Evita uma afirmação direta de execução sem evidência de ferramenta.

        Apenas afirmações inequívocas na abertura da resposta; não reescreve
        explicações, hipóteses nem falas negativas.
        """
        if not self.needs_tool_guidance() or not isinstance(answer, str):
            return answer
        opening = normalize(answer).lstrip()
        opening = re.sub(r'^(?:pronto|feito|concluido)[!.,:\s]+', '', opening)
        if re.match(r'^(?:abri|aberto|aberta|arquivo aberto|pasta aberta)\b', opening):
            confirmed = any(e['tool'] in _OPEN and e['status'] == 'verified'
                            for e in self.tool_events)
            if 'abrir' in [s.name for s in self.stages] and not confirmed:
                return ('Não posso confirmar a abertura solicitada: '
                        'nenhuma ferramenta confirmou essa operação.')
        if re.match(r'^(?:criei|editei|modifiquei|corrigi|salvei|implementei)\b', opening):
            confirmed = any(e['tool'] in _WRITE and e['status'] == 'verified'
                            for e in self.tool_events)
            if 'modificar' in [s.name for s in self.stages] and not confirmed:
                return ('Não posso confirmar a alteração solicitada: '
                        'nenhuma ferramenta confirmou a gravação.')
        return answer

    def summary(self):
        return {
            'category': self.category,
            'stages': [{'name': s.name, 'status': s.status} for s in self.stages],
            'verified_calls': sum(e['status'] == 'verified' for e in self.tool_events),
            'failed_calls': sum(e['status'] == 'failed' for e in self.tool_events),
            'partial_calls': sum(e['status'] == 'partial' for e in self.tool_events),
        }


class TaskPlanner:
    """Gera estágios conservadores; o LLM segue selecionando ferramentas."""

    def create(self, request):
        intent = IntentResolver().resolve(request)
        n = normalize(request)
        # Segurança: uma citação geral, conversa ou pergunta não pede acesso local.
        if intent.general_quotation:
            category, stages = 'conversation', []
        elif re.search(r'\b(projeto|codigo|script|funcao|python|arquivos?\s+python)\b', n) and (
                intent.requested_write or intent.requested_read):
            category = 'development'
            stages = ['localizar', 'inspecionar']
            if intent.requested_write:
                stages.append('modificar')
            if re.search(r'\b(test\w*|execut\w*|valid\w*|verifi\w*)\b', n):
                stages.append('validar')
        elif intent.explicit_local_source or (
                re.search(r'\b(pasta|diretorio|arquivo|disco)\b', n)
                and (intent.requested_open or intent.requested_load or intent.requested_read)):
            category = 'files'
            stages = ['localizar', 'listar']
            if intent.requested_open or intent.requested_load:
                stages.append('abrir')
            if intent.requested_read:
                stages.append('inspecionar')
        else:
            category, stages = 'conversation', []
        return TaskPlan(
            request=request,
            category=category,
            stages=[PlannedStage(s) for s in stages],
        )
