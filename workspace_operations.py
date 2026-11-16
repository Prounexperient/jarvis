"""Operações contextuais seguras em arquivos do projeto ativo."""
import ast
import os
from pathlib import Path
import shutil
import tempfile
from tools import _require_path, _schema, S, _confirm
from developer_workspace import _file_path, _no_symlink_ancestors, MAX_FILE_BYTES
import workspace_session as session

SCHEMAS = [
 _schema('developer_select_project', 'ATIVE um projeto ou pasta existente como workspace de trabalho, após localizar ou inspecionar o diretório. Não cria projeto nem altera arquivos. Use automaticamente quando o usuário pedir operações dentro de um projeto existente.', {'directory': S('Caminho absoluto da pasta existente autorizada')}, ['directory']),
 _schema('developer_workspace_status', 'Consulte o workspace ativo e últimas operações para resolver referências de arquivos.', {}, []),
 _schema('developer_rename_file', 'RENOMEIE arquivo existente no projeto ativo, sem criar cópia. Use caminhos relativos; bloqueia colisões.', {'source': S('Caminho relativo ou ultimo/penultimo'), 'destination': S('Novo caminho relativo')}, ['source','destination']),
 _schema('developer_delete_file', 'EXCLUA arquivo do projeto ativo SOMENTE após confirmação específica do caminho exato, com backup para desfazer. Aceita caminho relativo ou ultimo/penultimo.', {'path': S('Caminho relativo ou ultimo/penultimo')}, ['path']),
 _schema('developer_delete_derived_directory', 'EXCLUA pasta derivada explicitamente solicitada pelo usuário, incluindo conteúdo, somente após mostrar caminho completo e confirmar SIM. Não exclui raiz nem .venv.', {'directory': S('Caminho absoluto da pasta derivada a excluir')}, ['directory']),
 _schema('developer_undo_file_operation', 'DESFAÇA a última operação de arquivo registrada no workspace, quando possível.', {}, []),
]

def select_project(directory, config):
    root = _require_path(directory, config)
    _no_symlink_ancestors(root)
    if not root.is_dir():
        return {'error': 'A pasta selecionada não é um diretório.'}
    session.activate(root)
    return {'success': True, 'verified': True, 'active_root': str(root), 'existing_project': True}

def root_for(config):
    data = session.load(); name = data.get('active_root')
    if not name: raise ValueError('Nenhum projeto ativo. Crie ou selecione um projeto antes.')
    root = _require_path(name, config)
    _no_symlink_ancestors(root)
    if not root.is_dir(): raise ValueError('Projeto ativo não existe.')
    return root

def path_for(root, value):
    resolved = session.resolve_reference(root, value)
    if resolved: value = resolved
    elif value in ('ultimo','último','penultimo','penúltimo'):
        raise ValueError('Referência ordinal sem histórico suficiente; indique o nome do arquivo.')
    if not isinstance(value, str):
        raise ValueError('Caminho de arquivo inválido.')
    # Aceita caminho absoluto apenas se estiver contido no workspace ativo.
    candidate = Path(value)
    if candidate.is_absolute():
        if not candidate.is_relative_to(root):
            raise ValueError('Arquivo fora do projeto ativo.')
        value = candidate.relative_to(root).as_posix()
    rel = _file_path(value)
    target = root / rel
    _no_symlink_ancestors(target)
    return target, str(rel)

def confirm_risk(message, config):
    return _confirm(message, {'security': {'confirm_writes': True}})

def status(config):
    data = session.load()
    return {'active_root': data.get('active_root'), 'recent_operations': data.get('events', [])[-12:]}

def rename_file(source, destination, config):
    root = root_for(config)
    src, src_rel = path_for(root, source); dst, dst_rel = path_for(root, destination)
    if not src.is_file() or dst.exists(): return {'error':'Origem ausente ou destino já existe; nada alterado.'}
    if not dst.parent.is_dir(): return {'error':'Pasta de destino não existe.'}
    os.rename(src, dst)
    if src.exists() or not dst.is_file(): return {'error':'Falha de verificação após renomeação.'}
    session.record('rename', root, dst_rel, old_path=src_rel)
    return {'success':True,'verified':True,'old_path':str(src),'path':str(dst)}

