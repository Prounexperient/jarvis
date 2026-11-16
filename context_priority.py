"""Orientação contextual não destrutiva, derivada das mensagens do usuário.

A ordem cronológica e os ciclos de ferramentas permanecem intactos.
"""
import re

REFERENCE = re.compile(r'\b(continu\w*|retom\w*|anterior\w*|aquele\w*|aquela\w*|aquilo|mesmo|mesma|isso|esse|essa|esses|essas|dele|dela|corrij\w*|onde parou)\b', re.I)


def context_priority_instruction(history):
    """Cria orientação curta; não reordena, exclui nem resume mensagens."""
    users = [m.get('content', '') for m in history if m.get('role') == 'user' and isinstance(m.get('content'), str)]
    if not users:
        return ''
    current = users[-1]
    referring = bool(REFERENCE.search(current))
    return (
        '\nORIENTAÇÃO DE CONTINUIDADE CONVERSACIONAL:\n'
        '- A ÚLTIMA mensagem do usuário é a solicitação vigente; interprete-a primeiro.\n'
        '- Mensagens anteriores são contexto e referências, não ordens pendentes para executar.\n'
        '- Se a solicitação atual retomar ou corrigir algo anterior, recupere os detalhes necessários '
        'no histórico cronológico, sem mudar de assunto.\n'
        '- Uma confirmação breve pode autorizar apenas a operação pendente explicitamente identificada; '
        'não autoriza tarefas antigas desconexas.\n'
        '- Resultados de ferramentas só comprovam o que a ferramenta efetivamente confirmou.\n'
        '- Não repita respostas antigas nem execute ferramentas motivadas apenas por pedidos anteriores.\n'
        + ('- A mensagem atual contém referência contextual: procure o antecedente relacionado antes de agir.\n'
           if referring else '')
    )
