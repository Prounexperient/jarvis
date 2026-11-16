import unittest
from task_controller import TaskController, pending_authorization

class ContextAuthorizationTests(unittest.TestCase):
    def test_apply_all(self):
        t=TaskController('Aplique todas as correções e melhorias ao projeto')
        self.assertIsNone(t.inspect('developer_replace_function', {'path':'x.py'}))
    def test_confirmation_bound(self):
        history=[{'role':'user','content':'Aplique todas as correções no projeto X'},
                 {'role':'assistant','content':'Preciso de sua confirmação para editar os arquivos. Diga sim.'}]
        t=TaskController('Sim, pode aplicar os ajustes, as edições.', history)
        self.assertTrue(t.write_authorized)
        self.assertEqual(t.confirmed_request, history[0]['content'])
    def test_confirmation_not_general_permission(self):
        history=[{'role':'user','content':'Qual a temperatura?'},
                 {'role':'assistant','content':'Confirma?'}]
        self.assertFalse(TaskController('sim',history).write_authorized)
    def test_denial(self):
        self.assertFalse(TaskController('Não aplique as correções').write_authorized)
    def test_plain_analysis(self):
        self.assertIsNotNone(TaskController('Analise os arquivos').inspect('developer_replace_file',{}))
    def test_read_when_editing(self):
        self.assertIsNone(TaskController('Implemente a função').inspect('read_text_file',{}))
    def test_unrelated_confirmation(self):
        history=[{'role':'user','content':'Aplique correções'}, {'role':'assistant','content':'Alterações propostas.'}]
        self.assertFalse(TaskController('sim',history).write_authorized)
    def test_new_create_add(self):
        self.assertIsNone(TaskController('Crie o projeto').inspect('developer_add_project_files',{}))

if __name__=='__main__': unittest.main()
