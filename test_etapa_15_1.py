import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from skills_manager import SkillsManager

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'paths': {'allowed_roots': [str(self.root)]}, 'security': {'confirm_writes': True}, 'skills': {'enabled': True}}
        self.manager = SkillsManager(self.config)

    def create(self, directory, files):
        return self.manager.execute('developer_create_project', {'directory': str(directory), 'files_json': json.dumps(files)})

    def test_project_and_map(self):
        root = self.root / 'demo'
        with patch('builtins.input', return_value='SIM'):
            result = self.create(root, [{'path':'src/main.py','content':'import os\ndef hello():\n    print("Hello")\n'}, {'path':'README.md','content':'Demo'}])
        self.assertTrue(result['verified'])
        self.assertEqual((root/'README.md').read_text(), 'Demo')
        mapping = self.manager.execute('developer_map_codebase', {'directory':str(root)})
        self.assertEqual(mapping['modules'][0]['functions'], ['hello'])
        read = self.manager.execute('developer_read_code', {'path':str(root/'src/main.py')})
        self.assertIn('hello', read['content'])

    def test_no_overwrite_and_traversal(self):
        root = self.root / 'demo'
        with patch('builtins.input', return_value='SIM'):
            self.assertTrue(self.create(root, [{'path':'a.py','content':'x=1'}])['success'])
        self.assertIn('error', self.create(root, [{'path':'a.py','content':'x=2'}]))
        self.assertIn('error', self.create(self.root/'bad', [{'path':'../escape.py','content':'x=1'}]))
        self.assertFalse((self.root/'escape.py').exists())

    def test_patch_backup_and_syntax(self):
        target = self.root/'a.py'
        target.write_text('value = 1\n',encoding='utf-8')
        args = {'path':str(target),'old_text':'value = 1','new_text':'value = 2'}
        with patch('builtins.input', return_value='SIM'):
            result = self.manager.execute('developer_patch_file', args)
        self.assertTrue(result['verified'])
        self.assertEqual(target.read_text(), 'value = 2\n')
        self.assertEqual(Path(result['backup']).read_text(), 'value = 1\n')
        self.assertIn('error', self.manager.execute('developer_patch_file', args))
        self.assertIn('error', self.manager.execute('developer_patch_file', {'path':str(target),'old_text':'value = 2','new_text':'value = ('}))

    def test_refusal_and_disabled(self):
        with patch('builtins.input', return_value='NÃO'):
            self.assertIn('error', self.create(self.root/'demo', [{'path':'x.py','content':'x=1'}]))
        self.assertFalse((self.root/'demo').exists())
        off = SkillsManager(dict(self.config, skills={'enabled':False}))
        self.assertIn('error', off.execute('developer_map_codebase', {'directory':str(self.root)}))

if __name__ == '__main__': unittest.main()
