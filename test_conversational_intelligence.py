from contextual_actions import resolve_action
from conversation_policy import search_feedback, voice_first_system

pdf = [r'D:\Documentos\unico.pdf']
mp3 = [r'D:\Musicas\faixa.mp3']
multi = [r'D:\Documentos\um.pdf', r'D:\Documentos\dois.pdf']
assert resolve_action('abra esse arquivo', pdf) == ('open_search_result', 1)
assert resolve_action('abra-o', pdf) == ('open_search_result', 1)
assert resolve_action('abra o arquivo', pdf) == ('open_search_result', 1)
assert resolve_action('carregue essa musica', mp3) == ('open_search_result', 1)
assert resolve_action('carregue esse documento', pdf) is None
assert resolve_action('abra esse arquivo', multi) is None
assert resolve_action('abra o segundo', multi) == ('open_search_result', 2)
assert resolve_action('nao abra o arquivo', pdf) is None
assert resolve_action('procure e abra o arquivo', pdf) is None
assert resolve_action('carregue o modelo', mp3) is None
assert search_feedback({'results': []}).startswith('Não encontrei')
assert 'um arquivo' in search_feedback({'results': [{'path': pdf[0], 'spoken_name': 'meu PDF'}]})
assert 'primeiro' in search_feedback({'results': [{'path': x} for x in multi]})
assert 'digitar' in voice_first_system()
print('Etapa 9: testes de conversacao e selecao OK')
