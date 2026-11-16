"""Testa o código REAL dos dois atalhos do Agent sem LM Studio/Windows.

Extração via AST evita importar OpenAI e os serviços de voz, mas executa as
funções existentes em agent.py (não uma cópia reescrita de sua lógica).
"""
import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from action_policy import ActionPolicy
from context_state import NavigationContext
from contextual_actions import resolve_action
from task_controller import TaskController


def load_agent_method(name, overrides=None):
    source = Path(__file__).with_name('agent.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    obj = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'Agent')
    function = next(x for x in obj.body if isinstance(x, ast.FunctionDef) and x.name == name)
    scope = {'TaskController': TaskController, 'Path': Path, 'resolve_action': resolve_action,
             're': __import__('re'), 'get_last_search_paths': lambda: []}
    scope.update(overrides or {})
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'agent.py', 'exec'), scope)
    return scope[name]


class AgentGatewayIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.nav = NavigationContext(Path(self.tmp.name) / 'memory.db')
        self.paths = [r'D:\Music Lib\song{}.mp3'.format(i) for i in (1, 2, 3)]
        self.nav.observe('search_files_in_directory', {'scope': r'D:\Music Lib', 'results': [
            {'index': i + 1, 'path': p} for i, p in enumerate(self.paths)]})
        self.execute = Mock(side_effect=lambda name, args: {'opened': args.get('path', self.paths[0])})
        self.agent = SimpleNamespace(navigation=self.nav, skills_manager=SimpleNamespace(execute=self.execute), history=[])

    def test_actual_media_shortcut_uses_policy_and_updates_memory(self):
        action = load_agent_method('_contextual_media_action')
        msg = action(self.agent, 'Carregue o primeiro arquivo')
        self.assertIn('arquivo 1', msg)
        self.execute.assert_called_once_with('open_file', {'path': self.paths[0]})
        self.assertEqual(self.nav.state['media_sequence']['current_index'], 0)
        msg = action(self.agent, 'Carregue o próximo arquivo')
        self.assertIn('arquivo 2', msg)
        self.assertEqual(self.nav.state['media_sequence']['current_index'], 1)
        self.assertEqual(len(self.agent.history), 4)

    def test_declined_open_never_invokes_tool(self):
        action = load_agent_method('_contextual_media_action')
        self.assertIsNone(action(self.agent, 'Não abra o primeiro arquivo'))
        self.execute.assert_not_called()

    def test_open_result_from_context_uses_same_task_policy(self):
        # A ferramenta do contexto foi resolvida mas a abertura ainda passa por TaskController.
        action = load_agent_method('_contextual_file_action', {'get_last_search_paths': lambda: self.paths})
        self.assertIsNotNone(action(self.agent, 'Abra o segundo'))
        self.execute.assert_called_once_with('open_search_result', {'index': 2})


if __name__ == '__main__':
    unittest.main()
