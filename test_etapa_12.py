from speech_realization import SpeechRealizationLayer
from capability_reasoner import capability_matrix, capability_context
from tools import SCHEMAS

config = {'paths': {'allowed_roots': []}, 'security': {'confirm_writes': True}}
m = capability_matrix(config, SCHEMAS)
assert m['can_analyze_code']
assert not m['can_execute_python']
assert m['writes_require_confirmation']
assert 'Não disponíveis' in capability_context(config, SCHEMAS)

p = SpeechRealizationLayer()
source = 'Posso ler com `read_document` e editar com `replace_in_text_file`. Não posso executar scripts Python diretamente. '
chunks = [source[:31], source[31:58], source[58:92], source[92:]]
output = []
for chunk in chunks:
    output.extend(p.feed(chunk))
output.extend(p.feed('', final=True))
joined = ' '.join(output)
assert 'leitura de documentos' in joined, output
assert 'edição de trechos de arquivos' in joined, output
assert 'Não posso executar scripts Python diretamente' in joined, output
assert 'read_document' not in joined, output

p = SpeechRealizationLayer()
output = p.feed('| Nome | Função |\n|------|--------|\n| read_document | Lê documentos. |\n', final=True)
assert not any('------' in x or '|' in x for x in output), output
assert any('leitura de documentos' in x for x in output), output

p = SpeechRealizationLayer()
output = p.feed('O caminho C:\\Users\\rodco\\Documents está autorizado. ', final=True)
assert 'rodco' not in ' '.join(output), output
assert 'autorizado' in ' '.join(output), output

p = SpeechRealizationLayer()
output = p.feed('```python\nprint("segredo")\n```\nA análise foi concluída.\n', final=True)
assert 'segredo' not in ' '.join(output), output
assert 'análise foi concluída' in ' '.join(output), output
print('PASSOU: Etapa 12 - capacidades, fidelidade, streaming e voz')
