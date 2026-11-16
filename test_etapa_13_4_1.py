"""Testes offline da etapa 13.4.1."""
from types import SimpleNamespace
from speech_semantic import SpeechSemanticRealizer

TECH = ('Posso localizar, abrir e ler arquivos Python nas pastas autorizadas. '
        'Posso editar trechos com confirmação e backup. '
        'Não posso executar scripts Python diretamente. '
        'Posso abrir aplicativos autorizados como VS Code.')
GOOD = ('Posso abrir, ler e modificar arquivos Python nas pastas autorizadas. '
        'Para editar, preciso da sua confirmação e faço um backup. '
        'Não posso executar scripts Python diretamente, mas posso abrir aplicativos autorizados.')

class Client:
    def __init__(self, answer):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])))

config = {'conversation': {'speech_semantic_max_chars': 650}}
assert SpeechSemanticRealizer(Client(GOOD), config).realize(TECH, 'gpt-oss', 'Pode editar Python?') == GOOD
for bad, reason in [
    ('Posso abrir e ler arquivos Python nas pastas autorizadas. Não posso executar scripts Python diretamente.', 'confirmacao_omitida'),
    ('Posso editar com confirmação nas pastas autorizadas. Não posso executar scripts Python diretamente.', 'backup_omitido'),
    ('Posso editar com confirmação e backup. Não posso executar scripts Python diretamente.', 'acesso_omitido'),
    ('Posso editar com confirmação e backup nas pastas autorizadas.', 'execucao_omitida'),
    ('Não posso abrir programas. Posso editar com confirmação e backup nas pastas autorizadas. Não posso executar scripts Python diretamente.', 'contradicao_aplicativos'),
]:
    ok, why = SpeechSemanticRealizer._safe(TECH, bad)
    assert not ok and why == reason, (why, reason)
print('PASSOU: Etapa 13.4.1 - concisão e restrições')
