"""Ferramentas locais com controle de acesso. Não executa código arbitrário do LLM."""
import ast
import difflib
import json
import os
from pathlib import Path
import re
import subprocess
from decimal import Decimal, localcontext
from file_search_engine import search as realtime_search
from spoken_file_presenter import add_spoken_labels

_LAST_SEARCH = []
_LAST_SEARCH_KIND = None

try:
    import win32com.client
except ImportError:
    win32com = None


def _normalize_local_path(value):
    """Resolve environment tokens before Path; supports Windows %VAR% syntax."""
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError('Caminho deve ser texto.')
    raw = os.fspath(value).strip()
    if not raw or '\x00' in raw:
        raise ValueError('Caminho vazio ou inválido.')
    # os.path.expandvars on POSIX does not expand Windows %VAR%.
    def replace_var(match):
        name = match.group(1)
        if name.upper() == 'USERPROFILE':
            return os.environ.get('USERPROFILE') or str(Path.home())
        found = next((v for k, v in os.environ.items() if k.casefold() == name.casefold()), None)
        if found is None:
            raise ValueError(f'Variável de ambiente não definida: %{name}%')
        return found
    raw = re.sub(r'%([A-Za-z_][A-Za-z0-9_]*)%', replace_var, raw)
    raw = os.path.expandvars(os.path.expanduser(raw))
    if '%' in raw and re.search(r'%[^%]+%', raw):
        raise ValueError('Variável de ambiente não resolvida.')
    return Path(raw).resolve()


def _resolve_roots(config):
    roots = []
    for item in config['paths']['allowed_roots']:
        p = _normalize_local_path(item)
        if p.exists():
            roots.append(p)
    # Bibliotecas pessoais de mídia devem funcionar no Windows mesmo sem
    # configuração manual; somente diretórios existentes são acrescentados.
    if os.name == 'nt':
        for label in ('Music', 'Videos', 'Documents', 'Downloads', 'Pictures'):
            standard = (Path.home() / label).resolve()
            if standard.is_dir() and standard not in roots:
                roots.append(standard)
    derived = (Path.home() / 'JARVIS_DERIVED_PROJECTS').resolve()
    # A raiz gerenciada é autorizada mesmo antes de existir.
    roots.append(derived)
    return roots


def _allowed(path, config):
    p = _normalize_local_path(path)
    return any(p == r or r in p.parents for r in _resolve_roots(config))


def _require_path(path, config, *, must_exist=True):
    p = _normalize_local_path(path)
    derived = (Path.home() / 'JARVIS_DERIVED_PROJECTS').resolve()
    if p == derived / '.venv' or (derived / '.venv') in p.parents:
        raise PermissionError('O .venv compartilhado é gerenciado somente pelas ferramentas de ambiente.')
    if not _allowed(p, config):
        raise PermissionError(f'Caminho fora das pastas autorizadas: {p}')
    if must_exist and not p.exists():
        raise FileNotFoundError(str(p))
    return p


def _confirm(message, config):
    if not config['security'].get('confirm_writes', True):
        return True
    answer = input(f'\n[CONFIRMAÇÃO] {message}\nDigite SIM para autorizar: ').strip()
    return answer == 'SIM'


def search_files(query, config, extension=None, modified_after=None, modified_before=None):
    """Busca em tempo real, com ranking e referencias numeradas da ultima pesquisa."""
    global _LAST_SEARCH, _LAST_SEARCH_KIND
    _LAST_SEARCH = []
    _LAST_SEARCH_KIND = None
    settings = config.get('file_search', {})
    result = realtime_search(
        query, _resolve_roots(config),
        max_results=config.get('paths', {}).get('max_search_results', 12),
        timeout_seconds=settings.get('timeout_seconds', 30),
        extension=extension, modified_after=modified_after, modified_before=modified_before,
        min_score=settings.get('min_score', 35),
    )
    result = add_spoken_labels(result)
    if 'results' in result:
        _LAST_SEARCH = [item['path'] for item in result['results']]
        _LAST_SEARCH_KIND = 'files'
    return result


