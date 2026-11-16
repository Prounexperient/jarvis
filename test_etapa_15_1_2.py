"""Regressões Etapa 15.1.2; não exige LM Studio ou Windows."""
import tempfile
import unittest
from pathlib import Path
from task_controller import TaskController
from developer_context import DeveloperContext
from developer_workspace import verify_code, SCHEMAS

class Tests1512(unittest.TestCase):
    def test_carregue_autoriza_leitura(self):
        for phrase in ('Carregue o arquivo que acabou de criar', 'Carregar arquivo Python'):
            self.assertIsNone(TaskController(phrase).inspect('read_text_file', {'path':'x.py'}))
            self.assertIsNone(TaskController(phrase).inspect('read_document', {'path':'x.py'}))
    def test_carregue_nao_autoriza_abertura_visual(self):
        self.assertIsNotNone(TaskController('Carregue o arquivo').inspect('open_file', {'path':'x.py'}))
        self.assertIsNone(TaskController('Abra o arquivo').inspect('open_file', {'path':'x.py'}))
    def test_contexto_criacao_leitura_abertura(self):
        ctx = DeveloperContext()
        ctx.observe('developer_create_python', {'path':'/tmp/x.py'}, {'success':True, 'path':'/tmp/x.py'})
        ctx.observe('open_file', {'path':'/tmp/x.py'}, {'opened':'/tmp/x.py'})
        ctx.observe('read_document', {'path':'/tmp/x.py'}, {'path':'/tmp/x.py','text':'def baixar():\n    pass\n'})
        self.assertEqual(ctx.function, 'baixar')
        self.assertIn('/tmp/x.py', ctx.instruction())
        ctx.observe('developer_patch_file', {'path':'/tmp/y.py'}, {'error':'Falha'})
        self.assertEqual(ctx.path, '/tmp/x.py')
    def test_verify_ast_functions(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.py'
            p.write_text('def download_video():\n    pass\n', encoding='utf-8')
            cfg={'paths':{'allowed_roots':[d]}}
            r=verify_code(str(p), '["download_video","imprimir_nome"]', cfg)
            self.assertFalse(r['structural_verified'])
            self.assertEqual(r['functions_missing'], ['imprimir_nome'])
            self.assertFalse(r['functional_tested'])
            p.write_text('def download_video():\n    pass\n\ndef imprimir_nome(nome):\n    print(nome)\n', encoding='utf-8')
            r=verify_code(str(p), '["download_video","imprimir_nome"]', cfg)
            self.assertTrue(r['structural_verified'])
    def test_verify_rejeita_sintaxe_ruim_e_nomes_ruins(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.py';p.write_text('def broken(\n', encoding='utf-8')
            cfg={'paths':{'allowed_roots':[d]}}
            self.assertIn('error',verify_code(str(p),'["broken"]',cfg))
            self.assertIn('error',verify_code(str(p),'["not valid"]',cfg))
    def test_schema_registrado(self):
        self.assertIn('developer_verify_code', [x['function']['name'] for x in SCHEMAS])

if __name__=='__main__': unittest.main()
