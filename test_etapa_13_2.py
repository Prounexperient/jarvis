from dual_channel import fidelity_reason, fidelity_ok, split_response_diagnostic

v = 'Não posso executar scripts Python. Não posso chamar interpretadores Python diretamente.'
s = 'Ainda não consigo executar scripts Python diretamente, nem chamar um interpretador para isso.'
assert fidelity_ok(v, s), fidelity_reason(v, s)
assert fidelity_reason('Não posso editar. Não posso executar.', 'Não posso editar.') == 'restricao_omitida:execute_code'
assert fidelity_reason('Não posso executar.', 'Não posso editar.') is not None
assert fidelity_reason('Posso editar mediante sua autorização.', 'Posso editar sem pedir nada.') is not None
assert fidelity_reason('Posso editar mediante sua autorização.', 'Posso editar.') == 'condicao_omitida:edit'
assert fidelity_ok('Posso editar após sua aprovação.', 'Posso modificar com sua autorização.')
assert not fidelity_ok('Encontrei 12 arquivos.', 'Encontrei 10 arquivos.')
assert split_response_diagnostic('<texto>Não posso executar scripts.</texto><fala>Não consigo executar scripts.</fala>')[2]
assert split_response_diagnostic('texto sem tags')[3] == 'formato_ausente'
print('PASSOU: Etapa 13.2 - categorias, fusão de frases, condições e fallback')
