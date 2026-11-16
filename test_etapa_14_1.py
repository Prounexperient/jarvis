"""Testes offline do portão de intenção; não necessita LM Studio."""
from intent_router import route_intent

CONVERSATION = [
    'Me explique suas limitações técnicas e se consegue abrir arquivos Python.',
    'Você consegue abrir, ler e modificar arquivos Python?',
    'O que você acha da linguagem Python?',
    'Como posso modificar um arquivo Python?',
    'Estou pensando em reorganizar meus arquivos Python.',
    'Se eu pedir para abrir um arquivo, o que acontece?',
    'Não abra o arquivo projeto.py.',
    'O que você acha do código que acabamos de ler?',
    'Você sabe executar scripts Python?',
    'Me ensine a criar um documento Word.',
    'O que é a Odisseia de Homero?',
]
ACTION = [
    'Jarvis, abra o arquivo projeto.py.',
    'Leia o arquivo projeto.py.',
    'Modifique a função calcular no arquivo projeto.py.',
    'Pesquise arquivos Python na pasta do projeto.',
    'Examine a pasta do projeto e me diga quais módulos estão grandes.',
    'Abra o primeiro resultado.',
    'Crie um documento Word.',
    'Pode abrir o arquivo projeto.py?',
    'Calcule 17 * 35.',
]
for text in CONVERSATION:
    assert route_intent(text) == 'conversation', ('conversa', text, route_intent(text))
for text in ACTION:
    assert route_intent(text) == 'action', ('ação', text, route_intent(text))
print('PASSOU: Etapa 14.1 -', len(CONVERSATION), 'conversas e', len(ACTION), 'solicitações explícitas')
