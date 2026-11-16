"""Regressão 15.1.9.2: continuação automática de projetos parciais."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import ast


def project_operation(name, args, completed_projects):
    source = Path(__file__).with_name("agent.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
    fn = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_project_operation")
    fn.decorator_list = []
    scope = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "agent.py", "exec"), scope)
    return scope["_project_operation"](name, args, completed_projects)
from skills_manager import SkillsManager


class ProjectContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'projeto'
        self.config = {
            'paths': {'allowed_roots': [self.tmp.name]},
            'skills': {'enabled': True},
            'security': {'confirm_writes': False},
        }
        self.manager = SkillsManager(self.config)

    def test_repeated_create_is_routed_to_add(self):
        first = {'directory': str(self.root), 'files': [{'path': 'src/main.py', 'content': 'from src.downloader import download\n'}]}
        second = {'directory': str(self.root), 'files': [{'path': 'src/downloader.py', 'content': 'def download():\n    return 1\n'}]}
        with patch('developer_workspace._confirm_write', return_value=True):
            self.assertTrue(self.manager.execute('developer_create_project_structured', first)['success'])
            effective = project_operation('developer_create_project_structured', second, {str(self.root)})
            self.assertEqual(effective, 'developer_add_project_files')
            result = self.manager.execute(effective, second)
        self.assertTrue(result['success'], result)
        self.assertTrue((self.root / 'src/main.py').exists())
        self.assertTrue((self.root / 'src/downloader.py').exists())

    def test_no_overwrite_on_redirect(self):
        self.root.mkdir()
        (self.root / 'main.py').write_text('original')
        args = {'directory': str(self.root), 'files': [{'path': 'main.py', 'content': 'changed'}]}
        with patch('developer_workspace._confirm_write', return_value=True):
            result = self.manager.execute(project_operation('developer_create_project_structured', args, {str(self.root)}), args)
        self.assertIn('error', result)
        self.assertEqual((self.root / 'main.py').read_text(), 'original')

    def test_new_project_still_uses_create(self):
        args = {'directory': str(self.root), 'files': []}
        self.assertEqual(project_operation('developer_create_project_structured', args, set()), 'developer_create_project_structured')


if __name__ == '__main__':
    unittest.main()
