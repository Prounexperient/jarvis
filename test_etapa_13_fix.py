from dual_channel import split_response_diagnostic, split_response, fidelity_ok

v = 'Posso analisar código Python. Não posso executar scripts Python diretamente.'
f = 'Consigo analisar seu código Python, mas não posso executar os scripts no computador.'
assert split_response(f'<texto>{v}</texto><fala>{f}</fala>') == (v, f, True)
assert split_response_diagnostic(v)[-1] == 'formato_ausente'
assert split_response_diagnostic('<texto>ok</texto>')[-1] == 'formato_invalido'
assert split_response_diagnostic(f'<texto>{v}</texto><fala>Posso fazer tudo.</fala>')[-1] .startswith('restricao_omitida')
assert not fidelity_ok('São 12 arquivos.', 'São 10 arquivos.')
assert not fidelity_ok('Não posso editar. Não posso executar.', 'Não posso editar.')
print('PASSOU: diagnóstico e contrato Etapa 13.1')
