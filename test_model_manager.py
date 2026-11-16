"""Teste manual e interativo; não usa Kokoro nem altera o agent.py.

Execute em um terminal do Windows com o LM Studio aberto:
    python test_model_manager.py

ATENÇÃO: descarrega os modelos gerenciados listados no script.
"""
import logging
from model_manager import ModelManager, ModelManagerError


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    manager = ModelManager(timeout_seconds=180)
    print('\nModelos configurados:', ', '.join(manager.models))
    print('Carregados agora:', sorted(manager.loaded()))
    answer = input('\nEste teste pode descarregar Qwen/GPT-OSS. Continuar? [s/N] ').strip().lower()
    if answer not in {'s', 'sim'}:
        print('Cancelado.')
        return
    for name in ('qwen', 'gpt_oss', 'qwen'):
        input(f'\nPressione ENTER para ativar {name}...')
        identifier = manager.ensure_loaded(name)
        print('ATIVO:', identifier)
        print('CONFIRMADO:', sorted(manager.loaded()))
        input('Confira RAM/VRAM com nvidia-smi e Gerenciador de Tarefas; ENTER para continuar...')
    print('\nTeste concluído. O último modelo continua carregado.')


if __name__ == '__main__':
    try:
        main()
    except ModelManagerError as exc:
        print('\n[ERRO SEGURO]', exc)
        raise SystemExit(1)
