"""Execute: python test_contextual_actions.py"""
from contextual_actions import resolve_action
from spoken_file_presenter import spoken_name

paths = ['C:/Musicas/a.mp3', 'C:/Musicas/b.mp3', 'C:/Documentos/c.pdf']
assert resolve_action('carregue o segundo arquivo', paths) == ('open_search_result', 2)
assert resolve_action('reproduza o segundo', paths) == ('open_search_result', 2)
assert resolve_action('abra o terceiro resultado', paths) == ('open_search_result', 3)
assert resolve_action('mostre a pasta do segundo arquivo', paths) == ('reveal_search_result', 2)
assert resolve_action('carregue o terceiro arquivo', paths) is None
assert resolve_action('carregue o modelo GPT-OSS', paths) is None
assert resolve_action('não abra o segundo', paths) is None
assert resolve_action('abra o primeiro e o segundo', paths) is None
assert resolve_action('toque o primeiro', []) is None
assert spoken_name('2hollis-poster-boy-best-part-looped-slowed-youtubemp3free.org.mp3') == '2hollis poster boy best part looped slowed'
print('Testes de acoes contextuais e nomes falaveis: OK')
