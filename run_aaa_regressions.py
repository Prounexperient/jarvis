"""Suite de regressão offline da fundação AAA (sem Whisper ou LM Studio).

Executa grupos em processos Python separados para reduzir contaminação de
sys.modules por testes legados com mocks de 'tools'.
"""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
GROUPS = {
    'intent_gateway_memory': [
        'test_aaa_foundation', 'test_aaa_agent_gateway', 'test_quote_intent',
        'test_media_navigation_regression', 'test_media_navigation',
        'test_operational_memory', 'test_stabilization_regression',
        'test_etapa_14_1_5', 'test_etapa_15_1_2', 'test_etapa_15_1_9_5',
    ],
    'project_path': ['test_project_path_regression'],
    'navigation_origin': ['test_explicit_folder_origin'],
    'aaa_02_core': ['test_aaa_agent_core'],
}


def main():
    failures = []
    for name, modules in GROUPS.items():
        env = os.environ.copy()
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        try:
            proc = subprocess.run(
                [sys.executable, '-W', 'error::ResourceWarning', '-m', 'unittest',
                 '-q', *modules], cwd=ROOT, env=env, capture_output=True,
                text=True, errors='replace', timeout=60,
            )
        except subprocess.TimeoutExpired:
            print(f'[ERRO] {name}: timeout de 60s')
            failures.append(name)
            continue
        status = 'OK' if proc.returncode == 0 else 'FALHOU'
        print(f'[{status}] {name}\n{proc.stdout}{proc.stderr}')
        if proc.returncode:
            failures.append(name)
    if failures:
        print('Regressões reprovadas:', ', '.join(failures))
        return 1
    print('Regressões selecionadas aprovadas. Não substitui integração real no Windows.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
