"""Resumo determinístico para TTS; nunca silencia respostas comuns."""
import re


def summarize_for_speech(text, max_chars=1200, development=False):
    if not text:
        return ''
    original = str(text).strip()
    has_code = bool(re.search(r'```(?:[a-zA-Z0-9_+-]+)?\s*\n[\s\S]*?```', original))
    code_note = bool(development and has_code)
    cleaned = re.sub(r'```[\s\S]*?```', ' ', original)
    lines = []
    for line in cleaned.splitlines():
        line = line.strip()
        if not line or re.fullmatch(r'[-|: ]{3,}', line):
            continue
        if line.startswith('|'):
            # Não narrar células e cabeçalhos técnicos.
            continue
        if re.match(r'^(?:import |from \S+ import |def |class |except |return |assert )', line):
            continue
        line = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', line)
        line = re.sub(r'[`*_#>]+', '', line)
        line = re.sub(r'^[-+•]\s+', '', line)
        if line:
            lines.append(line)
    spoken = ' '.join(lines).strip()
    if len(spoken) > max_chars:
        spoken = spoken[:max_chars].rsplit(' ', 1)[0].rstrip(' ,;:') + '.'
    if code_note:
        if not spoken:
            spoken = 'Preparei um trecho de código para a tarefa solicitada.'
        spoken += ' O código completo está disponível no terminal.'
    # Sem skill de desenvolvimento, nunca emitir a mensagem técnica.
    if not spoken and not code_note:
        spoken = re.sub(r'[`*_#>|]+', ' ', original)
        spoken = re.sub(r'\s+', ' ', spoken).strip()[:max_chars]
    return spoken
