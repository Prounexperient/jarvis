"""Regressões dos incidentes reais de edição da Etapa 15.1."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from task_controller import TaskController
from developer_context import DeveloperContext
from developer_workspace import read_code, patch_file

class DeveloperFlowTests(unittest.TestCase):
    def test_edit_request_allows_auxiliary_read(self):
        task = TaskController('Acrescente uma função e chame dentro do main')
        self.assertIsNone(task.inspect('read_document', {'path': 'x.py'}))
        self.assertIsNone(task.inspect('read_text_file', {'path': 'x.py'}))

    def test_plain_search_does_not_authorize_read(self):
        task = TaskController('Procure o arquivo main.py')
        self.assertIsNotNone(task.inspect('read_document', {'path': 'x.py'}))
        self.assertIsNotNone(task.inspect('open_file', {'path': 'x.py'}))

    def test_edit_does_not_authorize_open(self):
        self.assertIsNotNone(TaskController('Edite o arquivo main.py').inspect('open_file', {'path': 'x.py'}))

    def test_focus_tracks_function_and_failed_patch_preserves_focus(self):
        ctx = DeveloperContext()
        ctx.observe('developer_read_code', {'path': '/tmp/a.py'}, {'path': '/tmp/a.py', 'content': 'def a():\n    pass\ndef b():\n    pass\n', 'function_name': 'b'})
        self.assertEqual(ctx.function, 'b')
        ctx.observe('developer_patch_file', {'path': '/tmp/a.py'}, {'error': 'Trecho ausente'})
        self.assertEqual(ctx.function, 'b')
        self.assertIn('b', ctx.instruction())

    def test_real_read_and_patch(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'main.py'
            p.write_text('def main():\n    print("HelloJarps")\n\nif __name__ == "__main__":\n    main()\n', encoding='utf-8')
            cfg = {'paths': {'allowed_roots': [d]}}
            read = read_code(str(p), cfg, function_name='main')
            self.assertEqual(read['function_name'], 'main')
            self.assertIn('print("HelloJarps")', read['function_source'])
            with patch('developer_workspace._confirm_write', return_value=True):
                result = patch_file(str(p), 'def main():', 'def incrementar(n):\n    return n + 1\n\ndef main():\n    print(incrementar(1))', cfg)
            self.assertTrue(result['verified'])
            self.assertIn('def incrementar(n):', p.read_text())
            self.assertTrue(Path(result['backup']).exists())

if __name__ == '__main__':
    unittest.main()
