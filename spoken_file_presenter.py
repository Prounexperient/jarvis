"""Resumo falável de nomes de arquivo; nunca altera o nome/caminho original."""
import re
from pathlib import Path

KNOWN_NOISE = re.compile(r'(?i)(?:[-_ ]+(?:www\.)?[a-z0-9]+(?:\.[a-z0-9]+)*\.(?:org|com|net|br))+$')


def spoken_name(filename, max_chars=105):
    stem = Path(filename).stem
    stem = KNOWN_NOISE.sub('', stem)
    stem = re.sub(r'[_-]+', ' ', stem)
    stem = re.sub(r'(?<=[a-zA-Z])(?=\d{5,})', ' ', stem)
    stem = re.sub(r'\s+', ' ', stem).strip(' ._-')
    if not stem:
        stem = Path(filename).stem.replace('_', ' ').replace('-', ' ')
    if len(stem) > max_chars:
        stem = stem[:max_chars].rsplit(' ', 1)[0].rstrip() + '…'
    return stem


def add_spoken_labels(result):
    if isinstance(result, dict) and isinstance(result.get('results'), list):
        for item in result['results']:
            if isinstance(item, dict) and 'name' in item:
                item['spoken_name'] = spoken_name(item['name'])
    return result
