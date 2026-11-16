"""Teste isolado sem LM Studio, sem modificar o estado real do usuário."""
import tempfile
from pathlib import Path
import workspace_session as session
from workspace_operations import select_project, rename_file, delete_file, undo, status
from developer_skill import create_python
from developer_workspace import create_project_structured, add_project_files

def test_workspace():
    old_state, old_backup = session.STATE, session.BACKUP_DIR
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        session.STATE, session.BACKUP_DIR = root/'state.json', root/'backups'
        config = {'paths': {'allowed_roots': [str(root)]}, 'security': {'confirm_writes': True}}
        try:
            existing = root/'existing'; existing.mkdir()
            (existing/'fig.json').write_text('{}')
            assert select_project(str(existing), config)['success']
            assert delete_file(str(existing/'fig.json'), config)['success']
            assert undo(config)['success']
            assert (existing/'fig.json').exists()
            assert create_python(str(existing/'test.py'), 'print(1)', config)['success']
            assert rename_file(str(existing/'test.py'), str(existing/'renamed.py'), config)['success']
            assert delete_file('renamed.py', config)['success']
            assert undo(config)['success']
            assert (existing/'renamed.py').exists()
            try:
                delete_file(str(root/'other.txt'), config)
                assert False, 'deveria bloquear caminho externo'
            except ValueError:
                pass
            new = root/'new'
            assert create_project_structured(str(new), [{'path':'main.py','content':'print(1)'}], config)['success']
            assert add_project_files(str(new), [{'path':'README.md','content':'ok'}], config)['success']
            assert status(config)['active_root'] == str(new)
        finally:
            session.STATE, session.BACKUP_DIR = old_state, old_backup

if __name__ == '__main__':
    test_workspace()
    print('PASS: workspace preexistente, paths, criação, rename, delete, undo e novo projeto')
