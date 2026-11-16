import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from skills_manager import SkillsManager

class SkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'paths': {'allowed_roots': [str(self.root)]}, 'security': {'confirm_writes': True}, 'skills': {'enabled': True}}
        self.manager = SkillsManager(self.config)

    def test_registration_and_fallback(self):
        self.assertIn('developer_create_python', [s['function']['name'] for s in self.manager.schemas])
        off = SkillsManager(dict(self.config, skills={'enabled': False}))
        self.assertNotIn('developer_create_python', [s['function']['name'] for s in off.schemas])
        self.assertEqual(off.execute('calculator', {'expression':'1+2'})['result'], '3')

    def test_create_and_verify(self):
        target = self.root/'hello.py'
        with patch('builtins.input', return_value='SIM'):
            result = self.manager.execute('developer_create_python', {'path': str(target), 'content': 'print("Hello, World!")\n'})
        self.assertTrue(result['verified'])
        self.assertEqual(target.read_text(encoding='utf-8'), 'print("Hello, World!")\n')
        self.assertIn('error', self.manager.execute('developer_create_python', {'path': str(target), 'content': 'print(2)'}))

    def test_refusal_and_scope(self):
        target = self.root/'no.py'
        with patch('builtins.input', return_value='NÃO'):
            result = self.manager.execute('developer_create_python', {'path': str(target), 'content': 'print(1)'})
        self.assertIn('error', result)
        self.assertFalse(target.exists())
        self.assertIn('error', self.manager.execute('developer_create_python', {'path': str(self.root.parent/'outside.py'), 'content': 'print(1)'}))

    def test_syntax_and_inspect(self):
        self.assertIn('error', self.manager.execute('developer_create_python', {'path': str(self.root/'bad.py'), 'content': 'print('}))
        (self.root/'existing.py').write_text('x=1')
        result = self.manager.execute('developer_inspect_project', {'directory': str(self.root)})
        self.assertIn('existing.py', result['files'])

    def test_run_requires_confirmation(self):
        target = self.root/'run.py'
        target.write_text('print("OK")')
        with patch('builtins.input', return_value='NÃO'):
            self.assertIn('error', self.manager.execute('developer_run_python', {'path': str(target)}))
        with patch('builtins.input', return_value='SIM'):
            result = self.manager.execute('developer_run_python', {'path': str(target)})
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['stdout'].strip(), 'OK')

    def test_parallel_readonly(self):
        results = self.manager.execute_many([('calculator', {'expression': '1+2'}), ('calculator', {'expression': '3+5'})], parallel=True)
        self.assertEqual([r['result'] for r in results], ['3', '8'])

if __name__ == '__main__': unittest.main()
