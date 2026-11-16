from dual_channel import structured_response_diagnostic
import json

def pack(visual, spoken, facts):
    return '<texto>'+visual+'</texto><fatos>'+json.dumps(facts, ensure_ascii=False)+'</fatos><fala>'+spoken+'</fala>'

v = 'Consigo ler scripts Python. Não posso executar scripts Python diretamente.'
s = 'Posso ler seus scripts Python, mas não consigo executar scripts Python diretamente.'
f = [
 {'id':'leitura','tipo':'capacidade','evidencia_texto':'Consigo ler scripts Python','evidencia_fala':'Posso ler seus scripts Python'},
 {'id':'execucao','tipo':'limitacao','evidencia_texto':'Não posso executar scripts Python diretamente','evidencia_fala':'não consigo executar scripts Python diretamente'},
]
assert structured_response_diagnostic(pack(v,s,f)) == (v,s,True,'ok_estruturado')
f[1]['evidencia_fala'] = 'posso executar scripts'
assert structured_response_diagnostic(pack(v,s,f))[3].startswith('fato_evidencia_ausente')
assert structured_response_diagnostic('<texto>Não posso executar.</texto><fala>Não consigo executar.</fala>')[2]
assert structured_response_diagnostic('resposta sem tags')[3] == 'formato_ausente'
print('PASSOU: Etapa 13.3 - contrato, evidências, compatibilidade e fallback')
