"""Etapa 13.2: dois canais com verificação conservadora de restrições operacionais.

Não é um verificador geral de equivalência semântica. Em caso de dúvida,
usa-se o texto visual original como fonte da fala.
"""
import re
import json
import unicodedata

_BLOCK = re.compile(r'\A\s*<texto>\s*(.*?)\s*</texto>\s*<fala>\s*(.*?)\s*</fala>\s*\Z', re.S | re.I)
_NUMBER = re.compile(r'(?<!\w)\d+(?:[.,]\d+)*(?!\w)')

_ACTIONS = {
    'execute_code': r'\b(?:execut\w*|rod\w*|cham\w*\s+(?:o\s+)?interpretador\w*|inici\w*\s+(?:o\s+)?script\w*)\b',
    'edit': r'\b(?:edit\w*|modific\w*|alter\w*|substitu\w*)\b',
    'delete': r'\b(?:apag\w*|exclu\w*|delet\w*|remov\w*)\b',
    'write': r'\b(?:salv\w*|grav\w*|escrev\w*|cri\w*\s+(?:um\s+)?arquiv\w*)\b',
    'open': r'\b(?:abr\w*|inici\w*\s+(?:um\s+)?aplicativ\w*)\b',
    'access': r'\b(?:acess\w*|consult\w*|ler\b|leitur\w*)\b',
}
_ACTION_PATTERNS = {k: re.compile(v) for k, v in _ACTIONS.items()}
_DENIAL = re.compile(r'\b(?:nao|nunca|jamais|sem|impossivel|indisponivel|incapaz|proibid\w*|bloquead\w*)\b')
_CONDITION = re.compile(r'\b(?:confirm\w*|autoriz\w*|aprov\w*|permiss\w*|consent\w*)\b')
_OBLIGATION = re.compile(r'\b(?:com\s+(?:sua\s+)?(?:autorizacao|aprovacao|permissao|consentimento)|precis\w*|necessari\w*|exig\w*|requer\w*|depend\w*|somente\s+com|so\s+com|apos|mediante|antes\s+d[aeo])\b')


def _normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


def _clauses(text):
    # Divide períodos e orações coordenadas; não divide por "nem", que preserva
    # a negação compartilhada: "não posso editar nem executar".
    return [c.strip() for c in re.split(r'[.;!?\n]+|\s*,?\s+(?=(?:mas|porem|entretanto)\b)', _normalize(text)) if c.strip()]


def _constraints(text):
    """Extrai categorias de negação e condições explícitas; não conta frases."""
    denied, conditional = set(), set()
    for clause in _clauses(text):
        actions = {key for key, pat in _ACTION_PATTERNS.items() if pat.search(clause)}
        if not actions:
            continue
        # Escopo limitado à oração: "não ... executar e editar" cobre ambas.
        if _DENIAL.search(clause):
            denied.update(actions)
        if _CONDITION.search(clause) and _OBLIGATION.search(clause):
            conditional.update(actions)
    return denied, conditional


def fidelity_reason(visual, spoken):
    """Heurística operacional, não certificação de equivalência semântica."""
    if not spoken or len(spoken.strip()) < 8:
        return 'fala_vazia_ou_curta'
    if set(_NUMBER.findall(visual)) - set(_NUMBER.findall(spoken)):
        return 'numeros_omitidos'
    v_denied, v_conditional = _constraints(visual)
    s_denied, s_conditional = _constraints(spoken)
    if v_denied - s_denied:
        return 'restricao_omitida:' + ','.join(sorted(v_denied - s_denied))
    if v_conditional - s_conditional:
        return 'condicao_omitida:' + ','.join(sorted(v_conditional - s_conditional))
    # Não permitir negações operacionais inventadas pela fala.
    if s_denied - v_denied:
        return 'restricao_acrescentada:' + ','.join(sorted(s_denied - v_denied))
    return None


def fidelity_ok(visual, spoken):
    return fidelity_reason(visual, spoken) is None


def split_response_diagnostic(raw):
    """Retorna (texto, fala, validado, motivo), sem imprimir dados do usuário."""
    raw = (raw or '').strip()
    match = _BLOCK.fullmatch(raw)
    if not match:
        reason = 'formato_ausente' if '<texto>' not in raw.lower() and '<fala>' not in raw.lower() else 'formato_invalido'
        return raw, raw, False, reason
    visual, spoken = (part.strip() for part in match.groups())
    if not visual:
        return raw, raw, False, 'texto_vazio'
    reason = fidelity_reason(visual, spoken)
    if reason:
        return visual, visual, False, reason
    return visual, spoken, True, 'ok'


def split_response(raw):
    visual, spoken, valid, _ = split_response_diagnostic(raw)
    return visual, spoken, valid



# Contrato opcional 13.3: fatos rastreáveis por evidência textual em ambos os canais.
# Isto NÃO prova equivalência semântica; detecta omissões explícitas e falhas de formato.
_STRUCTURED = re.compile(
    r'\A\s*<texto>\s*(.*?)\s*</texto>\s*<fatos>\s*(.*?)\s*</fatos>\s*<fala>\s*(.*?)\s*</fala>\s*\Z',
    re.S | re.I,
)
_ALLOWED_KINDS = {'capacidade', 'limitacao', 'condicao', 'resultado', 'informacao'}


