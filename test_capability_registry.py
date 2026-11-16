"""Testes locais sem LM Studio, acesso a discos ou execução de arquivos."""
import tempfile
from pathlib import Path
from capability_registry import describe_capabilities
from tools import FUNCTIONS, SCHEMAS, run_tool

with tempfile.TemporaryDirectory() as root:
    cfg = {'paths': {'allowed_roots': [root, str(Path(root) / 'inexistente')]},
           'security': {'confirm_writes': True, 'confirm_program_launch': False}}
    data = run_tool('get_system_capabilities', {}, cfg)
    assert not data.get('error'), data
    assert data['allowed_roots'][0]['exists'] is True
    assert data['allowed_roots'][1]['exists'] is False
    assert data['security']['confirm_writes'] is True
    assert any(t['name'] == 'search_files' for t in data['tools'])
    assert any(t['name'] == 'read_document' for t in data['tools'])
    assert 'get_system_capabilities' in FUNCTIONS
    assert any(s['function']['name'] == 'get_system_capabilities' for s in SCHEMAS)
    assert run_tool('get_system_capabilities', {'unexpected': True}, cfg).get('error')
    assert data == describe_capabilities(cfg, FUNCTIONS, SCHEMAS)
print('PASSOU: inventário, permissões, ferramentas e validação de argumentos')
