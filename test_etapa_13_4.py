"""Testes offline da camada de fala; não requer LM Studio nem openai."""
from types import SimpleNamespace
from speech_semantic import SpeechSemanticRealizer

TECH = ('Sim, posso abrir, ler e modificar arquivos Python nas pastas autorizadas. '
        'Para editar, preciso de confirmação. Não posso executar scripts Python.')
GOOD = ('Consigo abrir, ler e modificar arquivos Python nas pastas autorizadas. '
        'Para editar, preciso de confirmação, mas não posso executar scripts Python.')

class FakeClient:
    def __init__(self, content=None, error=None):
        self.content, self.error, self.calls = content, error, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])

client = FakeClient(GOOD)
realizer = SpeechSemanticRealizer(client, {'conversation': {}})
assert realizer.realize(TECH, 'gpt-oss', question='O que consegue fazer?') == GOOD
assert client.calls[0]['tool_choice'] == 'none'
assert client.calls[0]['stream'] is False
assert len(client.calls[0]['messages']) == 2
assert all(m['role'] != 'tool' for m in client.calls[0]['messages'])
assert 'O que consegue fazer?' in client.calls[0]['messages'][1]['content']

for bad in ('', '<fala>texto</fala>', 'Posso fazer tudo.', 'Posso abrir 9000 arquivos.', '```python\nprint(1)\n```'):
    client = FakeClient(bad)
    assert SpeechSemanticRealizer(client, {}).realize(TECH, 'gpt-oss') == TECH, bad

client = FakeClient(error=RuntimeError('LM Studio indisponível'))
assert SpeechSemanticRealizer(client, {}).realize(TECH, 'gpt-oss') == TECH
assert SpeechSemanticRealizer(FakeClient(GOOD), {}).realize('Oi.', 'gpt-oss') == 'Oi.'
print('PASSOU: Etapa 13.4 - isolamento, validações e fallback')
