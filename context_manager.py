"""Etapa 14.1.5: orçamento aproximado, sem armazenamento persistente."""
import json
import re


def estimate_tokens(message):
    # Estimativa conservadora; não substitui o tokenizer do modelo.
    raw = json.dumps(message, ensure_ascii=False, default=str)
    return max(1, (len(raw) + 2) // 3)


def budget_messages(history, context_length=8192, response_tokens=900, reserve=600):
    """Preserva as falas e o ciclo ativo; comprime ciclos técnicos antigos.

    Não modifica o histórico original: prepara somente a requisição ao modelo.
    """
    available = max(512, int(context_length) - int(response_tokens) - int(reserve))
    result = [dict(m) for m in history]
    def total():
        return sum(estimate_tokens(m) for m in result)
    if total() <= available:
        return result
    # Substitui resultados extensos de ferramentas antigas por um marcador,
    # sem remover o resultado de ferramenta mais recente da tarefa atual.
    last_user = max((i for i, m in enumerate(result) if m.get('role') == 'user'), default=0)
    for i, m in enumerate(result):
        if i >= last_user or total() <= available:
            break
        if m.get('role') == 'tool' and len(str(m.get('content', ''))) > 200:
            m['content'] = '{"notice":"Resultado técnico antigo omitido do contexto; não utilize como evidência atual."}'
    if total() <= available:
        return result
    # Remove ciclos técnicos completos anteriores ao pedido atual, mantendo
    # mensagens de usuário e respostas conversacionais sem chamadas.
    i = 1
    while i < len(result) and total() > available:
        m = result[i]
        calls = m.get('tool_calls') or []
        if i < last_user and m.get('role') == 'assistant' and calls:
            ids = [c.get('id') for c in calls]
            following = result[i+1:i+1+len(ids)]
            if len(following) == len(ids) and [x.get('tool_call_id') for x in following] == ids:
                del result[i:i+1+len(ids)]
                last_user -= 1 + len(ids)
                continue
        i += 1
    # Último recurso: remove turnos conversacionais mais antigos em fronteiras
    # de usuário; nunca remove a solicitação atual nem o system.
    while total() > available:
        users = [i for i, m in enumerate(result) if m.get('role') == 'user']
        if len(users) < 2:
            break
        del result[users[0]:users[1]]
    return result
