"""Testes locais sem LM Studio ou Windows; mocks apenas na abertura do Explorer."""
import tempfile
from pathlib import Path
from unittest.mock import patch
import tools
from contextual_actions import resolve_action
import ast
source = ast.parse(Path(__file__).with_name("agent.py").read_text(encoding="utf-8"))
cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "Agent")
methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ("_trim_history", "_clean_tool_history")]
minimal = ast.Module(body=[ast.ClassDef(name="Agent", bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])
namespace = {}
exec(compile(ast.fix_missing_locations(minimal), "agent.py", "exec"), namespace)
Agent = namespace["Agent"]

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    folders = [root/'Musicas', root/'AI Music', root/'Music Lib']
    for d in folders: d.mkdir()
    (folders[2]/'song.mp3').write_bytes(b'ID3')
    cfg = {'paths': {'allowed_roots': [tmp], 'max_search_results': 12}, 'file_search': {'timeout_seconds': 5}}
    result = tools.search_directories('music', cfg)
    assert len(result['results']) >= 2, result
    assert tools.get_last_search_kind() == 'directories'
    assert tools.get_last_search_paths()[0] == result['results'][0]['path']
    with patch.object(tools, 'open_directory', return_value={'opened_directory': result['results'][0]['path']}) as op:
        opened = tools.open_search_result(1, cfg)
        assert opened['opened_directory'] == result['results'][0]['path']
        op.assert_called_once()
    files = tools.search_files_in_directory(str(folders[2]), cfg, extension='mp3')
    assert files['results'][0]['name'] == 'song.mp3'
    assert tools.get_last_search_kind() == 'files'
    assert resolve_action('abra a pasta numero 1', tools.get_last_search_paths()) == ('open_search_result', 1)

# Instancia sem inicializar LM Studio.
a = Agent.__new__(Agent)
a.history = [{'role':'system','content':'S'}]
for n in range(25):
    a.history += [
        {'role':'user','content':str(n)},
        {'role':'assistant','tool_calls':[{'id':f'call{n}','type':'function','function':{'name':'calculator','arguments':'{}'}}]},
        {'role':'tool','tool_call_id':f'call{n}','content':'{}'},
        {'role':'assistant','content':'ok'},
    ]
a._trim_history()
a._clean_tool_history()
assert a.history[0]['role'] == 'system'
assert a.history[1]['role'] == 'user'
assert all(m.get('role') != 'tool' or any(prev.get('role') == 'assistant' and any(c.get('id') == m.get('tool_call_id') for c in prev.get('tool_calls',[])) for prev in a.history) for m in a.history)
print('PASSOU: 14.1.2 — referencias, abertura de pastas, escopo e integridade do historico')
