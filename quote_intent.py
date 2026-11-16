"""Compatibilidade de roteamento de citações, delegado ao IntentResolver."""

def is_general_quotation_request(text):
    """Compatibilidade: delega à interpretação centralizada do turno."""
    from intent_resolver import IntentResolver
    return IntentResolver().resolve(text).general_quotation


GENERAL_QUOTE_INSTRUCTION = (
    'O usuario pediu um trecho de uma obra como conhecimento geral, sem pedir acesso ao PC. '
    'Responda diretamente com conhecimento do modelo; nao busque arquivos, pastas, '
    'PDFs ou recursos locais. Nao alegue que nao encontrou arquivo no computador. '
    'Nao invente uma citacao literal: se nao puder confirmar as palavras exatas '
    'ou a traducao/edicao, declare a incerteza e ofereca uma parafrase identificada. '
    'Se houver referencia explicita a arquivo no computador, esta regra nao se aplica.'
)