def delete_file(path, config):
    root = root_for(config)
    target, rel = path_for(root, path)
    if not target.is_file(): return {'error':'Arquivo inexistente ou não regular.'}
    if target.stat().st_size > 20_000_000: return {'error':'Arquivo grande: exclusão não automatizada.'}
    if not confirm_risk('EXCLUIR SOMENTE O ARQUIVO {}?'.format(target), config):
        return {'error': 'Exclusão não autorizada.'}
    backup = session.backup(target)
    target.unlink()
    if target.exists(): return {'error':'Exclusão não verificada.'}
    session.record('delete', root, rel, backup=backup)
    return {'success':True,'verified':True,'path':str(target),'recoverable':True}

def delete_derived_directory(directory, config):
    """Remoção de pasta expressamente autorizada; nunca aceita raiz ou .venv."""
    root = (Path.home() / 'JARVIS_DERIVED_PROJECTS').resolve()
    target = Path(directory).expanduser().absolute()
    if not root.is_dir() or root not in target.parents or target == root:
        return {'error': 'Pasta fora da hierarquia derivada ou raiz protegida.'}
    if (root / '.venv') == target or (root / '.venv') in target.parents:
        return {'error': 'Ambiente virtual compartilhado protegido.'}
    if not target.is_dir() or target.is_symlink():
        return {'error': 'Pasta inexistente ou link simbólico.'}
    _no_symlink_ancestors(target)
    # Nenhum link simbólico interno pode ser percorrido ou excluído automaticamente.
    count = 0
    for current, dirs, files in os.walk(target, followlinks=False):
        for name in dirs + files:
            item = Path(current) / name
            if item.is_symlink():
                return {'error': 'Pasta contém links simbólicos; operação recusada.'}
            count += 1
            if count > 2000:
                return {'error': 'Pasta com mais de 2000 entradas; exclusão recusada.'}
    if not confirm_risk('EXCLUIR A PASTA E TODO SEU CONTEÚDO: {} ({} entradas)?'.format(target, count), config):
        return {'error': 'Exclusão não autorizada.'}
    shutil.rmtree(target)
    return {'success': not target.exists(), 'verified': not target.exists(), 'path': str(target), 'deleted_entries': count}


def undo(config):
    root = root_for(config)
    data = session.load()
    events = [e for e in data.get('events',[]) if e.get('root') == str(root) and e.get('operation') != 'undo']
    undone = {e.get('target_event') for e in data.get('events',[]) if e.get('operation') == 'undo'}
    event = next((e for e in reversed(events) if e['id'] not in undone), None)
    if not event: return {'error':'Nenhuma operação recuperável.'}
    target, rel = path_for(root, event['path'])
    op = event['operation']
    if op == 'create':
        if not target.is_file(): return {'error':'Arquivo criado não existe mais.'}
        if not confirm_risk('DESFAZER CRIAÇÃO E EXCLUIR O ARQUIVO {}?'.format(target), config):
            return {'error': 'Exclusão não autorizada.'}
        backup = session.backup(target); target.unlink()
    elif op == 'delete':
        if target.exists(): return {'error':'Destino ocupado; não é seguro restaurar.'}
        backup = event.get('backup')
        if not backup or not Path(backup).is_file(): return {'error':'Backup indisponível.'}
        shutil.copy2(backup, target)
    elif op == 'rename':
        old, _ = path_for(root, event['old_path'])
        if not target.is_file() or old.exists(): return {'error':'Não é seguro desfazer renomeação.'}
        target.rename(old)
    elif op == 'edit':
        backup = event.get('backup')
        if not backup or not Path(backup).is_file() or not target.is_file(): return {'error':'Backup de edição indisponível.'}
        shutil.copy2(backup, target)
    else: return {'error':'Operação não reversível automaticamente.'}
    session.record('undo', root, rel, target_event=event['id'])
    return {'success':True,'verified':True,'undone':op,'path':str(target)}

FUNCTIONS = {'developer_select_project':select_project,'developer_workspace_status':status,'developer_rename_file':rename_file,'developer_delete_file':delete_file,'developer_delete_derived_directory':delete_derived_directory,'developer_undo_file_operation':undo}
