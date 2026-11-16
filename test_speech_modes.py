from speech_text_processor import SpeechTextProcessor

sample = 'Embora o projeto seja complexo e exija atenção, podemos testá-lo cuidadosamente. Depois verificaremos o resultado.'
for mode in ('sentence', 'full'):
    processor = SpeechTextProcessor(mode=mode, safety_limit=650)
    chunks = [sample[:43], sample[43:87], sample[87:]]
    output = []
    for chunk in chunks:
        output += processor.feed(chunk)
    output += processor.feed('', final=True)
    print(mode, repr(output))
    assert len(output) == (2 if mode == 'sentence' else 1)
    assert ' '.join(output) == sample

# Não pode cortar uma frase comum apenas por passar de 220 caracteres.
long_sentence = 'A ' + 'palavra ' * 38 + 'termina.'
p = SpeechTextProcessor(mode='sentence', safety_limit=650)
assert p.feed(long_sentence + ' ') == [long_sentence]
assert p.feed('', final=True) == []

# Não pode cortar palavras quando o LLM envia tokens pequenos.
p = SpeechTextProcessor(mode='sentence')
assert p.feed('compre') == []
assert p.feed('ensão. ') == ['compreensão.']
print('Testes de segmentação: OK')
