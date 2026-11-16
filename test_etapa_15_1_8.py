import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from developer_workspace import add_project_files
from skills_manager import SkillsManager


class AddProjectFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        self.config = {'paths': {'allowed_roots': [self.temp.name]}, 'skills': {'enabled': True}, 'security': {'confirm_writes': True}}

    def add(self, files):
        with patch('developer_workspace._confirm_write', return_value=True):
            return add_project_files(str(self.root), files, self.config)

    def test_batch_creation(self):
        files = [{'path': 'README.md', 'content': '# Hello'}, {'path': 'requirements.txt', 'content': 'requests\n'}, {'path': 'src/downloader.py', 'content': 'def download():\n    pass\n'}]
        result = self.add(files)
        self.assertTrue(result['success'])
        self.assertFalse(result['functional_tested'])
        for item in files:
            self.assertEqual((self.root / item['path']).read_text(), item['content'])

    def test_never_overwrite(self):
        (self.root / 'README.md').write_text('original')
        result = self.add([{'path': 'README.md', 'content': 'changed'}])
        self.assertIn('error', result)
        self.assertEqual((self.root / 'README.md').read_text(), 'original')

    def test_invalid_python_is_atomic(self):
        result = self.add([{'path': 'README.md', 'content': 'hello'}, {'path': 'broken.py', 'content': 'def broken(:'}])
        self.assertIn('error', result)
        self.assertFalse((self.root / 'README.md').exists())

    def test_traversal_blocked(self):
        result = self.add([{'path': '../outside.txt', 'content': 'x'}])
        self.assertIn('error', result)

    def test_registered(self):
        manager = SkillsManager(self.config)
        self.assertIn('developer_add_project_files', [s['function']['name'] for s in manager.schemas])

    def test_confirmation_required(self):
        with patch('developer_workspace._confirm_write', return_value=False):
            result = add_project_files(str(self.root), [{'path': 'a.txt', 'content': 'a'}], self.config)
        self.assertIn('error', result)
        self.assertFalse((self.root / 'a.txt').exists())


if __name__ == '__main__':
    unittest.main()
