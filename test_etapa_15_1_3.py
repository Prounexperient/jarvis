"""Regressões do contrato estruturado de criação de projetos."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from skills_manager import SkillsManager

class StructuredProjectTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.manager = SkillsManager({'paths': {'allowed_roots': [str(self.root)]}, 'security': {'confirm_writes': True}, 'skills': {'enabled': True}})

    def create(self, name, files, approval='SIM'):
        with patch('builtins.input', return_value=approval):
            return self.manager.execute('developer_create_project_structured', {'directory': str(self.root/name), 'files': files})

    def test_nested_quotes_and_multifile(self):
        source = 'def run():\n    print(f"Hello, {\'world\'}!")\n'
        result = self.create('Tolkien', [{'path': 'src/main.py', 'content': source}, {'path': 'README.md', 'content': 'Tolkien'}])
        self.assertTrue(result['success'], result)
        self.assertEqual((self.root/'Tolkien/src/main.py').read_text(), source)

    def test_invalid_python_no_partial_project(self):
        result = self.create('invalid', [{'path': 'main.py', 'content': 'def broken(:\n pass'}])
        self.assertIn('error', result)
        self.assertFalse((self.root/'invalid').exists())

    def test_refusal(self):
        result = self.create('refused', [{'path': 'main.py', 'content': 'pass\n'}], 'NÃO')
        self.assertIn('error', result)
        self.assertFalse((self.root/'refused').exists())

    def test_traversal_and_duplicate(self):
        self.assertIn('error', self.create('traversal', [{'path': '../escape.py', 'content': 'pass'}]))
        self.assertIn('error', self.create('dup', [{'path': 'a.py', 'content': 'pass'}, {'path': 'a.py', 'content': 'pass'}]))

    def test_schema_array_and_legacy_error(self):
        schema = next(s for s in self.manager.schemas if s['function']['name'] == 'developer_create_project_structured')
        self.assertEqual(schema['function']['parameters']['properties']['files']['type'], 'array')
        result = self.manager.execute('developer_create_project', {'directory': str(self.root/'legacy'), 'files_json': '[{"path":"a.py","content":"broken"}'})
        self.assertIn('developer_create_project_structured', result['error'])

if __name__ == '__main__':
    unittest.main()
