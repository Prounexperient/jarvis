"""Leitura local limitada e sob demanda. Sem indexacao, OCR ou execucao de documentos."""
from pathlib import Path

TEXT_EXTENSIONS = {'.txt', '.md', '.py', '.json', '.yaml', '.yml', '.csv', '.ini', '.js', '.ts', '.java', '.sql', '.html', '.css', '.xml', '.log', '.rst'}
SUPPORTED = TEXT_EXTENSIONS | {'.pdf', '.docx'}


def _text(path, max_chars):
    # Limite de bytes impede ler um arquivo gigante integralmente.
    with path.open('rb') as stream:
        raw = stream.read(min(path.stat().st_size, max_chars * 4 + 4))
    for encoding in ('utf-8-sig', 'utf-16', 'cp1252'):
        try:
            return raw.decode(encoding), encoding
        except UnicodeError:
            continue
    return raw.decode('utf-8', errors='replace'), 'utf-8 (substituicoes)'


def extract(path, *, max_chars=12000, max_pages=12, max_file_mb=20):
    """Retorna texto e metadados; indica truncamento e ausencia de texto extraivel."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError('Formato nao suportado para leitura: ' + ext)
    if not path.is_file():
        raise ValueError('Nao e um arquivo.')
    if path.stat().st_size > max_file_mb * 1024 * 1024:
        raise ValueError('Documento acima do limite de tamanho configurado.')
    max_chars = max(500, min(int(max_chars), 40000))
    max_pages = max(1, min(int(max_pages), 40))
    if ext in TEXT_EXTENSIONS:
        content, encoding = _text(path, max_chars)
        return {'text': content[:max_chars], 'truncated': len(content) > max_chars or path.stat().st_size > max_chars * 4 + 4,
                'format': ext, 'encoding': encoding, 'pages_read': None, 'pages_total': None}
    if ext == '.pdf':
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError('Dependencia ausente: instale pypdf com pip install -r requirements.txt') from exc
        reader = PdfReader(str(path), strict=False)
        total = len(reader.pages)
        parts = []
        count = 0
        for i in range(min(total, max_pages)):
            page_text = reader.pages[i].extract_text() or ''
            parts.append(f'[Pagina {i + 1}]\n' + page_text)
            count += 1
            if sum(map(len, parts)) >= max_chars:
                break
        combined = '\n\n'.join(parts)
        return {'text': combined[:max_chars], 'truncated': count < total or len(combined) > max_chars,
                'format': ext, 'pages_read': count, 'pages_total': total,
                'note': 'PDF digitalizado sem camada de texto requer OCR, nao incluido nesta etapa.' if not combined.strip() else None}
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError('Dependencia ausente: instale python-docx com pip install -r requirements.txt') from exc
    document = Document(str(path))
    parts = []
    total_len = 0
    truncated = False
    # Preserva ordem de paragrafos e tabelas no python-docx atual.
    for block in document.iter_inner_content():
        if hasattr(block, 'text'):
            value = block.text
        else:
            value = '\n'.join(' | '.join(cell.text for cell in row.cells) for row in block.rows)
        if not value.strip():
            continue
        parts.append(value)
        total_len += len(value) + 1
        if total_len > max_chars:
            truncated = True
            break
    return {'text': '\n'.join(parts)[:max_chars], 'truncated': truncated,
            'format': ext, 'pages_read': None, 'pages_total': None}