def search_directories(query, config, drive=None, minimum_score=60):
    """Busca SOMENTE diretórios autorizados pelo nome, sem falsos positivos de arquivos."""
    import time
    from file_search_engine import normalize, _score, SKIP_DIRS
    global _LAST_SEARCH, _LAST_SEARCH_KIND
    _LAST_SEARCH = []
    _LAST_SEARCH_KIND = None
    q = normalize(query)
    if not q:
        return {'error': 'Informe o nome da pasta.'}
    if drive is not None:
        import ntpath
        drive = str(drive).strip().rstrip(':').upper()
        if not re.fullmatch(r'[A-Z]', drive):
            return {'error': 'Letra de unidade inválida.'}
    try:
        minimum_score = float(minimum_score)
        if not 45 <= minimum_score <= 100:
            return {'error': 'Pontuação mínima inválida.'}
    except (TypeError, ValueError):
        return {'error': 'Pontuação mínima inválida.'}
    started = time.monotonic()
    timeout = float(config.get('file_search', {}).get('timeout_seconds', 30))
    candidates = []
    timed_out = False
    seen_paths = set()
    for root in _resolve_roots(config):
        if drive and ntpath.splitdrive(str(root))[0].upper() != drive + ':':
            continue
        # A própria raiz é uma candidata legítima (ex.: ~/Videos).
        # Antes este código examinava somente suas subpastas.
        root_score = _score(q, root.name)
        if root.is_dir() and root_score >= minimum_score:
            key = os.path.normcase(str(root))
            if key not in seen_paths:
                candidates.append((root_score, str(root)))
                seen_paths.add(key)
        for current, folders, files in os.walk(root, followlinks=False):
            if time.monotonic() - started > timeout:
                timed_out = True
                break
            folders[:] = [d for d in folders if d.casefold() not in SKIP_DIRS and not d.startswith('.') and not (Path(current)/d).is_symlink()]
            for folder in folders:
                score = _score(q, folder)
                candidate = str(Path(current) / folder)
                key = os.path.normcase(candidate)
                if score >= minimum_score and key not in seen_paths:
                    candidates.append((score, candidate))
                    seen_paths.add(key)
    candidates.sort(key=lambda item: (-item[0], item[1].casefold()))
    results = [{'index': i, 'name': Path(path).name, 'path': path, 'score': round(score,1), 'type': 'directory'}
               for i, (score, path) in enumerate(candidates[:12], 1)]
    _LAST_SEARCH = [item['path'] for item in results]
    _LAST_SEARCH_KIND = 'directories'
    return {'results': results, 'timed_out': timed_out, 'truncated': len(candidates)>12 or timed_out, 'type': 'directories'}



def search_directories_by_content(config, extensions=None):
    """Encontra pastas que contêm arquivos com as extensões pedidas.

    Busca limitada às raízes autorizadas, com timeout e sem seguir symlinks.
    Não altera a lista de arquivos usada por open_search_result.
    """
    import time
    from file_search_engine import SKIP_DIRS
    global _LAST_SEARCH, _LAST_SEARCH_KIND
    raw = extensions or 'mp3,wav,flac,ogg,m4a'
    requested = {x.strip().lower().lstrip('.') for x in re.split(r'[,; ]+', raw) if x.strip()}
    if not requested or len(requested) > 12 or any(not re.fullmatch(r'[a-z0-9]{1,12}', x) for x in requested):
        return {'error': 'Extensões inválidas.'}
    roots = _resolve_roots(config)
    roots = [r for r in roots if not any(r != other and other in r.parents for other in roots)]
    start = time.monotonic()
    timeout = float(config.get('file_search', {}).get('timeout_seconds', 30))
    limit = max(1, min(int(config.get('paths', {}).get('max_search_results', 12)), 50))
    matches = []
    timed_out = False
    examined = 0
    for root in roots:
        for current, folders, files in os.walk(root, followlinks=False):
            if time.monotonic() - start >= timeout:
                timed_out = True
                break
            folders[:] = [d for d in folders if not d.startswith('.') and d.casefold() not in SKIP_DIRS and not (Path(current)/d).is_symlink()]
            examined += 1
            count = sum(1 for name in files if Path(name).suffix.lower().lstrip('.') in requested and not (Path(current)/name).is_symlink())
            if count:
                matches.append({'path':str(Path(current)), 'name':Path(current).name, 'count':count, 'type':'directory'})
        if timed_out:
            break
    matches.sort(key=lambda item:(-item['count'],item['path'].casefold()))
    results = [dict(item, index=i) for i,item in enumerate(matches[:limit],1)]
    _LAST_SEARCH = [item['path'] for item in results]
    _LAST_SEARCH_KIND = 'directories'
    return {'results':results, 'extensions':sorted(requested), 'timed_out':timed_out,
            'truncated':len(matches)>limit or timed_out,
            'diagnostics':{'directories_examined':examined, 'matching_directories':len(matches)}}


