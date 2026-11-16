"""Gerenciamento conservador de modelos locais pelo CLI do LM Studio.

Não altera a aplicação JARVIS existente. Requer `lms` no PATH do Windows.
O gerente controla apenas os identificadores configurados; não descarrega modelos
estranhos ao projeto. Se não conseguir confirmar a descarga, NÃO carrega outro.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

LOG = logging.getLogger(__name__)


class ModelManagerError(RuntimeError):
    """Falha segura na alternância de modelos."""


@dataclass(frozen=True)
class ModelSpec:
    name: str
    identifier: str


DEFAULT_MODELS = {
    'qwen': ModelSpec('qwen', 'qwen3.5-9b-uncensored-hauhaucs-aggressive.gguf'),
    'gpt_oss': ModelSpec('gpt_oss', 'openai/gpt-oss-20b'),
}


class ModelManager:
    """Mantém no máximo um modelo *gerenciado* carregado.

    Importante: uma instância externa pode carregar modelos fora deste processo.
    Verificamos `lms ps` antes e depois da troca, mas não podemos impedir
    carregamentos concorrentes realizados manualmente ou por outro programa.
    """

    def __init__(
        self,
        models: Optional[dict[str, ModelSpec]] = None,
        cli: str = 'lms',
        timeout_seconds: float = 180,
        poll_seconds: float = 1.0,
        runner: Optional[Callable] = None,
    ):
        self.models = dict(models or DEFAULT_MODELS)
        if not self.models:
            raise ValueError('Configure ao menos um modelo.')
        self.cli = cli
        self.timeout_seconds = float(timeout_seconds)
        self.poll_seconds = float(poll_seconds)
        self._runner = runner or subprocess.run
        self._lock = threading.RLock()

    def _run(self, *args: str) -> str:
        command = [self.cli, *args]
        try:
            result = self._runner(
                command, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=self.timeout_seconds, check=False,
            )
        except FileNotFoundError as exc:
            raise ModelManagerError(
                'Comando lms não encontrado. Abra o terminal com o LM Studio CLI disponível.'
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ModelManagerError(f'Tempo esgotado executando: {" ".join(command)}') from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or 'sem detalhes').strip()
            raise ModelManagerError(f'Falha no comando {" ".join(command)}: {detail}')
        if args == ('ps',) and not result.stdout.strip():
            if 'No models are currently loaded.' in (result.stderr or ''):
                return 'NO_MODELS_LOADED'
        return result.stdout or ''

    def loaded(self) -> set[str]:
        """Identifica modelos gerenciados na saída tabular de `lms ps`.

        O formato textual pode mudar entre versões do LM Studio; em caso de
        saída inesperada, falhamos de forma conservadora, sem carregar outro.
        """
        output = self._run('ps')
        if output == 'NO_MODELS_LOADED':
            return set()
        if 'IDENTIFIER' not in output or 'MODEL' not in output:
            raise ModelManagerError('Formato inesperado de `lms ps`; alternância cancelada.')
        found = set()
        for line in output.splitlines():
            cells = line.strip().split()
            if not cells or cells[0] == 'IDENTIFIER':
                continue
            for name, spec in self.models.items():
                if cells[0].casefold() == spec.identifier.casefold():
                    found.add(name)
        return found

    def _wait_until(self, predicate: Callable[[set[str]], bool], label: str) -> set[str]:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            active = self.loaded()
            if predicate(active):
                return active
            if time.monotonic() >= deadline:
                raise ModelManagerError(f'Tempo esgotado aguardando {label}. Modelos: {sorted(active)}')
            time.sleep(self.poll_seconds)

    def ensure_loaded(self, name: str) -> str:
        """Retorna o ID do modelo somente após confirmar exclusividade gerenciada."""
        if name not in self.models:
            raise ModelManagerError(f'Modelo desconhecido: {name!r}. Opções: {list(self.models)}')
        with self._lock:
            start = time.monotonic()
            active = self.loaded()
            others = sorted(active - {name})
            for other in others:
                LOG.info('Descarregando %s...', other)
                self._run('unload', self.models[other].identifier)
                self._wait_until(lambda s, other=other: other not in s, f'descarga de {other}')
            # Revalida imediatamente antes do carregamento.
            active = self.loaded()
            if active - {name}:
                raise ModelManagerError('Outro modelo gerenciado continua carregado; abortando.')
            if name not in active:
                LOG.info('Carregando %s...', name)
                self._run('load', self.models[name].identifier)
                self._wait_until(lambda s: name in s, f'carga de {name}')
            active = self.loaded()
            if active != {name}:
                raise ModelManagerError(
                    f'Estado inesperado após alternância: {sorted(active)}. '
                    'Não envie requisições até verificar o LM Studio.'
                )
            LOG.info('Modelo pronto: %s (%.1fs)', name, time.monotonic() - start)
            return self.models[name].identifier

    def unload_all_managed(self) -> None:
        with self._lock:
            for name in sorted(self.loaded()):
                self._run('unload', self.models[name].identifier)
                self._wait_until(lambda s, name=name: name not in s, f'descarga de {name}')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if not shutil.which('lms'):
        raise SystemExit('Não foi encontrado `lms` no PATH.')
    manager = ModelManager()
    print('Modelos gerenciados carregados:', sorted(manager.loaded()))
