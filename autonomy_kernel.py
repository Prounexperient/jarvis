"""AAA 05 — núcleo operacional integrado para turnos e ferramentas.

Planejar → Executar → Verificar → Corrigir → Aprender, com restrições explícitas:
- ferramentas nunca ganham permissões extras por planejamento ou memória;
- sucesso instrumental só decorre de ResultVerifier, não de texto do LLM;
- falha não provoca repetição de escrita/execução/exclusão;
- aprendizado é estatístico/simbólico local, NÃO treinamento do LLM;
- todo processo é síncrono, cancelamento e prazo permanecem no runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
from contextlib import contextmanager
import json
import re
import sqlite3

from adaptive_toolset import AdaptiveToolset
from semantic_memory import SemanticMemory, SemanticHint
from result_verifier import ResultVerifier
from recovery_engine import RecoveryEngine
from task_planner import TaskPlanner
from quote_intent import is_general_quotation_request


def utcnow():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AutonomousTurn:
    id: str
    request: str
    route: str
    tools: tuple
    hint: SemanticHint
    stages: tuple
    created: str = field(default_factory=utcnow)
    evidence: list = field(default_factory=list)
    status: str = 'running'
    final: str = ''
    model_rounds: int = 0

    @property
    def tools_enabled(self):
        return bool(self.tools)

    @property
    def tool_names(self):
        return {schema['function']['name'] for schema in self.tools}

    def verified(self, kinds=None):
        return any(e['status']=='verified' and (kinds is None or e['tool'] in kinds)
                   for e in self.evidence)

    def instruction(self):
        stages=' → '.join(self.stages) if self.stages else 'interpretar → responder'
        return ('\nNÚCLEO AUTÔNOMO / OBJETIVO DO TURNO: '+self.request[:500]+'; plano='+stages+
                '; modo='+self.route+'. O LLM propõe próximos passos, ferramentas executam, '
                'ResultVerifier comprova, RecoveryEngine orienta alternativas sem burlar permissões. '
                'Uma chamada com erro não é conclusão. Não declare ações sem confirmação da ferramenta. '
                'Não use ferramentas não oferecidas. Diferencie conclusão operacional de mera resposta do modelo.'+
                self.hint.instruction())


class _TraceSkills:
    """Proxy que registra as ferramentas efetivamente usadas pelo atalho AAA03/04."""
    def __init__(self, original, kernel, turn):
        self._original=original
        self._kernel=kernel
        self._turn=turn
        self.config=getattr(original,'config',{})
        self.schemas=getattr(original,'schemas',[])

    def execute(self, name, args):
        result=self._original.execute(name,args)
        self._kernel.observe(self._turn,name,args,result)
        return result

    def __getattr__(self, name):
        return getattr(self._original,name)


class AutonomyKernel:
    """Uma sessão de decisão compartilhada por ask, ask_stream e os atalhos."""

    def __init__(self, db_path, schemas):
        self.db_path=Path(db_path)
        self.db_path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=RLock()
        self.catalog=AdaptiveToolset(schemas)
        self.semantic=SemanticMemory(db_path)
        self.verifier=ResultVerifier()
        self.recovery=RecoveryEngine()
        self.planner=TaskPlanner()
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS aaa_autonomy_turns '
                       '(id TEXT PRIMARY KEY, request TEXT NOT NULL, route TEXT NOT NULL, '
                       'status TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, '
                       'stages TEXT NOT NULL, evidence TEXT NOT NULL, result TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS aaa_strategy_scores '
                       '(route TEXT NOT NULL, tool TEXT NOT NULL, ok INTEGER NOT NULL DEFAULT 0, '
                       'failed INTEGER NOT NULL DEFAULT 0, partial INTEGER NOT NULL DEFAULT 0, '
                       'PRIMARY KEY(route,tool))')

    @contextmanager
    def _connect(self):
        conn=sqlite3.connect(str(self.db_path),timeout=10)
        conn.execute('PRAGMA busy_timeout=10000')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _save(self, turn):
        with self.lock, self._connect() as db:
            db.execute('INSERT OR REPLACE INTO aaa_autonomy_turns VALUES(?,?,?,?,?,?,?,?,?)',
                       (turn.id,turn.request[:1200],turn.route,turn.status,turn.created,utcnow(),
                        json.dumps(turn.stages,ensure_ascii=False),
                        json.dumps(turn.evidence[-60:],ensure_ascii=False),turn.final[:1200]))

    def begin(self, text, navigation=None, workspace_active=False, workspace_waiting=False):
        state=getattr(navigation,'state',{}) or {}
        seq=state.get('media_sequence') or {}
        scope=self.catalog.select(text,has_media=bool(seq.get('results') and seq.get('current_index') is not None),
                                  has_workspace=workspace_active,has_workspace_choice=workspace_waiting)
        hint=self.semantic.prepare(text,local_request=scope.category not in {'knowledge','conversation'})
        plan=self.planner.create(text)
        stages=tuple(stage.name for stage in plan.stages)
        if scope.category in ('knowledge','conversation'):
            stages=('interpretar_contexto','responder')
        turn=AutonomousTurn(uuid4().hex,str(text),scope.category,scope.schemas,hint,stages)
        self._save(turn)
        print('[AUTONOMIA] inicio='+turn.id[:8]+' modo='+scope.category+' tools='+str(len(turn.tools)))
        return turn

    def observe(self, turn, name, args, result):
        if not turn:
            return None
        verified=self.verifier.verify(name,args,result)
        event={'tool':name,'status':verified.status,'detail':verified.detail[:240], 'utc':utcnow()}
        turn.evidence.append(event)
        with self.lock, self._connect() as db:
            counters={'verified':'ok','failed':'failed','partial':'partial'}
            col=counters.get(verified.status)
            if col:
                db.execute('INSERT OR IGNORE INTO aaa_strategy_scores(route,tool,ok,failed,partial) '
                           'VALUES(?,?,0,0,0)',(turn.route,name))
                db.execute('UPDATE aaa_strategy_scores SET '+col+'='+col+'+1 WHERE route=? AND tool=?',
                           (turn.route,name))
        self._save(turn)
        return verified

    def strategies(self, route):
        """Aprendizado limitado a frequências instrumentais. Nunca altera permissões."""
        with self.lock, self._connect() as db:
            rows=db.execute('SELECT tool,ok,failed,partial FROM aaa_strategy_scores WHERE route=? '
                            'ORDER BY ok DESC LIMIT 12',(route,)).fetchall()
        return [dict(tool=a,ok=b,failed=c,partial=d) for a,b,c,d in rows]

    def learned_guidance(self, route):
        """Reutiliza experiência estatística, sem aprender políticas ou conceder acesso."""
        evidence=self.strategies(route)
        if not evidence:
            return ''
        successful=[x for x in evidence if x['ok'] >= 3 and x['ok'] > x['failed']*2]
        unreliable=[x for x in evidence if x['failed'] >= 3 and x['failed'] > x['ok']]
        notes=[]
        if successful:
            notes.append('Ferramentas com confirmações anteriores: '+
                         ', '.join(x['tool'] for x in successful[:4])+'.')
        if unreliable:
            notes.append('Ferramentas que falharam repetidamente: '+
                         ', '.join(x['tool'] for x in unreliable[:4])+
                         '; avalie alternativas autorizadas antes de repetir.')
        if not notes:
            return ''
        return ('\nEXPERIÊNCIA OPERACIONAL LOCAL (estatística, não evidência do pedido atual): '
                + ' '.join(notes) + ' Siga sempre a confirmação do turno atual.')

    def recovery_hint(self, turn):
        events=[e for e in turn.evidence if e['status'] in ('failed','partial')]
        if not events:
            return ''
        latest=events[-1]
        return ('\nRECUPERAÇÃO: a ferramenta '+latest['tool']+' obteve '+latest['status']+': '+
                latest['detail']+'. Não repita argumentos idênticos sem progresso; '
                'refine o escopo em leitura ou explique o impedimento. '
                'NUNCA repita automaticamente escrita, exclusão ou execução de código.')

    def dispatch(self, agent, turn, *, general_quote=False):
        """Rota única de atalhos: origem, cursor e item recente compartilham evidências."""
        if general_quote or turn.route in ('knowledge','conversation','calculation'):
            return None
        original=agent.skills_manager
        agent.skills_manager=_TraceSkills(original,self,turn)
        try:
            workspace = getattr(agent, 'navigation_workspace', None)
            result = workspace.handle(turn.request, agent.skills_manager, agent.navigation) if workspace else None
            if result is not None:
                # Deterministic actions belong to the conversational history
                # just like the preexisting AAA03 direct actions.
                agent.history.append({'role':'user','content':turn.request})
                agent.history.append({'role':'assistant','content':result})
                # Supersede an older media-only task when a new verified
                # navigation context was explicitly selected.
                if (getattr(workspace,'last_evidence',None) and
                    getattr(agent,'task_continuity',None) and
                    re.search(r'\b(pasta|diretorio|disco|contexto)\b',turn.request.casefold())):
                    agent.task_continuity.clear_pending()
                # Filesystem scans are verified by the workspace's own path and
                # inventory checks. Tool openings are independently observed.
                evidence = getattr(workspace, 'last_evidence', None)
                if evidence and not turn.evidence:
                    status, detail = evidence
                    turn.evidence.append({'tool':'navigation_workspace',
                                          'status':status, 'detail':detail, 'utc':utcnow()})
                    self._save(turn)
            if result is None:
                result=agent._explicit_folder_action(turn.request)
            if result is None:
                result=agent._contextual_media_action(turn.request)
            if result is None:
                from explicit_folder_controller import parse_folder_request
                if not parse_folder_request(turn.request).explicit_new_origin:
                    result=agent._contextual_file_action(turn.request)
        finally:
            agent.skills_manager=original
        if result is not None:
            self.finish(turn,result)
        return result

    @staticmethod
    def _claim_without_evidence(text):
        return bool(re.match(r'^\s*(?:pronto[,!: ]*|feito[,!: ]*)?'
                             r'(?:abri|aberto|aberta|criei|editei|salvei|executei|exclu[ií])\b',
                             str(text or ''),re.I))

    def abort(self, turn, error):
        """Registra falha do motor/integração sem transformar a task em sucesso."""
        if not turn:
            return
        turn.status='failed'
        turn.evidence.append({'tool':'__runtime__','status':'failed',
                              'detail':type(error).__name__+': '+str(error)[:160],
                              'utc':utcnow()})
        turn.final='Falha do runtime: '+type(error).__name__
        self._save(turn)

    def objective_met(self, turn):
        """Predicado verificável que impede sucesso por busca quando foi pedida abertura.

        Cada finalidade exige sua própria evidência, nunca apenas finish_reason.
        """
        if turn.route not in {'files','development','capabilities'}:
            return None
        if turn.route=='capabilities':
            return turn.verified({'get_system_capabilities'})
        text=turn.request.casefold()
        if turn.route=='development':
            if re.search(r'\b(exclua|excluir|apague|apagar)\b',text):
                return turn.verified({'developer_delete_file','developer_delete_derived_directory'})
            if re.search(r'\b(execute|executar|rode|rodar|teste|testar)\b',text):
                return turn.verified({'developer_run_python','developer_run_derived_test'})
            if re.search(r'\b(crie|criar|edite|editar|altere|modifique|corrija|corrigir|implemente|implement)\b',text):
                return turn.verified({'developer_create_python','developer_create_project_structured',
                    'developer_add_project_files','developer_replace_function','developer_replace_file',
                    'developer_rename_file'})
            return turn.verified({'developer_inspect_project','developer_map_codebase','developer_read_code'})
        from intent_resolver import IntentResolver
        from media_intent import MediaIntentResolver
        intent=IntentResolver().resolve(turn.request)
        media=MediaIntentResolver().interpret(turn.request,has_media_context=True)
        if media['wants_open'] and media['position'] is not None:
            if media['open_directory']:
                return turn.verified({'open_file','open_search_result'}) and turn.verified({'open_directory'})
            return turn.verified({'open_file','open_search_result'})
        if intent.requested_open:
            return turn.verified({'open_file','open_search_result','open_directory'})
        if re.search(r'\b(liste|listar|listagem|arquivos\s+na\s+pasta)\b',text):
            return turn.verified({'search_files_in_directory'})
        if intent.requested_read:
            return turn.verified({'read_document','read_search_result','read_text_file'})
        return turn.verified({'navigation_workspace','search_directories','search_files','search_files_in_directory',
                              'search_directories_by_content'})

    def needs_continuation(self, turn, *, completed_cycles=0, answer=""):
        """Replaneja uma vez quando o LLM parou sem fazer o que foi solicitado.

        Após falha ou se o usuário precisa esclarecer algo, não força novas ações.
        """
        if turn.route not in ('files','development') or completed_cycles >= 1:
            return False
        if self.objective_met(turn):
            return False
        if turn.evidence and turn.evidence[-1]['status'] in ('failed','partial'):
            return False
        # Perguntar para escolher entre candidatos é progresso legítimo, não erro.
        if re.search(r'(qual (?:pasta|arquivo|caminho)|informe (?:a|o)|preciso que|escolha|poderia esclarecer)',str(answer).casefold()):
            return False
        return True

    def continuation_instruction(self, turn):
        return ('O modelo interrompeu a geração, mas o OBJETIVO ORIGINAL ainda não '
                'possui evidência de conclusão. Faltam operações verificáveis. '
                'Planeje e execute as ferramentas autorizadas que realmente faltam, '
                'ou explique concretamente o impedimento. Não declare conclusão '
                'sem retorno das ferramentas.')

    def finish(self, turn, answer, *, model_based=False):
        """Fecha objetivo segundo evidências, não segundo finish_reason=stop."""
        answer=str(answer or '').strip()
        operational=turn.route in {'files','development','capabilities'}
        met=self.objective_met(turn)
        if operational and self._claim_without_evidence(answer) and not met:
            answer='Não tenho confirmação da ferramenta para declarar essa operação concluída.'
        if model_based and is_general_quotation_request(turn.request) and not any(
                e['tool'] in {'read_document','read_text_file','read_search_result'} and e['status']=='verified'
                for e in turn.evidence):
            # Não converter uma paráfrase inventada em citação literal.
            if re.search(r'[“\"](.{12,})[”\"]',answer,re.S):
                answer=('Não tenho uma edição textual verificada para reproduzir um trecho literal '
                        'com segurança. Posso explicar ou resumir a passagem, identificando-a como paráfrase.')
        if operational:
            if met:
                turn.status='verified'
            elif any(e['status']=='failed' for e in turn.evidence):
                turn.status='blocked'
            elif turn.evidence:
                turn.status='partial'
            else:
                turn.status='awaiting_evidence'
        else:
            turn.status='answered_unverified' if answer else 'blocked'
        turn.final=answer
        self._save(turn)
        self.semantic.remember_turn(turn.request,answer)
        print('[AUTONOMIA] fim='+turn.id[:8]+' status='+turn.status+' ferramentas='+str(len(turn.evidence)))
        return answer