def search_files_in_directory(directory, config, extension=None, query=None, extensions=None):
    """Busca arquivos somente dentro do diretório autorizado informado."""
    global _LAST_SEARCH, _LAST_SEARCH_KIND
    _LAST_SEARCH = []
    _LAST_SEARCH_KIND = None
    p = _require_path(directory, config)
    if not p.is_dir():
        return {'error': 'O caminho informado não é uma pasta.'}
    ext = str(extension or '').lower().lstrip('.')
    if ext and not re.fullmatch(r'[a-z0-9]{1,12}', ext):
        return {'error': 'Extensão inválida.'}
    allowed_extensions = set()
    if extensions is not None:
        if ext:
            return {'error': 'Use extension ou extensions, não ambos.'}
        if not isinstance(extensions, str):
            return {'error': 'Extensões inválidas.'}
        allowed_extensions = {x.strip().lower().lstrip('.') for x in extensions.split(',') if x.strip()}
        if (not allowed_extensions or len(allowed_extensions) > 16 or
                any(not re.fullmatch(r'[a-z0-9]{1,12}', x) for x in allowed_extensions)):
            return {'error': 'Extensões inválidas.'}
    # Não usa busca global e não confunde nome de pasta com nome de arquivo.
    import time
    start = time.monotonic()
    timeout = float(config.get('file_search', {}).get('timeout_seconds', 30))
    results = []
    timed_out = False
    from file_search_engine import normalize
    for current, folders, files in os.walk(p, followlinks=False):
        if time.monotonic() - start > timeout:
            timed_out = True
            break
        folders[:] = [d for d in folders if not d.startswith('.') and d.casefold() not in {'.git','.venv','venv','node_modules','__pycache__'} and not (Path(current)/d).is_symlink()]
        for filename in sorted(files, key=str.casefold):
            candidate = Path(current)/filename
            if candidate.is_symlink() or (ext and candidate.suffix.lower() != '.'+ext) or (allowed_extensions and candidate.suffix.lower().lstrip('.') not in allowed_extensions):
                continue
            if query and normalize(query) not in normalize(filename):
                continue
            results.append({'path': str(candidate), 'name': filename, 'extension': candidate.suffix.lower()})
    results.sort(key=lambda item: item['path'].casefold())
    limit = int(config.get('paths',{}).get('max_search_results',12))
    result = {'results': results[:limit], 'timed_out': timed_out, 'truncated': len(results)>limit or timed_out, 'scope': str(p), 'order': 'path_ascending'}
    result = add_spoken_labels(result)
    for i, item in enumerate(result['results'], 1):
        item['index'] = i
    _LAST_SEARCH = [item['path'] for item in result['results']]
    _LAST_SEARCH_KIND = 'files'
    return result


def get_last_search_kind():
    return _LAST_SEARCH_KIND


