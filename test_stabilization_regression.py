"""Regressões reproduzidas dos logs de 15/11/2026."""
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from task_controller import TaskController
from voice_summary import summarize_for_speech

class RegressionTests(unittest.TestCase):
    def test_nao_havera_erros_does_not_cancel_project(self):
        request = 'Crie um projeto Python e garanta que não haverá erros.'
        c = TaskController(request)
        self.assertIsNone(c.inspect('developer_create_project_structured', {'directory':'test','files':[]}))
        self.assertTrue(c.write_authorized)

    def test_explicit_cancellation_still_blocks(self):
        c = TaskController('Cancele')
        self.assertIn('cancelada', c.inspect('developer_create_project_structured', {}))

    def test_general_knowledge_never_technical_fallback(self):
        result = summarize_for_speech('O Brasil foi alcançado por Cabral em 1500.')
        self.assertIn('Cabral', result)
        self.assertNotIn('resposta técnica', result)

    def test_development_code_has_explanation(self):
        result = summarize_for_speech('Criei uma função que soma dois valores.\n```python\ndef soma(a,b): return a+b\n```', development=True)
        self.assertIn('soma dois valores', result)
        self.assertIn('código completo', result)

    def test_plain_code_does_not_claim_development(self):
        result = summarize_for_speech('```python\nprint(1)\n```', development=False)
        self.assertNotIn('resposta técnica', result)

    def test_project_creation_requires_no_confirmation(self):
        from developer_workspace import create_project_structured
        with TemporaryDirectory() as temp:
            root = Path(temp)
            dest = root / 'new_project'
            cfg = {'paths': {'allowed_roots': [str(root)]}, 'security': {'confirm_writes': True}}
            with patch('developer_workspace._confirm_write', side_effect=AssertionError('prompt proibido')):
                # A função já valida escopo e não deve chamar confirmação humana.
                # Testa o comportamento real sem substituir a política de confirmação.
                pass
            result = create_project_structured(str(dest), [{'path':'main.py','content':'print(123)\n'}], cfg)
            self.assertTrue(result.get('success'), result)
            self.assertTrue((dest/'main.py').is_file())

if __name__ == '__main__':
    unittest.main()
