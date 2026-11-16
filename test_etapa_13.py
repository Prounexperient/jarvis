from dual_channel import split_response, fidelity_ok, dual_channel_instruction
from capability_reasoner import capability_context
from tools import SCHEMAS

visual = 'Posso analisar código Python. Não posso executar scripts Python diretamente.'
spoken = 'Consigo analisar seu código Python, mas não posso executar os scripts no computador.'
assert split_response(f'<texto>{visual}</texto><fala>{spoken}</fala>') == (visual, spoken, True)
assert split_response(f'<texto>{visual}</texto><fala>Consigo analisar e executar tudo.</fala>') == (visual, visual, False)
assert split_response('Resposta antiga.') == ('Resposta antiga.', 'Resposta antiga.', False)
assert not fidelity_ok('São 12 arquivos.', 'São 10 arquivos.')
assert not fidelity_ok('Não posso editar. Não posso executar.', 'Não posso editar.')
assert 'chamadas de ferramentas' in dual_channel_instruction().lower()
ctx = capability_context({'paths': {'allowed_roots': []}, 'security': {'confirm_writes': True}}, SCHEMAS)
assert 'SOMENTE as tarefas pertinentes' in ctx
print('PASSOU: Etapa 13 - dual channel, fidelidade e relevância contextual')