def get_last_search_paths():
    """Cópia da lista de resultados atual, sem expor estado mutável."""
    return tuple(_LAST_SEARCH)


def _result_path(index):
    if isinstance(index, bool) or not isinstance(index, int) or index < 1 or index > len(_LAST_SEARCH):
        raise ValueError('Numero de resultado invalido. Pesquise novamente ou escolha um indice da ultima pesquisa.')
    return _LAST_SEARCH[index - 1]


def open_search_result(index, config):
    """Abre somente arquivo que apareceu na ultima pesquisa."""
    p = _require_path(_result_path(index), config)
    if p.is_dir():
        return open_directory(str(p), config)
    return open_file(str(p), config)


def reveal_search_result(index, config):
    """Mostra o arquivo no Explorador, sem executa-lo."""
    p = _require_path(_result_path(index), config)
    if not (p.is_file() or p.is_dir()):
        raise ValueError('O resultado nao existe mais.')
    if os.name != 'nt':
        raise OSError('Esta acao requer Windows.')
    if p.is_dir():
        subprocess.Popen(['explorer.exe', str(p)], shell=False)
    else:
        subprocess.Popen(['explorer.exe', '/select,' + str(p)], shell=False)
    return {'revealed': str(p)}


def open_directory(path, config):
    p = _require_path(path, config)
    if not p.is_dir():
        raise ValueError('Não é uma pasta.')
    if os.name != 'nt':
        raise OSError('Esta acao requer Windows.')
    subprocess.Popen(['explorer.exe', str(p)], shell=False)
    return {'opened_directory': str(p)}


def open_file(path, config):
    p = _require_path(path, config)
    if not p.is_file():
        raise ValueError('Não é um arquivo.')
    if p.suffix.lower() in {'.exe', '.bat', '.cmd', '.ps1', '.psm1', '.vbs', '.msi', '.scr', '.lnk', '.com', '.pif', '.hta', '.wsf', '.wsh', '.jar', '.reg', '.cpl', '.msc', '.url', '.appref-ms', '.js', '.jse', '.py', '.pyw', '.sh', '.pl', '.rb'}:
        raise PermissionError('Arquivos executáveis e scripts não podem ser abertos por esta ferramenta.')
    os.startfile(str(p))
    return {'opened': str(p)}


def open_application(application, config):
    programs = {
        'word': ['winword.exe'],
        'bloco de notas': ['notepad.exe'],
        'notepad': ['notepad.exe'],
        'calculadora': ['calc.exe'],
        'vscode': ['code.cmd'],
        'vs code': ['code.cmd'],
        'explorador': ['explorer.exe'],
    }
    key = application.casefold().strip()
    if key not in programs:
        return {'error': 'Aplicativo não está na lista autorizada.', 'authorized': list(programs)}
    if config['security'].get('confirm_program_launch') and not _confirm(f'Abrir {key}?', config):
        return {'cancelled': True}
    try:
        subprocess.Popen(programs[key], shell=False)
    except FileNotFoundError:
        return {'error': f'Executável de {key} não encontrado no PATH. Configure o PATH ou abra manualmente.'}
    return {'launched': key}


