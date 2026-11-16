from pathlib import Path
from tempfile import TemporaryDirectory
from document_inspector import inspect
from tools import inspect_document, run_tool

with TemporaryDirectory() as tmp:
    root=Path(tmp)
    p=root/'amostra.txt'
    p.write_text('Primeira linha\nCodigo 493821\nTerceira linha\n',encoding='utf-8')
    config={'paths':{'allowed_roots':[str(root)]},'document_reading':{'max_chars':12000,'max_pages':12,'max_file_mb':20}}
    a=inspect_document(str(p),'lines',config,count=3)
    assert [v['text'] for v in a['lines']]==['Primeira linha','Codigo 493821','Terceira linha'],a
    b=inspect_document(str(p),'find',config,query='493821')
    assert b['matches'][0]['line']==2,b
    c=run_tool('inspect_document',{'path':str(p),'operation':'images'},config)
    assert 'note' in c,c
    d=run_tool('inspect_document',{'path':str(root.parent/'nao_autorizado.txt'),'operation':'lines'},config)
    assert 'error' in d,d
    e=run_tool('inspect_document',{'path':str(p),'operation':'lines','count':31},config)
    assert 'error' in e,e
print('Etapa 8: testes de inspecao documental OK')
