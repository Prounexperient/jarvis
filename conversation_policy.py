"""Voice-first presentation and grounded, deterministic search-result summaries."""
from pathlib import Path
from spoken_file_presenter import add_spoken_labels


def search_feedback(result, *, requested_action=None):
    """Returns spoken text for search results without guessing a selection."""
    if 'error' in result:
        return None
    items = result.get('results', [])
    if not items:
        return 'Não encontrei arquivos correspondentes. Quer tentar outro nome?'
    if len(items) == 1:
        item = items[0]
        name = item.get('spoken_name') or Path(item['path']).stem
        suffix = ' A pesquisa atingiu o limite de tempo.' if result.get('timed_out') else ''
        return f'Encontrei um arquivo: {name}.{suffix}'
    suffix = ' A pesquisa atingiu o limite de tempo.' if result.get('timed_out') else ''
    return f'Encontrei {len(items)} arquivos. Você pode dizer, por exemplo, abra o primeiro, ou leia o segundo.{suffix}'


def voice_first_system():
    return (
        'A interação é prioritariamente por voz. Nunca peça para digitar números, índices ou caminhos; '
        'peça para DIZER ou FALAR. Ao encontrar um único arquivo, não solicite escolha de índice; '
        'trate-o como resultado único e aceite referências como esse arquivo, abra-o ou leia-o. '
        'Não abra automaticamente se o pedido foi apenas localizar. '
        'Com vários resultados, solicite seleção falada somente se a ação exigir desambiguação. '
        'Não afirme que um arquivo foi aberto ou lido sem confirmação da ferramenta.'
    )