def _evaluate_node(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        n = _evaluate_node(node.operand)
        return n if isinstance(node.op, ast.UAdd) else -n
    if isinstance(node, ast.BinOp):
        a, b = _evaluate_node(node.left), _evaluate_node(node.right)
        if isinstance(node.op, ast.Add): return a + b
        if isinstance(node.op, ast.Sub): return a - b
        if isinstance(node.op, ast.Mult): return a * b
        if isinstance(node.op, ast.Div): return a / b
        if isinstance(node.op, ast.Pow):
            if abs(b) > 1000 or abs(a) > Decimal('1e100'):
                raise ValueError('Potência fora do limite seguro.')
            return a ** b
    raise ValueError('Expressão não permitida. Use apenas números, +, -, *, / e **.')


def calculator(expression, config):
    expression = expression.strip().replace('^', '**').replace(',', '.')
    if len(expression) > 160:
        raise ValueError('Expressão muito extensa.')
    node = ast.parse(expression, mode='eval')
    with localcontext() as ctx:
        ctx.prec = 32
        value = _evaluate_node(node.body)
    return {'expression': expression, 'result': format(value, 'f')}


def create_word_document(path, text, config):
    p = _require_path(path, config, must_exist=False)
    if p.suffix.lower() != '.docx':
        raise ValueError('O caminho deve terminar com .docx.')
    if p.exists():
        return {'error': 'Arquivo já existe. Não será sobrescrito.'}
    if not _confirm(f'Criar documento Word em {p}?', config):
        return {'cancelled': True}
    import win32com.client as win32
    p.parent.mkdir(parents=True, exist_ok=True)
    word = win32.DispatchEx('Word.Application')
    word.Visible = True
    doc = word.Documents.Add()
    try:
        doc.Content.Text = text
        doc.SaveAs2(str(p), FileFormat=16)
    except Exception:
        doc.Close(False)
        word.Quit()
        raise
    return {'created': str(p), 'word_visible': True}


def read_text_file(path, config):
    p = _require_path(path, config)
    if p.suffix.lower() not in {'.py', '.txt', '.md', '.json', '.yaml', '.yml', '.csv', '.ini'}:
        raise ValueError('Extensão não autorizada para leitura textual.')
    if p.stat().st_size > 250_000:
        return {'error': 'Arquivo maior que 250 KB; leitura integral desativada nesta versão.'}
    return {'path': str(p), 'content': p.read_text(encoding='utf-8-sig')}


def read_document(path, config):
    """Le arquivo permitido sob demanda; retorna extrato limitado ao LLM."""
    from document_reader import extract
    p = _require_path(path, config)
    settings = config.get('document_reading', {})
    result = extract(p, max_chars=settings.get('max_chars', 12000),
                     max_pages=settings.get('max_pages', 12),
                     max_file_mb=settings.get('max_file_mb', 20))
    return {'path': str(p), **result}


def read_search_result(index, config):
    """Le arquivo selecionado por numero na ultima pesquisa."""
    return read_document(_result_path(index), config)


def inspect_document(path, operation, config, page=1, start_line=1, count=3, query=''):
    """Inspecao estruturada de documento com controle de caminho."""
    from document_inspector import inspect
    p = _require_path(path, config)
    settings = config.get('document_reading', {})
    return {'path':str(p), **inspect(p, operation=operation, page=page,
        start_line=start_line, count=count, query=query,
        max_file_mb=settings.get('max_file_mb',20),
        max_pages=settings.get('max_pages',12),
        max_chars=settings.get('max_chars',12000))}


def inspect_search_result(index, operation, config, page=1, start_line=1, count=3, query=''):
    return inspect_document(_result_path(index), operation, config, page, start_line, count, query)


def replace_in_text_file(path, old_text, new_text, config):
    p = _require_path(path, config)
    if p.suffix.lower() not in {'.py', '.txt', '.md', '.json', '.yaml', '.yml'}:
        raise ValueError('Extensão não autorizada para edição.')
    if p.stat().st_size > 250_000:
        raise ValueError('Arquivo muito grande.')
    if not old_text:
        raise ValueError('O texto original não pode estar vazio.')
    original = p.read_text(encoding='utf-8-sig')
    occurrences = original.count(old_text)
    if occurrences != 1:
        return {'error': f'Texto original encontrado {occurrences} vezes; esperado exatamente uma.'}
    updated = original.replace(old_text, new_text, 1)
    if p.suffix.lower() == '.py':
        compile(updated, str(p), 'exec')  # checagem sintática, não executa
    diff = ''.join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True), fromfile='antes', tofile='depois'))
    print('\n=== ALTERAÇÃO PROPOSTA ===\n' + diff[:10000])
    if not _confirm(f'Aplicar a alteração em {p}?', config):
        return {'cancelled': True}
    backup = p.with_name(p.name + '.jarvis.bak')
    if backup.exists():
        return {'error': f'Backup {backup} já existe. Mova-o antes de editar novamente.'}
    backup.write_bytes(p.read_bytes())
    p.write_text(updated, encoding='utf-8')
    return {'modified': str(p), 'backup': str(backup)}


