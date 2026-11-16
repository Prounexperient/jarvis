import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path
from task_completion import TaskCompletion
from voice_summary import summarize_for_speech
import derived_test_environment as env
from task_controller import TaskController

class TestRevision(unittest.TestCase):
    def test_read_tracking_without_write_authorization(self):
        c=TaskCompletion('Analise e sugira melhorias')
        c.observe('read_text_file', {'path':'C:/proj/a.py'}, {'path':'C:/proj/a.py','content':'x'})
        self.assertEqual(c.reads,1)
    def test_uncovered_triggers_once(self):
        c=TaskCompletion('Analise o projeto')
        c.observe('search_files_in_directory',{}, {'results':[{'path':'C:/proj/a.py'},{'path':'C:/proj/b.py'}]})
        c.observe('read_text_file',{'path':'C:/proj/a.py'},{'content':'hello'})
        self.assertEqual(len(c.uncovered()),1)
        self.assertTrue(c.needs_continuation())
        c.instruction()
        self.assertFalse(c.needs_continuation())
    def test_write_continuation(self):
        c=TaskCompletion('Analise e aplique correções', True)
        c.observe('developer_replace_file',{'path':'a.py'},{'success':True,'syntax_valid':True})
        self.assertTrue(c.needs_continuation())
        c.observe('developer_run_derived_test',{}, {'executed':True,'exit_code':1,'passed':False})
        self.assertFalse(c.needs_continuation())
    def test_failed_test_not_passed(self):
        c=TaskCompletion('Analise e aplique correções', True)
        c.observe('developer_run_derived_test',{}, {'executed':True,'exit_code':1,'passed':False})
        self.assertFalse(c.functional_tests[0]['passed'])
    def test_no_write_permission(self):
        t=TaskController('Analise e sugira melhorias')
        self.assertIsNotNone(t.inspect('developer_prepare_test_environment',{'project':'demo'}))
    def test_test_requires_request(self):
        t=TaskController('Analise e sugira melhorias')
        self.assertIsNotNone(t.inspect('developer_run_derived_test',{'project':'demo','test_file':'test_a.py'}))
    def test_project_name_validation(self):
        for name in ('../x','a/b','', '.venv'):
            with self.assertRaises(ValueError): env._project(name)
    def test_prepare_requires_confirmation(self):
        with patch.object(env, '_confirm', return_value=False):
            self.assertIn('error',env.prepare('demo',{}))
    def test_run_requires_test_file(self):
        self.assertIn('error',env.run_tests('demo','main.py',{}))
    def test_voice_excludes_code(self):
        out=summarize_for_speech('Resumo das correções.\n```python\nprint(123)\n```\nTestes pendentes.')
        self.assertNotIn('print(123)',out)
        self.assertIn('Testes pendentes',out)

if __name__=='__main__': unittest.main()
