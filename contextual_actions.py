"""Resolução conservadora de comandos sobre resultados de busca recentes.

Não substitui o LLM: somente resolve pedidos explícitos, com índice inequívoco,
para abrir/revelar resultados previamente encontrados.
"""
import re
import unicodedata
from pathlib import Path

MEDIA_EXTENSIONS = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma', '.mp4', '.mkv', '.avi', '.mov', '.webm'}
ORDINALS = {
    'primeiro': 1, 'primeira': 1, 'segundo': 2, 'segunda': 2,
    'terceiro': 3, 'terceira': 3, 'quarto': 4, 'quarta': 4,
    'quinto': 5, 'quinta': 5, 'sexto': 6, 'sexta': 6,
    'setimo': 7, 'setima': 7, 'oitavo': 8, 'oitava': 8,
    'nono': 9, 'nona': 9, 'decimo': 10, 'decima': 10,
    'ultimo': -1, 'ultima': -1,
}


def normalize(value):
    value = unicodedata.normalize('NFKD', str(value).casefold())
    return ''.join(ch for ch in value if not unicodedata.combining(ch))


def resolve_action(text, paths):
    """Retorna (acao, indice) ou None. Nunca adivinha arquivos sem referência clara."""
    if not paths:
        return None
    s = normalize(text)
    # Pedidos qualificados exigem o LLM e o contexto do diretório ativo.
    if re.search(r'\b(audio|mp3|musica|faixa|arquivo|video|imagem|foto|desta|dessa|nesta|nessa|dentro|contid[oa]|da pasta|do diretorio)\b', s):
        return None
    # Não interceptar negações ou comandos compostos.
    if re.search(r'\b(nao|nunca|jamais|sem)\b', s):
        return None
    if re.search(r'\b(pesquis|procur|busqu|encontr|list|delet|apag|exclu|remov|edit|alter|renome|copi|mov)\w*\b', s):
        return None
    reveal = bool(re.search(r'\b(mostr|revel|localiz|exib)\w*\b', s) and re.search(r'\b(pasta|explorador|diretorio|localizacao)\b', s))
    play = bool(re.search(r'\b(abra|abrir|abre|abri|toque|tocar|reproduza|reproduzir|reproduz|execute|executar|coloque|colocar|carregue|carregar|carrega)\b', s))
    if not (reveal or play):
        return None
    if re.search(r'\b(modelo|gpt|qwen|programa|aplicativo)\b', s):
        return None
    candidates = []
    for word, index in ORDINALS.items():
        if re.search(r'\b' + word + r'\b', s):
            candidates.append(index)
    # Números somente quando acompanhados de referência à lista/arquivo.
    if re.search(r'\b(arquivo|resultado|musica|faixa|item|numero|posicao|lista|mp3|video|pasta|diretorio)\b', s):
        candidates += [int(x) for x in re.findall(r'\b(?:n(?:umero|o)?\.?\s*|#)(\d{1,2})\b', s)]
        candidates += [int(x) for x in re.findall(r'\b(\d{1,2})(?:o|a)?\b', s)]
    candidates = set(candidates)
    if len(candidates) > 1:
        return None
    if not candidates:
        # Singular references are safe only when there is exactly one result.
        # Do not resolve vague commands when several results are available.
        if len(paths) != 1 or not re.search(
            r'\b(arquivo|documento|pdf|resultado|musica|faixa|video|ele|ela|esse|essa|este|esta|isso|o|a)\b', s
        ):
            return None
        index = 1
    else:
        index = candidates.pop()
    if index == -1:
        index = len(paths)
    if index < 1 or index > len(paths):
        return None
    if not reveal and re.search(r'\b(carregue|carregar|carrega|toque|tocar|reproduza|reproduzir|reproduz)\b', s):
        if Path(paths[index - 1]).suffix.lower() not in MEDIA_EXTENSIONS:
            return None
    return ('reveal_search_result' if reveal else 'open_search_result', index)
