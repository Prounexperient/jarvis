"""Interpretação conservadora de comandos de interrupção da narração."""
import re
import unicodedata

def parse_voice_control(text):
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))
    normalized = re.sub(r'[^a-z0-9 ]+', ' ', normalized).strip()
    if not normalized.startswith('jarvis '):
        return None
    command = normalized[7:]
    if command in ('fique em silencio e continue', 'fique em silencio', 'pare de falar'):
        return 'silence'
    if command in ('resuma a fala', 'resuma sua fala'):
        return 'summarize'
    if command in ('conclua o assunto', 'conclua sua fala'):
        return 'conclude'
    return None
