"""Regressoes de inspecao fundamentada; sem LM Studio nem escrita no Windows."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import sys
import types
sys.modules.setdefault("openai", types.SimpleNamespace(OpenAI=object))
from agent import Agent

class GroundedInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'src').mkdir()
        (self.root/'src'/'main.py').write_text('print("bem-vindo")\n', encoding='utf-8')
        (self.root/'src'/'instagram.py').write_text('def download(url):\n    print("nao implementado")\n', encoding='utf-8')
        self.agent = Agent.__new__(Agent)
        def read(name, args):
            if name != 'developer_read_code':
                raise AssertionError(name)
            return {'path': args['path'], 'content': Path(args['path']).read_text(encoding='utf-8')}
        self.agent.skills_manager = Mock()
        self.agent.skills_manager.execute.side_effect = read
    def tearDown(self):
        self.temp.cleanup()
    def inspect(self, request, files=None):
        return self.agent._ground_project_inspection('developer_inspect_project',
            {'directory': str(self.root)}, {'directory': str(self.root),
            'files': files if files is not None else ['src/main.py', 'src/instagram.py'], 'truncated': False}, request)
    def test_reads_real_content(self):
        data = self.inspect('Analise o projeto e sugira melhorias')
        self.assertTrue(data['source_review_complete'])
        self.assertIn('nao implementado', data['source_evidence']['src/instagram.py'])
        self.assertEqual([], data['unread_source_files'])
    def test_listing_does_not_read(self):
        data = self.inspect('Liste os arquivos')
        self.assertNotIn('source_evidence', data)
        self.agent.skills_manager.execute.assert_not_called()
    def test_missing_file_is_not_claimed_read(self):
        data = self.inspect('Analise', ['src/main.py', 'src/missing.py'])
        self.assertFalse(data['source_review_complete'])
        self.assertIn('src/missing.py', data['unread_source_files'])
    def test_budget_partial(self):
        files=[]
        for i in range(9):
            rel=f'src/file{i}.py'
            (self.root/rel).write_text('x=1\n',encoding='utf-8')
            files.append(rel)
        data=self.inspect('Revisar arquivos', files)
        self.assertEqual(6,len(data['source_evidence']))
        self.assertEqual(3,len(data['unread_source_files']))
        self.assertFalse(data['source_review_complete'])
    def test_no_path_escape(self):
        data=self.inspect('Auditar', ['../outside.py'])
        self.assertFalse(data['source_review_complete'])
        self.agent.skills_manager.execute.assert_not_called()

if __name__=='__main__': unittest.main()
