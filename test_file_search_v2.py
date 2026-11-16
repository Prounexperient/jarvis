"""Execute: python test_file_search_v2.py (nao altera arquivos pessoais)."""
import tempfile
from pathlib import Path
from file_search_engine import normalize, search
from tools import search_files, _result_path

assert normalize('Relatório_Financeiro-2026') == 'relatorio financeiro 2026'
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    (root / 'Relatorio_Financeiro_2026_Final.pdf').write_bytes(b'%PDF test')
    (root / 'Relatorio_2023.txt').write_text('teste', encoding='utf8')
    (root / 'Python Django.md').write_text('teste', encoding='utf8')
    (root / 'node_modules').mkdir()
    (root / 'node_modules' / 'Relatorio_Financeiro_2026.pdf').write_text('ignorar')
    cfg = {'paths': {'allowed_roots': [str(root)], 'max_search_results': 12}, 'file_search': {'timeout_seconds': 5}}
    result = search_files('relatório financeiro', cfg)
    assert result['results'] and result['results'][0]['name'] == 'Relatorio_Financeiro_2026_Final.pdf', result
    assert _result_path(1) == result['results'][0]['path']
    assert all('node_modules' not in x['path'] for x in result['results']), result
    filtered = search_files('relatorio', cfg, extension='pdf')
    assert len(filtered['results']) == 1, filtered
    assert filtered['results'][0]['extension'] == '.pdf'
    assert not search('nao existe', [root], timeout_seconds=5)['results']
    assert search('python', [root], modified_after='3000-01-01')['results'] == []
    print('Etapa 5: testes de busca, ranking, filtros, exclusoes e referencias OK')
