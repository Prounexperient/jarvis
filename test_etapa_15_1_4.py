import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from developer_workspace import replace_function, replace_file

class Test1514(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'code.py'
        self.path.write_text('def old():\n    return 1\n', encoding='utf-8')
        self.cfg = {'paths': {'allowed_roots': [self.tmp.name]}, 'security': {'confirm_writes': True}}
    def tearDown(self):
        self.tmp.cleanup()
    def test_replace_function(self):
        with patch('developer_workspace._require_path', return_value=self.path), patch('developer_workspace._confirm_write', return_value=True):
            result = replace_function(str(self.path), 'old', 'def old():\n    return 2\n', self.cfg)
        self.assertTrue(result['success'])
        self.assertFalse(result['functional_tested'])
        self.assertIn('return 2', self.path.read_text())
        self.assertTrue(Path(result['backup']).exists())
    def test_reject_invalid_syntax(self):
        with patch('developer_workspace._require_path', return_value=self.path), patch('developer_workspace._confirm_write', return_value=True):
            result = replace_function(str(self.path), 'old', 'def old(:\n', self.cfg)
        self.assertIn('error', result)
        self.assertIn('return 1', self.path.read_text())
    def test_confirm_failure_does_not_write(self):
        with patch('developer_workspace._require_path', return_value=self.path), patch('developer_workspace._confirm_write', side_effect=OSError('WinError 6')):
            result = replace_file(str(self.path), 'def old():\n    return 3\n', self.cfg)
        self.assertIn('Confirmação indisponível', result['error'])
        self.assertIn('return 1', self.path.read_text())
    def test_recovery_system_first(self):
        try:
            from agent import Agent
        except ModuleNotFoundError:
            self.skipTest('openai SDK indisponível no ambiente de testes')
        obj = Agent.__new__(Agent)
        obj.history = [{'role':'system','content':'base'}, {'role':'user','content':'oi'}]
        obj._model_messages = lambda: list(obj.history)
        obj._clean_tool_history = lambda: None
        messages = obj._recovery_messages('instrução')
        self.assertEqual([m['role'] for m in messages], ['system','user'])
        self.assertIn('instrução', messages[0]['content'])
        self.assertTrue(obj._is_internal_response('<tool_call>'))

if __name__ == '__main__': unittest.main()
