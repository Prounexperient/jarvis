import unittest
from task_completion import TaskCompletion


class CompletionTests(unittest.TestCase):
    def test_composite_request(self):
        t = TaskCompletion('Analise o projeto e aplique todas as correções.', True)
        self.assertTrue(t.active)
        t.observe('developer_replace_file', {'path': 'a.py'}, {'success': True, 'syntax_valid': True, 'functional_tested': False})
        self.assertTrue(t.needs_continuation())
        self.assertIn('nenhuma ferramenta confirmou teste funcional', t.instruction())
        self.assertFalse(t.needs_continuation())

    def test_read_only_no_continuation(self):
        self.assertFalse(TaskCompletion('Analise o projeto e sugira melhorias', False).active)

    def test_no_write_no_continuation(self):
        t = TaskCompletion('Analise e aplique as correções', True)
        t.observe('developer_read_code', {}, {'content': 'x'})
        self.assertFalse(t.needs_continuation())

    def test_functional_verification(self):
        t = TaskCompletion('Analise e aplique as correções', True)
        t.observe('developer_replace_file', {'path':'a.py'}, {'success': True, 'functional_tested': True})
        self.assertFalse(t.needs_continuation())

    def test_failed_write(self):
        t = TaskCompletion('Analise e aplique as correções', True)
        t.observe('developer_replace_file', {'path':'a.py'}, {'error':'denied'})
        self.assertFalse(t.needs_continuation())
        self.assertEqual(len(t.failures), 1)


if __name__ == '__main__':
    unittest.main()
