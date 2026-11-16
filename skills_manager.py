"""Camada executora, sem classificador de intenção ou LLM próprio."""
from concurrent.futures import ThreadPoolExecutor
from tools import SCHEMAS as LEGACY_SCHEMAS, run_tool as legacy_run_tool
from developer_skill import SCHEMAS as DEVELOPER_SCHEMAS, FUNCTIONS as DEVELOPER_FUNCTIONS
from developer_workspace import SCHEMAS as WORKSPACE_SCHEMAS, FUNCTIONS as WORKSPACE_FUNCTIONS
from workspace_operations import SCHEMAS as OPERATION_SCHEMAS, FUNCTIONS as OPERATION_FUNCTIONS
from derived_test_environment import SCHEMAS as TEST_SCHEMAS, FUNCTIONS as TEST_FUNCTIONS


class SkillsManager:
    def __init__(self, config):
        self.config = config
        self.enabled = bool(config.get('skills', {}).get('enabled', True))
        self.schemas = list(LEGACY_SCHEMAS)
        if self.enabled:
            self.schemas.extend(DEVELOPER_SCHEMAS)
            self.schemas.extend(WORKSPACE_SCHEMAS)
            self.schemas.extend(OPERATION_SCHEMAS)
            self.schemas.extend(TEST_SCHEMAS)
        self._schemas_by_name = {s['function']['name']: s for s in self.schemas}
        # Somente ferramentas sem estado compartilhado e sem efeitos colaterais.
        self.parallel_safe = {'calculator', 'read_text_file', 'developer_inspect_project', 'developer_read_code', 'developer_map_codebase'}

    def execute(self, name, arguments):
        if name not in self._schemas_by_name:
            return {'error': 'Ferramenta não registrada.'}
        schema = self._schemas_by_name[name]['function']['parameters']
        if not isinstance(arguments, dict) or set(arguments) - set(schema['properties']):
            return {'error': 'Parâmetros inválidos.'}
        if set(schema.get('required', [])) - set(arguments):
            return {'error': 'Parâmetros obrigatórios ausentes.'}
        if name in DEVELOPER_FUNCTIONS or name in WORKSPACE_FUNCTIONS or name in OPERATION_FUNCTIONS or name in TEST_FUNCTIONS:
            try:
                print('[SKILLS_MANAGER] developer.' + name)
                return (DEVELOPER_FUNCTIONS if name in DEVELOPER_FUNCTIONS else WORKSPACE_FUNCTIONS if name in WORKSPACE_FUNCTIONS else OPERATION_FUNCTIONS if name in OPERATION_FUNCTIONS else TEST_FUNCTIONS)[name](**arguments, config=self.config)
            except Exception as exc:
                return {'error': f'{type(exc).__name__}: {exc}'}
        return legacy_run_tool(name, arguments, self.config)

    def execute_many(self, requests, parallel=False):
        """Preserva a ordem dos resultados. Concorrência só se TODAS forem read-only seguras.

        O Agent mantém execução sequencial por padrão, preservando contexto de buscas.
        """
        if parallel and len(requests) > 1 and all(name in self.parallel_safe for name, _ in requests):
            with ThreadPoolExecutor(max_workers=min(len(requests), 3)) as pool:
                futures = [pool.submit(self.execute, name, args) for name, args in requests]
                return [future.result() for future in futures]
        return [self.execute(name, args) for name, args in requests]
