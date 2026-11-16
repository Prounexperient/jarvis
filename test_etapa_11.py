from speech_text_processor import SpeechTextProcessor
from capability_reasoner import capability_context
from tools import SCHEMAS

p = SpeechTextProcessor(mode='sentence')
chunks = ['| Nome | Função |\n|------|--------|\n| read_document | Lê documentos. |\n', 'Posso analisar código Python. ']
spoken = []
for chunk in chunks:
    spoken.extend(p.feed(chunk))
spoken.extend(p.feed('', final=True))
assert spoken == ['read_document: Lê documentos.', 'Posso analisar código Python.'], spoken
config = {'paths': {'allowed_roots': []}, 'security': {'confirm_writes': True}}
ctx = capability_context(config, SCHEMAS)
assert 'ler arquivos de texto e código' in ctx
assert 'executar scripts Python diretamente' in ctx
print('PASSOU: Etapa 11 - tabela para fala, streaming e raciocínio de capacidades')
