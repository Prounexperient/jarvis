"""AAA 02 — Executor verificado de ferramentas autorizadas.

A política existente (TaskController/ActionPolicy e ferramentas) continua
responsável pelas permissões. Esta camada só executa chamadas que passaram
pela autorização do Agent, verifica os resultados e limita recuperações.
"""
from recovery_engine import RecoveryEngine
from result_verifier import ResultVerifier


class TaskExecutor:
    def __init__(self, skills_manager, plan, *, verifier=None, recovery=None,
                 experience_store=None, session_id=None):
        self.skills_manager = skills_manager
        self.plan = plan
        self.verifier = verifier or ResultVerifier()
        self.recovery = recovery or RecoveryEngine()
        self.operations = 0
        self.experience_store = experience_store
        self.session_id = session_id

    def _call(self, name, args):
        try:
            result = self.skills_manager.execute(name, args)
        except Exception as exc:
            return {'error': type(exc).__name__ + ': ' + str(exc)}
        if not isinstance(result, dict):
            return {'error': 'Resposta não estruturada de ferramenta.', 'raw_type': type(result).__name__}
        return result

    def execute(self, name, args):
        """Executa UMA ação autorizada; permite só uma repetição de leitura transitória."""
        if self.operations >= self.plan.max_tool_calls:
            return {'error': 'Limite de operações por turno atingido. '
                             'Informe a parte concluída e solicite continuação.'}
        args = args if isinstance(args, dict) else {}
        self.operations += 1
        result = self._call(name, args)
        verification = self.verifier.verify(name, args, result)
        attempts = 1
        decision = self.recovery.decide(name, args, result, verification, attempts)
        if decision.retry and self.operations < self.plan.max_tool_calls:
            attempts += 1
            self.operations += 1
            result = self._call(name, args)
            verification = self.verifier.verify(name, args, result)
            decision = self.recovery.decide(name, args, result, verification, attempts)
        self.plan.record(name, args, verification, attempts=attempts)
        if self.experience_store is not None and self.session_id:
            try:
                self.experience_store.record(self.session_id, name, verification.status, attempts)
            except Exception as exc:
                # Falha no diário nunca invalida o resultado técnico da ferramenta.
                print('[AAA_STORE] gravação indisponível: ' + type(exc).__name__)
        print('[AAA_EXEC] {} status={} tentativas={} {}'.format(
            name, verification.status, attempts, verification.detail[:100]))
        if verification.status == 'failed':
            # Falta de evidência de abertura, leitura ou teste deve ser entendida
            # como falha, não como sucesso inferido. Preserva a resposta original.
            if not result.get('error'):
                result = dict(result)
                result['error'] = 'Verificação AAA: ' + verification.detail
            if decision.advice:
                result['_aaa_recovery'] = decision.advice
        elif verification.status in ('partial', 'unverified'):
            result = dict(result)
            result['_aaa_verification'] = {
                'status': verification.status,
                'detail': verification.detail,
                'advice': decision.advice,
            }
        return result
