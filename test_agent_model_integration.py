"""Smoke test da integração; exige dependências de requirements.txt instaladas."""
import logging
from pathlib import Path
import yaml
from agent import Agent
from model_manager import ModelManagerError

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
config = yaml.safe_load(Path(__file__).with_name('config.yaml').read_text(encoding='utf-8'))
assert config['model_management']['enabled'] is True
print('Modelo principal:', config['model_management']['default_model'])
print('ATENÇÃO: o teste pode descarregar outro modelo gerenciado.')
if input('Continuar? [s/N] ').strip().casefold() not in ('s', 'sim'):
    raise SystemExit('Cancelado.')
agent = Agent(config)
try:
    answer = agent.ask('Responda em uma frase: o que é inteligência?')
    print('JARVIS>', answer)
    print('Modelo confirmado:', agent.model_manager.loaded())
    print('Histórico de mensagens:', len(agent.history))
except ModelManagerError as exc:
    raise SystemExit('[ERRO SEGURO] ' + str(exc))
