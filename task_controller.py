"""Autorização por turno e confirmação contextual estritamente vinculada.

Não substitui a confirmação humana da camada de ferramentas nem as raízes permitidas.
"""
import json
import re
import unicodedata
from action_policy import ActionPolicy, WRITE_TOOLS


def normalize(value):
    value = unicodedata.normalize('NFKD', str(value).casefold())
    return ''.join(c for c in value if not unicodedata.combining(c))


READ_WORDS = re.compile(r'\b(ler|leia|leitura|carreg\w*|resum\w*|analis\w*|explic\w*|traduz\w*|inspecion\w*|conteudo|pagina|linha|texto|verifi\w*|mostr\w*)\b')
WRITE_WORDS = re.compile(r'\b(cri\w*|faz\w*|fac\w*|ger\w*|salv\w*|grav\w*|escrev\w*|edit\w*|alter\w*|modific\w*|corrig\w*|corrij\w*|correc\w*|consert\w*|acrescent\w*|adicion\w*|inclu\w*|implement\w*|refator\w*|ajust\w*|substitu\w*|remov\w*|exclu\w*|apag\w*|aplic\w*|atualiz\w*)\b')
EDIT_WORDS = re.compile(r'\b(edit\w*|alter\w*|modific\w*|corrig\w*|corrij\w*|correc\w*|consert\w*|acrescent\w*|adicion\w*|inclu\w*|implement\w*|refator\w*|ajust\w*|aplic\w*|atualiz\w*)\b')
DENIAL = re.compile(r'^\s*(?:nao|nunca|cancele|cancelar|desista|pare|interrompa)(?:[\s!.]+(?:isso|essa tarefa|a tarefa|a operacao|o projeto))?[\s!.]*$')
AFFIRMATION = re.compile(r'^\s*(?:sim|pode|autorizo|confirmo|prossiga|continue|pode prosseguir|sim pode|sim pode prosseguir|sim pode aplicar|sim pode editar)(?:[\s,!.]+(?:aplicar|editar|os ajustes|as edicoes|as alteracoes|as correcoes|tudo|isso|pode|prosseguir|continuar))*[\s,!.]*$')
CONFIRM_REQUEST = re.compile(r'\b(confirm\w*|autoriz\w*|permiss\w*|diga sim|preciso de sua confirmacao)\b')


def pending_authorization(history):
    """Confirma somente pedido imediatamente anterior, se houve solicitação de confirmação.

    A intenção é derivada de falas originais; não se cria autorização persistente.
    """
    turns = [m for m in history if m.get('role') in ('user', 'assistant') and isinstance(m.get('content'), str) and m['content'].strip()]
    if len(turns) < 2 or turns[-1]['role'] != 'assistant' or turns[-2]['role'] != 'user':
        return None
    request = turns[-2]['content']
    reply = turns[-1]['content']
    if WRITE_WORDS.search(normalize(request)) and CONFIRM_REQUEST.search(normalize(reply)):
        return request
    return None


class TaskController:
    def __init__(self, user_request, previous_history=None, navigation=None):
        self.user_request = user_request
        self.policy = ActionPolicy(navigation)
        self.last_signature = None
        self.repetitions = 0
        self.executed = set()
        normalized = normalize(user_request)
        self.confirmed_request = None
        if AFFIRMATION.fullmatch(normalized) and previous_history:
            self.confirmed_request = pending_authorization(previous_history)
        self.write_authorized = bool(WRITE_WORDS.search(normalized) or self.confirmed_request) and not (DENIAL.fullmatch(normalized) or self.policy.resolver.resolve(user_request).negative_command)
        self.edit_requested = bool(EDIT_WORDS.search(normalized) or self.confirmed_request)

    def inspect(self, name, args, *, verified_origin=None):
        signature = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
        if signature == self.last_signature:
            self.repetitions += 1
        else:
            self.repetitions = 0
        self.last_signature = signature
        if self.repetitions >= 2:
            return 'Ferramenta repetida sem progresso. Conclua com o que sabe ou solicite esclarecimento.'
        # Operações não destrutivas são autorizadas pelo escopo do projeto e pelas ferramentas.
        # Nunca usar palavras-chave do turno para revogar uma tarefa em andamento.
        return self.policy.deny_reason(
            name, args, self.user_request,
            edit_requested=self.edit_requested,
            write_authorized=self.write_authorized,
            confirmed_request=self.confirmed_request,
            verified_origin=verified_origin,
        )
