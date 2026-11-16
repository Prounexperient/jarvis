"""Ambiente de testes compartilhado, NÃO sandbox de segurança.

Windows: %USERPROFILE%\\JARVIS_DERIVED_PROJECTS\\.venv
Projetos: %USERPROFILE%\\JARVIS_DERIVED_PROJECTS\\<nome>
"""
import os
import ast
from pathlib import Path
import re
import subprocess
import sys
import venv
import unicodedata

from tools import _confirm, _schema, S


def _root():
    return Path.home() / 'JARVIS_DERIVED_PROJECTS'


def _project(name):
    if isinstance(name, str):
        name = ''.join(c for c in unicodedata.normalize('NFKD', name) if not unicodedata.combining(c))
        name = re.sub(r'[\s-]+', '_', name.strip()).lower()
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name):
        raise ValueError('Nome de projeto inválido; use letras, números, _ ou -.')
    root = _root().resolve()
    project = (root / name).resolve()
    if project.parent != root:
        raise ValueError('Projeto fora da raiz permitida.')
    return project


def _python():
    root = _root()
    return root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def prepare(project, config):
    """Cria pasta e venv somente mediante confirmação explícita."""
    try:
        dest = _project(project)
        root = _root()
        root.mkdir(parents=True, exist_ok=True)
        dest.mkdir(parents=True, exist_ok=True)
        interpreter = _python()
        if not interpreter.is_file():
            venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(str(root / '.venv'))
        return {'success': interpreter.is_file(), 'root': str(root), 'project': str(dest),
                'python': str(interpreter), 'shared_venv': str(root / '.venv'),
                'warning': 'Ambiente virtual isola dependências, NÃO isola acesso a arquivos/rede.'}
    except Exception as exc:
        return {'error': '{}: {}'.format(type(exc).__name__, exc)}


def run_tests(project, test_file, config):
    """Executa unittest em arquivo isolado no projeto derivado, com timeout.

    Testes Python arbitrários ainda podem acessar sistema e rede; requer aprovação.
    """
    try:
        dest = _project(project)
        if not isinstance(test_file, str) or not re.fullmatch(r'test_[A-Za-z0-9_]+\.py', test_file):
            return {'error': 'Informe arquivo test_*.py na pasta tests/ do projeto derivado.'}
        script = (dest / 'tests' / test_file).resolve()
        if script.parent != (dest / 'tests').resolve() or not script.is_file() or script.is_symlink():
            return {'error': 'Arquivo de teste inexistente ou fora da pasta derivada.'}
        interpreter = _python()
        if not interpreter.is_file():
            return {'error': 'Ambiente virtual ausente. Execute developer_prepare_test_environment.'}
        if not _confirm('EXECUTAR código Python de teste {}? Pode acessar arquivos e rede.'.format(script), {'security': {'confirm_writes': True}}):
            return {'error': 'Execução não autorizada.'}
        try:
            proc = subprocess.run([str(interpreter), '-I', str(script)], cwd=str(dest),
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  errors='replace', timeout=45)
            return {'executed': True, 'functional_tested': True,
                    'exit_code': proc.returncode, 'passed': proc.returncode == 0,
                    'stdout': proc.stdout[:12000], 'stderr': proc.stderr[:12000],
                    'project': str(dest), 'test_file': str(script),
                    'truncated': len(proc.stdout) > 12000 or len(proc.stderr) > 12000}
        except subprocess.TimeoutExpired as exc:
            return {'executed': True, 'functional_tested': False, 'error': 'Tempo limite de 45 segundos excedido.',
                    'stdout': str(exc.stdout or '')[:2000], 'stderr': str(exc.stderr or '')[:2000]}
    except Exception as exc:
        return {'error': '{}: {}'.format(type(exc).__name__, exc)}


def create_test(project, test_file, content, config):
    """Grava teste sintaticamente válido, somente em tests/ do projeto autorizada."""
    try:
        dest = _project(project)
        if not isinstance(test_file, str) or not re.fullmatch(r'test_[A-Za-z0-9_]+\.py', test_file):
            return {'error': 'Nome deve ser test_*.py.'}
        if not isinstance(content, str) or len(content.encode('utf-8')) > 100_000:
            return {'error': 'Código ausente ou acima de 100 KB.'}
        ast.parse(content)
        if not dest.is_dir():
            return {'error': 'Projeto derivado não existe. Prepare o ambiente primeiro.'}
        target = dest / 'tests' / test_file
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            return {'error': 'Teste já existe; operação não sobrescreve arquivos.'}
        with target.open('x', encoding='utf-8') as f:
            f.write(content)
        return {'success': True, 'path': str(target), 'syntax_valid': True, 'functional_tested': False}
    except Exception as exc:
        return {'error': '{}: {}'.format(type(exc).__name__, exc)}


SCHEMAS = [
    _schema('developer_prepare_test_environment', 'Cria ou reutiliza %USERPROFILE%/JARVIS_DERIVED_PROJECTS/.venv compartilhado e subpasta de projeto, sem confirmação de escrita nessa raiz. Não instala pacotes externos.', {'project': S('Nome simples da subpasta de projeto derivado')}, ['project']),
    _schema('developer_create_derived_test', 'Cria novo test_*.py em tests/ do projeto sem confirmação, sem sobrescrever. Código ainda NÃO foi executado.', {'project': S('Subpasta derivada'), 'test_file': S('Nome test_*.py'), 'content': S('Código completo do teste Python')}, ['project', 'test_file', 'content']),
    _schema('developer_run_derived_test', 'Executa um test_*.py na raiz de um projeto derivado usando o Python do .venv compartilhado, após confirmação humana. NÃO é sandbox; testes podem acessar o PC. Retorna stdout, stderr e exit_code.', {'project': S('Nome da subpasta derivada'), 'test_file': S('Nome test_*.py em tests/ do projeto')}, ['project', 'test_file']),
]
FUNCTIONS = {'developer_prepare_test_environment': prepare, 'developer_create_derived_test': create_test, 'developer_run_derived_test': run_tests}
