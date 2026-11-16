"""DeveloperSkill: operações explícitas e verificáveis; geração de código é do LLM."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from tools import _require_path, _confirm, _schema, S
import workspace_session as session

SCHEMAS = [
    _schema('developer_create_python', 'Crie arquivo .py solicitado. Se estiver dentro do workspace ativo, não requer confirmação. Para projetos existentes, selecione-os primeiro com developer_select_project. Não executa código.', {'path': S('Caminho absoluto do novo .py'), 'content': S('Código Python completo a gravar')}, ['path', 'content']),
    _schema('developer_inspect_project', 'Inspecione estrutura de projeto Python existente, sem executar arquivos. Retorna nomes e diretórios, limitado a 100 entradas.', {'directory': S('Diretório absoluto do projeto autorizado')}, ['directory']),
    _schema('developer_run_python', 'Execute um script Python local já existente (inclusive testes) somente após confirmação humana explícita no terminal. Código Python pode ter efeitos no PC; não é sandbox.', {'path': S('Caminho absoluto do script .py existente')}, ['path']),
]


def create_python(path, content, config):
    target = _require_path(path, config, must_exist=False)
    if target.suffix.lower() != '.py':
        return {'error': 'Somente arquivos .py são permitidos.'}
    if not target.parent.is_dir():
        return {'error': 'A pasta de destino não existe; informe uma pasta existente.'}
    if target.exists():
        return {'error': 'O arquivo já existe. Esta operação não sobrescreve arquivos.'}
    if not isinstance(content, str) or len(content.encode('utf-8')) > 200_000:
        return {'error': 'Conteúdo ausente ou maior que 200 KB.'}
    try:
        ast.parse(content, filename=str(target))
    except SyntaxError as exc:
        return {'error': f'Código com erro de sintaxe na linha {exc.lineno}: {exc.msg}'}
    active = session.load().get('active_root')
    derived = (Path.home() / 'JARVIS_DERIVED_PROJECTS').resolve()
    contextual = bool((active and target.is_relative_to(Path(active))) or derived in target.parents)
    # A solicitação da tarefa autoriza criação em raízes permitidas; somente exclusões pedem confirmação.
    descriptor = None
    try:
        descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        verified = target.read_text(encoding='utf-8') == content
        if verified and contextual: session.record('create', active, str(target.relative_to(Path(active))))
        return {'success': verified, 'path': str(target), 'bytes_written': target.stat().st_size, 'verified': verified}
    except Exception as exc:
        if descriptor is not None:
            os.close(descriptor)
        return {'error': f'{type(exc).__name__}: {exc}'}


def inspect_project(directory, config):
    root = _require_path(directory, config)
    if not root.is_dir():
        return {'error': 'O caminho não é um diretório.'}
    entries = []
    excluded = {'.git', '.venv', 'venv', '__pycache__', 'node_modules'}
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted((d for d in dirs if d not in excluded and not (Path(current)/d).is_symlink()), key=str.casefold)
        for name in sorted(files, key=str.casefold):
            path = Path(current) / name
            if not path.is_symlink():
                entries.append(str(path.relative_to(root)))
                if len(entries) >= 100:
                    return {'directory': str(root), 'files': entries, 'truncated': True}
    return {'directory': str(root), 'files': entries, 'truncated': False}


def run_python(path, config):
    target = _require_path(path, config)
    if not target.is_file() or target.suffix.lower() != '.py':
        return {'error': 'Informe um arquivo Python existente.'}
    if not _confirm(f'EXECUTAR código Python {target}? Isso pode modificar arquivos ou acessar a rede.', {'security': {'confirm_writes': True}}):
        return {'error': 'Execução não autorizada pelo usuário.'}
    try:
        derived = (Path.home() / 'JARVIS_DERIVED_PROJECTS').resolve()
        venv_python = derived / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        interpreter = venv_python if derived in target.parents and venv_python.is_file() else sys.executable
        result = subprocess.run([str(interpreter), '-I', str(target)], cwd=str(target.parent), capture_output=True, text=True, errors='replace', timeout=30, stdin=subprocess.DEVNULL)
        return {'path': str(target), 'executed': True, 'passed': result.returncode == 0, 'functional_tested': True, 'interpreter': str(interpreter), 'exit_code': result.returncode, 'stdout': result.stdout[:8000], 'stderr': result.stderr[:8000], 'truncated': len(result.stdout)>8000 or len(result.stderr)>8000}
    except subprocess.TimeoutExpired:
        return {'error': 'Execução excedeu 30 segundos.'}


FUNCTIONS = {'developer_create_python': create_python, 'developer_inspect_project': inspect_project, 'developer_run_python': run_python}
