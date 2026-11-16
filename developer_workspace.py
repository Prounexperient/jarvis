"""Etapa 15.1: operações de workspace; nenhuma decisão de LLM aqui."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from tools import _require_path, _confirm, _schema, S
import workspace_session as session

EXCLUDED = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.jarvis_backups'}
MAX_FILES = 30
MAX_FILE_BYTES = 120_000
MAX_TOTAL_BYTES = 500_000

SCHEMAS = [
    _schema('developer_create_project', 'LEGADO: evite esta ferramenta; prefira developer_create_project_structured. Crie projeto novo com várias pastas e arquivos em uma única operação. LLM fornece JSON array de objetos {path,content} com caminhos RELATIVOS. Não instala nem executa dependências. Pasta raiz absoluta deve não existir e estar dentro das raízes autorizadas. Autorização contextual.', {'directory': S('Caminho absoluto de uma NOVA pasta de projeto'), 'files_json': S('JSON array de {"path":"src/main.py","content":"..."}; até 30 arquivos e 500KB no total')}, ['directory', 'files_json']),
    _schema('developer_create_project_structured', 'PREFERIDA: crie projeto novo com arquivos estruturados (array de objetos), SEM JSON em string. Valida sintaxe Python, caminhos, limites, usa autorização contextual e grava atomicamente. Até 30 arquivos. Inclua todos os arquivos solicitados, até 30, na mesma chamada; se faltar algum, use developer_add_project_files.', {'directory': S('Caminho absoluto da NOVA pasta do projeto; use %USERPROFILE%/JARVIS_DERIVED_PROJECTS/<nome> ou caminho absoluto autorizado. Variáveis serão expandidas pela ferramenta.'), 'files': {'type': 'array', 'description': 'Arquivos do projeto, objetos com path relativo e content de texto. NÃO serialize esta lista como string JSON.', 'minItems': 1, 'maxItems': 30, 'items': {'type': 'object', 'properties': {'path': S('Caminho relativo, por exemplo src/main.py'), 'content': S('Código ou texto completo, sem escape manual de JSON')}, 'required': ['path','content'], 'additionalProperties': False}}}, ['directory','files']),
    _schema('developer_add_project_files', 'ADICIONE arquivos a um projeto JÁ EXISTENTE, inclusive README.md, requirements.txt, .py, .json e subpastas. Use após developer_create_project_structured; NUNCA recrie a pasta. Não sobrescreve arquivos, valida Python, autorização contextual. Envie todos os arquivos faltantes em uma chamada.', {'directory': S('Pasta absoluta do projeto existente'), 'files': {'type': 'array', 'description': 'Arquivos NOVOS: [{path relativo, content completo}]. Sem JSON como string.', 'minItems': 1, 'maxItems': 30, 'items': {'type': 'object', 'properties': {'path': S('Caminho relativo como README.md ou src/downloader.py'), 'content': S('Conteúdo integral do arquivo')}, 'required': ['path', 'content'], 'additionalProperties': False}}}, ['directory', 'files']),
    _schema('developer_read_code', 'Leia um arquivo de código ou configuração existente no workspace para compreender ou editar; não executa código. Até 30KB.', {'path': S('Caminho absoluto de arquivo autorizado'), 'function_name': S('Opcional: nome da função Python em foco para análise')}, ['path']),
    _schema('developer_patch_file', 'Substitua exatamente UMA ocorrência de old_text por new_text em arquivo de texto existente. Leia o arquivo antes. Cria backup sem confirmação adicional de edição. Não executa código.', {'path': S('Caminho absoluto do arquivo existente'), 'old_text': S('Trecho exato existente; precisa ocorrer uma única vez'), 'new_text': S('Trecho substituto completo')}, ['path','old_text','new_text']),
    _schema('developer_replace_function', 'PREFERIDA: substitua uma função Python pelo nome, com nova definição completa. Sem old_text/JSON aninhado. Autorização contextual, backup e valida AST. Leia o arquivo antes.', {'path': S('Caminho absoluto do .py existente'), 'function_name': S('Nome exato da função existente'), 'new_source': S('Definição Python completa incluindo def/async def')}, ['path','function_name','new_source']),
    _schema('developer_replace_file', 'Substitua arquivo de texto completo após leitura, com verificação SHA256 opcional. Autorização contextual, backup e valida AST para Python.', {'path': S('Caminho absoluto do arquivo existente'), 'content': S('Conteúdo novo completo'), 'expected_sha256': S('Opcional: hash SHA256 da versão lida')}, ['path','content']),
    _schema('developer_verify_code', 'Verifique sem executar se um arquivo Python existente contém as funções, classes ou métodos solicitados. Retorna verificação estrutural AST, NÃO teste funcional. Use após editar código.', {'path': S('Caminho absoluto do arquivo Python'), 'expected_functions_json': S('JSON array de nomes de funções/métodos esperados, por exemplo ["download_video","imprimir_nome"]')}, ['path','expected_functions_json']),
    _schema('developer_map_codebase', 'Mapeie estrutura de módulos Python, classes, funções e imports, sem executar arquivos. Diretório absoluto autorizado; limite de 60 arquivos Python.', {'directory': S('Diretório absoluto do projeto')}, ['directory']),
]


def _file_path(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('Use caminho relativo com /, sem barra invertida ou NUL.')
    rel = Path(value)
    if rel.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')) or ':' in value or rel.parts[0] in EXCLUDED:
        raise ValueError('Caminho relativo inválido ou reservado.')
    if any(part in EXCLUDED or part.startswith('.') for part in rel.parts):
        raise ValueError('Pastas ocultas ou reservadas não são permitidas.')
    return rel


def _no_symlink_ancestors(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Caminho contém link simbólico.')


def _confirm_write(message, target=None, *, creation=False):
    """A autorização de escrita é dada pelo escopo da tarefa e pela raiz permitida.

    As chamadas validam caminhos com _require_path; exclusões usam confirmação
    individual em workspace_operations, nunca esta função.
    """
    return True


def create_project(directory, files_json, config):
    # Compatibilidade com projetos antigos; o contrato novo usa uma lista real.
    if not isinstance(files_json, str) or len(files_json) > 650_000:
        return {'error': 'Manifesto excede o limite.'}
    try:
        files = json.loads(files_json)
    except (ValueError, TypeError) as exc:
        return {'error': f'Manifesto JSON inválido: {exc}. Use developer_create_project_structured com files como array, sem string JSON.'}
    return create_project_structured(directory, files, config)

def create_project_structured(directory, files, config):
    root = _require_path(directory, config, must_exist=False)
    _no_symlink_ancestors(root)
    if root.exists():
        return {'error': f'Projeto já existe: {root}. Inspecione-o; não exclua nem crie _v2 automaticamente.', 'error_code': 'PROJECT_EXISTS', 'directory': str(root)}
    if not root.parent.is_dir():
        managed = (Path.home() / 'JARVIS_DERIVED_PROJECTS').resolve()
        if root.parent == managed:
            # Apenas a raiz padrão pode ser criada automaticamente.
            try:
                if managed.is_symlink():
                    return {'error': 'Raiz gerenciada é link simbólico.', 'error_code': 'UNSAFE_PARENT'}
                managed.mkdir(exist_ok=True)
                _no_symlink_ancestors(root)
            except OSError as exc:
                return {'error': f'Não foi possível preparar a raiz gerenciada: {exc}', 'error_code': 'PARENT_CREATE_FAILED'}
        else:
            return {'error': f'Pasta pai não existe: {root.parent}', 'error_code': 'PARENT_MISSING'}
    if not root.parent.is_dir():
        return {'error': f'Destino pai não é diretório: {root.parent}', 'error_code': 'PARENT_NOT_DIRECTORY'}
    try:
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
            return {'error': 'Informe de 1 a 30 arquivos.'}
        seen, prepared, total = set(), [], 0
        for item in files:
            if not isinstance(item, dict) or set(item) != {'path','content'} or not isinstance(item['content'], str):
                return {'error': 'Cada item precisa ter path e content (strings).'}
            rel = _file_path(item['path'])
            key = str(rel).casefold()
            if key in seen:
                return {'error': 'Caminhos duplicados.'}
            seen.add(key)
            raw = item['content'].encode('utf-8')
            total += len(raw)
            if len(raw) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                return {'error': 'Limite de tamanho excedido (120KB/arquivo; 500KB total).'}
            if rel.suffix.lower() == '.py':
                ast.parse(item['content'], filename=str(rel))
            prepared.append((rel, item['content']))
    except (ValueError, TypeError, SyntaxError) as exc:
        return {'error': f'Manifesto inválido: {exc}'}
    if not _confirm_write(f'Criar projeto {root} com {len(prepared)} arquivos ({total} bytes)?', creation=True):
        return {'error': 'Criação não autorizada.'}
    stage = Path(tempfile.mkdtemp(prefix='.jarvis_stage_', dir=str(root.parent)))
    try:
        for rel, content in prepared:
            target = stage / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8', newline='\n') as f:
                f.write(content)
        if any((stage / rel).read_text(encoding='utf-8') != content for rel, content in prepared):
            return {'error': 'Falha na verificação de conteúdo.'}
        if root.exists():
            return {'error': 'Destino passou a existir durante a operação.'}
        stage.rename(root)
        session.activate(root)
        for rel, _ in prepared: session.record('create', root, str(rel))
        return {'success': True, 'directory': str(root), 'files': [str(rel) for rel, _ in prepared], 'verified': True, 'functional_tested': False, 'verification_scope': 'files_written_and_read_back'}
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def add_project_files(directory, files, config):
    """Adiciona arquivos novos a um projeto existente, sem sobrescrever arquivos.

    Valida o lote inteiro antes da confirmação e reverte apenas os arquivos
    criados por esta operação se houver falha de gravação.
    """
    root = _require_path(directory, config)
    _no_symlink_ancestors(root)
    if not root.is_dir():
        return {'error': 'A pasta do projeto precisa existir.'}
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        return {'error': 'Informe de 1 a 30 arquivos.'}
    prepared, seen, total = [], set(), 0
    try:
        for item in files:
            if not isinstance(item, dict) or set(item) != {'path', 'content'} or not isinstance(item['content'], str):
                return {'error': 'Cada arquivo precisa de path e content (strings).'}
            rel = _file_path(item['path'])
            key = str(rel).casefold()
            if key in seen:
                return {'error': 'Caminhos duplicados no lote.'}
            seen.add(key)
            target = root / rel
            _no_symlink_ancestors(target)
            if target.exists():
                return {'error': f'Arquivo já existe, sem sobrescrita: {rel}'}
            if any(parent.exists() and not parent.is_dir() for parent in target.parents if parent != root):
                return {'error': f'Pasta intermediária inválida: {rel}'}
            raw = item['content'].encode('utf-8')
            total += len(raw)
            if len(raw) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                return {'error': 'Limite de tamanho excedido (120KB/arquivo, 500KB/lote).'}
            if rel.suffix.lower() == '.py':
                ast.parse(item['content'], filename=str(rel))
            prepared.append((target, item['content'], str(rel)))
    except (ValueError, SyntaxError, TypeError) as exc:
        return {'error': f'Arquivos inválidos: {exc}'}
    if not _confirm_write(f'Adicionar {len(prepared)} arquivos ao projeto {root} ({total} bytes)?', target=root):
        return {'error': 'Criação não autorizada.'}
    created_files, created_dirs = [], []
    try:
        for target, content, rel in prepared:
            missing = []
            parent = target.parent
            while parent != root and not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for folder in reversed(missing):
                folder.mkdir()  # não aceita diretórios criados concorrentemente
                created_dirs.append(folder)
            _no_symlink_ancestors(target)
            with target.open('x', encoding='utf-8', newline='\n') as handle:
                created_files.append(target)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if target.read_text(encoding='utf-8') != content:
                raise OSError(f'Falha na verificação de {rel}')
        session.activate(root)
        for _, _, rel in prepared: session.record('create', root, rel)
        return {'success': True, 'directory': str(root), 'files': [rel for _, _, rel in prepared], 'verified': True, 'functional_tested': False}
    except Exception as exc:
        for target in reversed(created_files):
            target.unlink(missing_ok=True)
        for folder in reversed(created_dirs):
            try:
                folder.rmdir()
            except OSError:
                pass
        return {'error': f'{type(exc).__name__}: {exc}', 'rolled_back': True}


def read_code(path, config, function_name=None):
    target = _require_path(path, config)
    _no_symlink_ancestors(target)
    if not target.is_file() or target.stat().st_size > 30_000:
        return {'error': 'Arquivo inexistente, não regular ou maior que 30KB.'}
    try:
        content = target.read_text(encoding='utf-8-sig')
        result = {'path': str(target), 'content': content}
        if function_name:
            if target.suffix.lower() != '.py':
                return {'error': 'Seleção de função disponível somente para Python.'}
            tree = ast.parse(content)
            nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function_name]
            if len(nodes) != 1:
                return {'error': 'Função não encontrada de forma inequívoca; informe arquivo e nome.'}
            node = nodes[0]
            result['function_name'] = function_name
            result['function_source'] = ''.join(content.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])
        return result
    except (UnicodeError, OSError) as exc:
        return {'error': f'Falha ao ler UTF-8: {exc}'}


def patch_file(path, old_text, new_text, config):
    target = _require_path(path, config)
    _no_symlink_ancestors(target)
    if not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
        return {'error': 'Arquivo não suportado ou maior que 120KB.'}
    if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
        return {'error': 'Trechos inválidos.'}
    try:
        original = target.read_text(encoding='utf-8')
    except (UnicodeError, OSError) as exc:
        return {'error': f'Falha ao ler UTF-8: {exc}'}
    if original.count(old_text) != 1:
        return {'error': 'Trecho antigo não encontrado exatamente uma vez. Releia o arquivo.'}
    changed = original.replace(old_text, new_text, 1)
    if len(changed.encode('utf-8')) > MAX_FILE_BYTES:
        return {'error': 'Arquivo resultante excede 120KB.'}
    if target.suffix.lower() == '.py':
        try:
            ast.parse(changed, filename=str(target))
        except SyntaxError as exc:
            return {'error': f'Código inválido: linha {exc.lineno}: {exc.msg}'}
    if not _confirm_write(f'Editar {target}? Backup será preservado.', target=target):
        return {'error': 'Edição não autorizada.'}
    backup = target.with_name(target.name + '.jarvis_backup_' + uuid.uuid4().hex[:12])
    temp_path = None
    try:
        # Impede alteração silenciosa se arquivo mudou durante a confirmação.
        if target.read_text(encoding='utf-8') != original:
            return {'error': 'Arquivo mudou durante a confirmação. Releia antes de editar.'}
        shutil.copy2(target, backup)
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n', dir=str(target.parent), prefix='.jarvis_edit_', delete=False) as f:
            temp_path = Path(f.name)
            f.write(changed)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target)
        temp_path = None
        verified = target.read_text(encoding='utf-8') == changed
        if verified: session.record('edit', target.parent, target.name, backup=str(backup))
        return {'success': verified, 'verified': verified, 'path': str(target), 'backup': str(backup)}
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}', 'backup': str(backup) if backup.exists() else None}
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def _safe_replace(target, original, changed, config):
    if len(changed.encode('utf-8')) > MAX_FILE_BYTES:
        return {'error': 'Arquivo resultante excede 120KB.'}
    if target.suffix.lower() == '.py':
        try:
            ast.parse(changed, filename=str(target))
        except SyntaxError as exc:
            return {'error': f'Código inválido: linha {exc.lineno}: {exc.msg}'}
    try:
        if not _confirm_write(f'Editar {target}? Backup será preservado.', target=target):
            return {'error': 'Edição não autorizada.'}
    except (OSError, EOFError) as exc:
        return {'error': 'Confirmação indisponível no terminal: ' + str(exc)}
    backup = target.with_name(target.name + '.jarvis_backup_' + uuid.uuid4().hex[:12])
    temp_path = None
    try:
        if target.read_text(encoding='utf-8') != original:
            return {'error': 'Arquivo mudou durante a confirmação. Releia antes de editar.'}
        shutil.copy2(target, backup)
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n', dir=str(target.parent), prefix='.jarvis_edit_', delete=False) as f:
            temp_path = Path(f.name)
            f.write(changed)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target)
        temp_path = None
        verified = target.read_text(encoding='utf-8') == changed
        if verified:
            active = session.load().get('active_root')
            if active and target.is_relative_to(Path(active)):
                session.record('edit', active, str(target.relative_to(active)), backup=str(backup))
        return {'success': verified, 'verified': verified, 'syntax_valid': True if target.suffix.lower() == '.py' else None, 'functional_tested': False, 'path': str(target), 'backup': str(backup)}
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}', 'backup': str(backup) if backup.exists() else None}
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def replace_file(path, content, config, expected_sha256=None):
    target = _require_path(path, config)
    _no_symlink_ancestors(target)
    if not target.is_file() or target.stat().st_size > MAX_FILE_BYTES or not isinstance(content, str):
        return {'error': 'Arquivo inválido, muito grande ou conteúdo não textual.'}
    try:
        original = target.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        return {'error': str(exc)}
    if expected_sha256 and hashlib.sha256(original.encode('utf-8')).hexdigest() != expected_sha256:
        return {'error': 'Hash divergente: releia o arquivo antes de editar.'}
    if original == content:
        return {'error': 'Nenhuma alteração proposta.'}
    return _safe_replace(target, original, content, config)


def replace_function(path, function_name, new_source, config):
    target = _require_path(path, config)
    _no_symlink_ancestors(target)
    if not target.is_file() or target.suffix.lower() != '.py' or target.stat().st_size > MAX_FILE_BYTES:
        return {'error': 'Arquivo Python inválido ou maior que 120KB.'}
    if not isinstance(function_name, str) or not function_name.isidentifier() or not isinstance(new_source, str):
        return {'error': 'Argumentos inválidos.'}
    try:
        original = target.read_text(encoding='utf-8')
        tree = ast.parse(original)
        replacement = ast.parse(new_source)
        if len(replacement.body) != 1 or not isinstance(replacement.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)) or replacement.body[0].name != function_name:
            return {'error': 'new_source deve conter uma única definição da função indicada.'}
        # Apenas funções de módulo: evita substituir métodos ambíguos por engano.
        matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function_name]
        if len(matches) != 1:
            return {'error': 'Função de módulo não encontrada de forma inequívoca.'}
        node = matches[0]
        lines = original.splitlines(keepends=True)
        start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
        end = node.end_lineno
        changed = ''.join(lines[:start]) + new_source.rstrip('\n') + '\n' + ''.join(lines[end:])
        return _safe_replace(target, original, changed, config)
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}


def map_codebase(directory, config):
    root = _require_path(directory, config)
    _no_symlink_ancestors(root)
    if not root.is_dir():
        return {'error': 'Informe diretório válido.'}
    modules, truncated = [], False
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not (Path(current) / d).is_symlink())
        for name in sorted(files):
            path = Path(current) / name
            if path.suffix.lower() != '.py' or path.is_symlink():
                continue
            if len(modules) >= 60:
                truncated = True
                break
            info = {'path': str(path.relative_to(root))}
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    info['error'] = 'Arquivo maior que 120KB'
                else:
                    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
                    info['classes'] = [n.name for n in tree.body if isinstance(n, ast.ClassDef)][:30]
                    info['functions'] = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))][:40]
                    info['imports'] = list(dict.fromkeys([a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names] + [n.module or '' for n in tree.body if isinstance(n, ast.ImportFrom)]))[:35]
            except (OSError, SyntaxError, UnicodeError) as exc:
                info['error'] = f'{type(exc).__name__}: {exc}'
            modules.append(info)
        if truncated:
            break
    return {'directory': str(root), 'modules': modules, 'truncated': truncated}


FUNCTIONS = {'developer_create_project': create_project, 'developer_create_project_structured': create_project_structured, 'developer_add_project_files': add_project_files, 'developer_read_code': read_code, 'developer_patch_file': patch_file, 'developer_replace_function': replace_function, 'developer_replace_file': replace_file, 'developer_map_codebase': map_codebase}


def verify_code(path, expected_functions_json, config):
    """Verificação AST somente leitura: não afirma comportamento funcional."""
    target = _require_path(path, config)
    _no_symlink_ancestors(target)
    if not target.is_file() or target.suffix.lower() != '.py' or target.stat().st_size > MAX_FILE_BYTES:
        return {'error': 'Informe arquivo Python válido de até 120KB.'}
    try:
        expected = json.loads(expected_functions_json)
        if not isinstance(expected, list) or not expected or len(expected) > 30 or any(not isinstance(x, str) or not x.isidentifier() for x in expected):
            return {'error': 'Informe lista JSON de 1 a 30 nomes de funções válidos.'}
        tree = ast.parse(target.read_text(encoding='utf-8-sig'), filename=str(target))
        functions = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        found = sorted(set(expected) & functions)
        missing = sorted(set(expected) - functions)
        return {'path': str(target), 'syntax_valid': True, 'structural_verified': not missing,
                'functions_found': found, 'functions_missing': missing, 'functional_tested': False}
    except (ValueError, TypeError, SyntaxError, UnicodeError, OSError) as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}

FUNCTIONS['developer_verify_code'] = verify_code
