"""Regressões: caminhos Windows, raiz padrão, segurança e criação de projetos."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tools
import developer_workspace as workspace


class ProjectPathRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.home_patch = patch('pathlib.Path.home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.config = {'paths': {'allowed_roots': []}, 'security': {'confirm_writes': True}}
        self.files = [{'path': 'src/main.py', 'content': 'def main():\n    return 1\n'}, {'path': 'tests/test_main.py', 'content': 'import unittest\n'}]

    def test_expands_userprofile_even_when_environment_missing(self):
        with patch.dict(os.environ, {'USERPROFILE': ''}):
            path = tools._normalize_local_path('%USERPROFILE%/JARVIS_DERIVED_PROJECTS/demo')
        self.assertEqual(path, (self.home / 'JARVIS_DERIVED_PROJECTS/demo').resolve())

    def test_creates_managed_parent_and_project(self):
        with patch.dict(os.environ, {'USERPROFILE': str(self.home)}):
            result = workspace.create_project_structured('%USERPROFILE%/JARVIS_DERIVED_PROJECTS/demo', self.files, self.config)
        self.assertTrue(result.get('success'), result)
        self.assertFalse(result['functional_tested'])
        self.assertTrue((self.home / 'JARVIS_DERIVED_PROJECTS/demo/tests/test_main.py').is_file())

    def test_existing_project_is_not_overwritten(self):
        target = self.home / 'JARVIS_DERIVED_PROJECTS/demo'
        target.mkdir(parents=True)
        sentinel = target / 'sentinel.txt'
        sentinel.write_text('preserve')
        result = workspace.create_project_structured(str(target), self.files, self.config)
        self.assertEqual(result.get('error_code'), 'PROJECT_EXISTS')
        self.assertEqual(sentinel.read_text(), 'preserve')

    def test_missing_nonmanaged_parent_not_created(self):
        root = self.home / 'elsewhere' / 'project'
        self.config['paths']['allowed_roots'] = [str(self.home)]
        result = workspace.create_project_structured(str(root), self.files, self.config)
        self.assertIn('error', result)
        self.assertFalse(root.parent.exists())

    def test_rejects_unknown_environment_variable(self):
        with self.assertRaises(ValueError):
            tools._normalize_local_path('%JARVIS_UNKNOWN_TEST_VARIABLE_999%/demo')

    def test_rejects_traversal_outside_authorized_root(self):
        with self.assertRaises(PermissionError):
            tools._require_path('%USERPROFILE%/JARVIS_DERIVED_PROJECTS/../../escape', self.config, must_exist=False)

    def test_python_syntax_error_does_not_create_project(self):
        root = self.home / 'JARVIS_DERIVED_PROJECTS/bad'
        result = workspace.create_project_structured(str(root), [{'path':'src/a.py','content':'def broken(:\n'}], self.config)
        self.assertIn('error', result)
        self.assertFalse(root.exists())


if __name__ == '__main__':
    unittest.main()
