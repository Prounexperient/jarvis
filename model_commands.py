"""Comandos administrativos locais, sem LLM, rede ou acesso ao microfone.

Somente frases completas são aceitas; menções casuais aos modelos não
acionam trocas. A saída é uma ação sem efeitos colaterais.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class ModelCommand:
    action: str  # switch | status
    target: str | None = None


def normalize_command(text: str) -> str:
    text = unicodedata.normalize('NFKD', text.casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', text)).strip()


# Formas sem nomes estrangeiros são preferidas para reconhecimento de voz.
_SWITCH = {
    'gpt_oss': (
        'ative o modelo avancado', 'ativar modelo avancado',
        'mude para o modelo avancado', 'troque para o modelo avancado', 'troca de modelo avancado', 'troque o modelo para avancado',
        'utilize o modelo avancado', 'use o modelo avancado',
        'ative o gpt oss', 'utilize o gpt oss', 'use o gpt oss',
        'mude para o gpt oss', 'troque para o gpt oss',
        'ative o gpt', 'utilize o gpt', 'use o gpt',
    ),
    'qwen': (
        'volte ao modelo padrao', 'voltar ao modelo padrao',
        'ative o modelo padrao', 'utilize o modelo padrao',
        'use o modelo padrao', 'mude para o modelo padrao',
        'troca de modelo padrao', 'troque o modelo para padrao',
        'eu quero que troque o modelo para padrao', 'troque para o modelo padrao',
        'ative o qwen', 'utilize o qwen', 'use o qwen',
        'mude para o qwen', 'troque para o qwen',
    ),
}
_STATUS = ('qual modelo esta ativo', 'qual e o modelo ativo',
           'qual modelo voce esta usando', 'informe o modelo ativo')


def parse_model_command(text: str, wake: str = 'jarvis') -> ModelCommand | None:
    phrase = normalize_command(text)
    wake = normalize_command(wake)
    if wake and phrase.startswith(wake + ' '):
        phrase = phrase[len(wake) + 1:]
    if phrase in _STATUS:
        return ModelCommand('status')
    for target, phrases in _SWITCH.items():
        if phrase in phrases:
            return ModelCommand('switch', target)
    # Comandos de teclado/texto, sem inferência semântica.
    match = re.fullmatch(r'/modelo\s+(qwen|gpt|gpt_oss|status)', text.strip().casefold())
    if match:
        value = match.group(1)
        return ModelCommand('status') if value == 'status' else ModelCommand('switch', 'gpt_oss' if value in ('gpt', 'gpt_oss') else 'qwen')
    return None


def execute_model_command(command: ModelCommand, agent, announce=None) -> str:
    """Executar SOMENTE entre turnos. Falha segura sem alterar a seleção.

    announce(text) é opcional e só usado para informar antes de uma troca real.
    """
    manager = agent.model_manager
    if manager is None:
        return 'O gerenciamento de modelos está desativado.'
    names = {'qwen': 'Qwen', 'gpt_oss': 'GPT-OSS'}
    if command.action == 'status':
        current = agent.active_model_name
        return f'O modelo selecionado é {names.get(current, current)}.'
    if command.action != 'switch' or command.target not in manager.models:
        return 'Comando de modelo inválido.'
    target = command.target
    if target == agent.active_model_name:
        # Se descarregado externamente, o próximo turno fará a carga normal.
        return f'O modelo {names.get(target, target)} já está selecionado.'
    if announce:
        announce(f'Vou ativar o modelo {names.get(target, target)}. Aguarde um instante.')
    try:
        manager.ensure_loaded(target)
    except Exception as exc:
        # Nunca marcar como ativo um modelo cuja carga não foi confirmada.
        return f'Não consegui concluir a troca de modelo. {type(exc).__name__}: {exc}'
    agent.active_model_name = target
    return f'Modelo {names.get(target, target)} ativado e pronto para conversar.'