def _fact_diagnostic(visual, raw_facts, spoken):
    try:
        facts = json.loads(raw_facts)
    except (ValueError, TypeError):
        return 'fatos_json_invalido'
    if not isinstance(facts, list) or not (1 <= len(facts) <= 24):
        return 'fatos_lista_invalida'
    if not spoken or len(spoken.strip()) < 8:
        return 'fala_vazia_ou_curta'
    if set(_NUMBER.findall(visual)) - set(_NUMBER.findall(spoken)):
        return 'numeros_omitidos'
    used = set()
    for item in facts:
        if not isinstance(item, dict) or set(item) != {'id', 'tipo', 'evidencia_texto', 'evidencia_fala'}:
            return 'fato_campos_invalidos'
        fid, kind = item['id'], item['tipo']
        a, b = item['evidencia_texto'], item['evidencia_fala']
        if not isinstance(fid, str) or not re.fullmatch(r'[a-z][a-z0-9_]{1,49}', fid) or fid in used:
            return 'fato_id_invalido'
        used.add(fid)
        if kind not in _ALLOWED_KINDS or not isinstance(a, str) or not isinstance(b, str):
            return 'fato_tipo_invalido'
        if len(a.strip()) < 5 or len(b.strip()) < 5:
            return 'fato_evidencia_curta'
        if _normalize(a) not in _normalize(visual) or _normalize(b) not in _normalize(spoken):
            return 'fato_evidencia_ausente:' + fid
        # A negação explícita em uma evidência de limitação deve persistir.
        if kind == 'limitacao' and _DENIAL.search(_normalize(a)) and not _DENIAL.search(_normalize(b)):
            return 'fato_negacao_omitida:' + fid
        if kind == 'condicao' and _CONDITION.search(_normalize(a)) and not _CONDITION.search(_normalize(b)):
            return 'fato_condicao_omitida:' + fid
    # A lista é produzida pelo LLM: não confiar nela como prova de cobertura.
    # Para evitar a falha conhecida por contagem de orações, conferir somente
    # se existe evidência para cada cláusula explicitamente restritiva.
    critical = [c for c in _clauses(visual) if _DENIAL.search(c) and any(p.search(c) for p in _ACTION_PATTERNS.values())]
    if critical and not any(f['tipo'] == 'limitacao' for f in facts):
        return 'fatos_sem_limitacoes'
    return None


def structured_response_diagnostic(raw):
    """(visual, fala, valido, motivo), aceitando também contrato legado."""
    raw = (raw or '').strip()
    match = _STRUCTURED.fullmatch(raw)
    if match:
        visual, raw_facts, spoken = (part.strip() for part in match.groups())
        if not visual:
            return raw, raw, False, 'texto_vazio'
        reason = _fact_diagnostic(visual, raw_facts, spoken)
        return (visual, spoken, True, 'ok_estruturado') if reason is None else (visual, visual, False, reason)
    return split_response_diagnostic(raw)

def dual_channel_instruction():
    return (
        'PARA RESPOSTAS FINAIS, não chamadas de ferramentas, use preferencialmente '
        '<texto>resposta técnica</texto><fatos>[{"id":"limite_execucao",'
        '"tipo":"limitacao","evidencia_texto":"trecho LITERAL da resposta técnica",'
        '"evidencia_fala":"trecho LITERAL da resposta falada"}]</fatos>'
        '<fala>resposta natural para voz</fala>. '
        'Fatos: lista JSON de 1 a 24 itens com IDs únicos, tipo capacidade, limitacao, '
        'condicao, resultado ou informacao. Cada evidência deve ser um trecho EXATO '
        'que aparece no respectivo canal; não use paráfrases nas evidências. '
        'Inclua fatos para todas as capacidades, limitações e condições importantes. '
        'Não invente permissões, proibições, resultados ou ferramentas. '
        'Não confunda abrir aplicativos autorizados com executar código arbitrário. '
        'Em fala, preserve todas as limitações e autorizações, mas fale naturalmente, '
        'sem caminhos completos nem nomes internos de funções salvo pedido explícito. '
        'Se não conseguir montar fatos válidos, use o contrato legado '
        '<texto>resposta técnica</texto><fala>resposta natural</fala>. '
        'Não escreva texto fora das tags. Só formate a resposta FINAL.'
    )


def repair_instruction():
    return (
        'REFORMATAÇÃO DA ÚLTIMA RESPOSTA: devolva exatamente '
        '<texto>...</texto><fala>...</fala>. '
        'Copie o conteúdo de <texto> da resposta anterior SEM MUDAR UM CARACTERE; '
        'se a resposta anterior não tinha tags, copie a resposta integral para <texto>. '
        'Na fala explique esses mesmos fatos de modo natural, sem nomes internos de funções. '
        'Preserve TODAS as restrições e exigências de autorização mesmo quando condensar frases. '
        'Não execute ferramentas, não acrescente fatos nem proibições. '
        'Não escreva nada fora das duas tags.'
    )
