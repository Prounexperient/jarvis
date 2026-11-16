"""Testes offline: sem LM Studio, Whisper, Kokoro ou dependências externas."""
import unittest
from types import SimpleNamespace
from model_commands import parse_model_command, execute_model_command, ModelCommand

class FakeManager:
    models = {'qwen': object(), 'gpt_oss': object()}
    def __init__(self): self.calls = []
    def ensure_loaded(self, target): self.calls.append(target)

class TestCommands(unittest.TestCase):
    def test_recognizes_commands(self):
        for text, target in [('JARVIS, ative o modelo avançado', 'gpt_oss'),
                             ('Volte ao modelo padrão', 'qwen'),
                             ('/modelo gpt', 'gpt_oss'), ('/modelo qwen', 'qwen')]:
            self.assertEqual(parse_model_command(text).target, target)
        self.assertEqual(parse_model_command('Jarvis, qual modelo está ativo?').action, 'status')
        self.assertEqual(parse_model_command('/modelo status').action, 'status')
    def test_no_false_positive(self):
        for text in ['Qual a diferença entre Qwen e GPT-OSS?',
                     'Jarvis, explique o modelo avançado',
                     'Eu disse ative o modelo avançado ontem',
                     'Quero usar o Qwen para programação']:
            self.assertIsNone(parse_model_command(text), text)
    def test_switch_only_after_confirmation(self):
        manager = FakeManager()
        agent = SimpleNamespace(model_manager=manager, active_model_name='qwen')
        self.assertIn('pronto', execute_model_command(ModelCommand('switch', 'gpt_oss'), agent))
        self.assertEqual(agent.active_model_name, 'gpt_oss')
        self.assertEqual(manager.calls, ['gpt_oss'])
        execute_model_command(ModelCommand('switch', 'gpt_oss'), agent)
        self.assertEqual(manager.calls, ['gpt_oss'])
    def test_failed_load_preserves_selection(self):
        manager = FakeManager()
        def fail(_): raise RuntimeError('falhou')
        manager.ensure_loaded = fail
        agent = SimpleNamespace(model_manager=manager, active_model_name='qwen')
        self.assertIn('Não consegui', execute_model_command(ModelCommand('switch', 'gpt_oss'), agent))
        self.assertEqual(agent.active_model_name, 'qwen')

if __name__ == '__main__': unittest.main(verbosity=2)
