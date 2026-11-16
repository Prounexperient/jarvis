"""Teste isolado, nao depende de LM Studio nem altera documentos reais."""
import tempfile
from pathlib import Path
from document_reader import extract
from tools import read_document, read_search_result, search_files

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    (root / 'Relatorio_teste.txt').write_text('A arquitetura usa modulos independentes.\n' * 20, encoding='utf-8')
    (root / 'sample.py').write_text('def hello():\n    return 42\n', encoding='utf-8')
    cfg = {'paths': {'allowed_roots': [str(root)], 'max_search_results': 12},
           'file_search': {'timeout_seconds': 5, 'min_score': 0},
           'document_reading': {'max_chars': 500, 'max_pages': 3, 'max_file_mb': 2},
           'security': {'confirm_writes': True}}
    result = read_document(str(root / 'sample.py'), cfg)
    assert 'return 42' in result['text']
    assert not result['truncated']
    result = read_document(str(root / 'Relatorio_teste.txt'), cfg)
    assert result['truncated'] and len(result['text']) == 500
    result = search_files('Relatorio', cfg)
    assert result['results'], result
    result = read_search_result(1, cfg)
    assert 'arquitetura' in result['text']
    try:
        read_document(str(root.parent / 'fora.txt'), cfg)
    except PermissionError:
        pass
    else:
        raise AssertionError('Controle de acesso falhou')
    try:
        extract(root / 'sample.exe')
    except ValueError:
        pass
    else:
        raise AssertionError('Extensao nao permitida')
    try:
        from docx import Document
        doc = Document(); doc.add_paragraph('Documento de teste'); doc.save(root / 'sample.docx')
        assert 'Documento de teste' in read_document(str(root / 'sample.docx'), cfg)['text']
    except ImportError:
        print('SKIP: python-docx nao instalado')
    try:
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.add_blank_page(width=200, height=200)
        with (root / 'sample.pdf').open('wb') as f: writer.write(f)
        result = read_document(str(root / 'sample.pdf'), cfg)
        assert result['pages_total'] == 1
    except ImportError:
        print('SKIP: pypdf nao instalado')
print('Etapa 7: testes de leitura e autorizacao OK')