def get_system_capabilities(config):
    """Consulta as capacidades operacionais efetivas, sem modificar o computador."""
    from capability_registry import describe_capabilities
    return describe_capabilities(config, FUNCTIONS, SCHEMAS)


FUNCTIONS = {
    'get_system_capabilities': get_system_capabilities,
    'search_files': search_files,
    'search_directories': search_directories,
    'search_directories_by_content': search_directories_by_content,
    'search_files_in_directory': search_files_in_directory,
    'open_search_result': open_search_result,
    'reveal_search_result': reveal_search_result,
    'open_file': open_file,
    'open_directory': open_directory,
    'open_application': open_application,
    'calculator': calculator,
    'create_word_document': create_word_document,
    'read_text_file': read_text_file,
    'read_document': read_document,
    'read_search_result': read_search_result,
    'inspect_document': inspect_document,
    'inspect_search_result': inspect_search_result,
    'replace_in_text_file': replace_in_text_file,
}


def _schema(name, description, properties, required):
    return {'type':'function','function':{'name':name,'description':description,'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}}

S = lambda description: {'type':'string','description':description}
SCHEMAS = [
    _schema('get_system_capabilities', 'Consulte as ferramentas registradas, raízes autorizadas e unidades detectadas antes de responder perguntas sobre acesso, permissões ou recursos do JARVIS. Não modifica nada.', {}, []),
    _schema('search_files', 'Busque em tempo real por nome aproximado, sem indice. Retorna resultados numerados por relevancia. Se houver apenas um, diga que encontrou um arquivo e nao peca indice. Para abrir use open_search_result, nunca invente caminhos.', {'query':S('Termos principais do nome, sem frases como encontre meu'), 'extension':S('Extensao opcional, como pdf ou docx'), 'modified_after':S('Data ISO opcional inclusiva, AAAA-MM-DD'), 'modified_before':S('Data ISO opcional exclusiva, AAAA-MM-DD')}, ['query']),
    _schema('search_directories_by_content', 'Localize PASTAS que contenham arquivos de áudio, vídeo ou outras extensões, sem precisar saber o nome da pasta. Padrão: mp3,wav,flac,ogg,m4a. Retorna pastas e contagens, pode abrir por índice.', {'extensions':S('Extensões separadas por vírgula, ex.: mp3,wav,flac')}, []),
    _schema('search_directories', 'Localize PASTAS pelo nome, opcionalmente restringindo a uma unidade antes de limitar os resultados. Não afirmar ausência quando timed_out.', {'query':S('Nome da pasta'), 'drive':S('Unidade opcional, letra como C ou D'), 'minimum_score':{'type':'number', 'description':'Pontuação mínima opcional, padrão 60; valor entre 45 e 100'}}, ['query']),
    _schema('search_files_in_directory', 'Liste arquivos dentro de uma pasta previamente localizada. Restringe fisicamente a busca ao diretório e ordena por caminho; para primeiro MP3 use extension mp3, depois open_search_result index 1.', {'directory':S('Caminho absoluto da pasta retornado por search_directories'), 'extension':S('Extensão opcional como mp3'), 'query':S('Filtro opcional no nome do arquivo'), 'extensions':S('Extensões opcionais separadas por vírgula; ex.: mp4,mkv,avi')}, ['directory']),
    _schema('open_search_result', 'Abre ARQUIVO ou PASTA numerado da ultima busca, se o usuario tiver pedido abertura. Com resultado unico, referencias como esse arquivo ou abra-o indicam indice 1. Se houver varios e nao houver escolha, pergunte por voz.', {'index':{'type':'integer','description':'Numero do resultado, comecando em 1'}}, ['index']),
    _schema('reveal_search_result', 'Revela arquivo ou abre pasta numerada da ultima busca no Explorador, sem executar arquivo.', {'index':{'type':'integer','description':'Numero do resultado, comecando em 1'}}, ['index']),
    _schema('open_directory', 'Abra uma pasta autorizada no Explorador do Windows, usando caminho absoluto retornado por search_directories.', {'path':S('Caminho absoluto da pasta')}, ['path']),
    _schema('open_file', 'Abra arquivo local já encontrado. Não aceita executáveis.', {'path':S('Caminho absoluto do arquivo')}, ['path']),
    _schema('open_application', 'Abra aplicativo autorizado: word, bloco de notas, calculadora, vscode, vs code, explorador.', {'application':S('Nome do programa permitido')}, ['application']),
    _schema('calculator', 'Calcule expressão matemática exata com + - * / ** e parênteses. Vírgula decimal é aceita.', {'expression':S('Exemplo: 3,3457 ** 2')}, ['expression']),
    _schema('create_word_document', 'Crie um arquivo .docx no disco e abra-o no Microsoft Word (Word precisa estar instalado).', {'path':S('Caminho .docx absoluto'), 'text':S('Texto completo do documento')}, ['path','text']),
    _schema('read_text_file', 'Leia código Python ou texto local autorizado.', {'path':S('Caminho absoluto')}, ['path']),
    _schema('read_search_result', 'Leia e extraia texto do resultado numerado da ultima busca (PDF, DOCX, TXT, codigo). Use para resumir ou responder perguntas; se truncado, avise.', {'index':{'type':'integer','description':'Numero do resultado a ler, iniciando em 1'}}, ['index']),
    _schema('read_document', 'Leia documento em caminho absoluto conhecido e autorizado (PDF, DOCX, TXT, codigo). Nao abre aplicativos. Respeite os limites de extracao.', {'path':S('Caminho absoluto existente e autorizado')}, ['path']),
    _schema('inspect_search_result', 'Inspecione resultado numerado: lines para linhas exatas extraidas; images para quantidade de imagens embutidas; find para localizar trecho. Nao invente conteudo visual.', dict({'operation':S('lines, images ou find'), 'page':{'type':'integer','description':'Pagina a inspecionar, a partir de 1'}, 'start_line':{'type':'integer','description':'Primeira linha extraida, a partir de 1'}, 'count':{'type':'integer','description':'Quantidade de linhas, de 1 a 30'}, 'query':S('Termo literal para find') }, index={'type':'integer','description':'Posicao na ultima pesquisa'}), ['index','operation']),
    _schema('inspect_document', 'Inspecione documento por caminho absoluto: lines, images ou find. Nao confunda deteccao com interpretacao de imagens.', dict({'operation':S('lines, images ou find'), 'page':{'type':'integer','description':'Pagina a inspecionar, a partir de 1'}, 'start_line':{'type':'integer','description':'Primeira linha extraida, a partir de 1'}, 'count':{'type':'integer','description':'Quantidade de linhas, de 1 a 30'}, 'query':S('Termo literal para find') }, path=S('Caminho absoluto autorizado')), ['path','operation']),
    _schema('replace_in_text_file', 'Substitua trecho exato único de arquivo Python ou texto, com diff, confirmação e backup.', {'path':S('Caminho absoluto'), 'old_text':S('Trecho exato existente'), 'new_text':S('Trecho de substituição')}, ['path','old_text','new_text']),
]


def run_tool(name, kwargs, config):
    if name not in FUNCTIONS:
        return {'error':'Ferramenta não autorizada.'}
    permitted = set(next(s['function']['parameters']['properties'] for s in SCHEMAS if s['function']['name'] == name))
    if not isinstance(kwargs, dict) or set(kwargs) - permitted:
        return {'error':'Parâmetros inválidos.'}
    try:
        return FUNCTIONS[name](**kwargs, config=config)
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}
