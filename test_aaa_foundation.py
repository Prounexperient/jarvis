"""Regressões executáveis da primeira fundação do núcleo autônomo."""
import tempfile
import unittest
from pathlib import Path

from action_policy import ActionPolicy
from context_state import NavigationContext
from intent_resolver import IntentResolver
from quote_intent import is_general_quotation_request
from task_controller import TaskController


class IntentFoundationTests(unittest.TestCase):
    def setUp(self):
        self.resolve = IntentResolver().resolve

    def test_quotations_without_local_access(self):
        samples = (
            'Jarvis. Site o primeiro livro do livro de Enoch.',
            'Cite o primeiro livro de Enoque',
            'Cite um trecho do PDF Enoque',
            'Recite um trecho de uma obra de Tolkien',
            'Cite uma frase de Sêneca',
            'Cite um trecho da Odisseia',
        )
        for question in samples:
            with self.subTest(question=question):
                self.assertTrue(is_general_quotation_request(question))
                for tool in ('search_files', 'search_files_in_directory', 'open_file',
                             'search_directories', 'read_document'):
                    self.assertIn('conhecimento geral', ActionPolicy().deny_reason(tool, {}, question))

    def test_explicit_local_file_citation(self):
        for question in (
            'Cite um trecho do PDF Enoch do meu PC',
            'Cite um trecho do PDF que você abriu',
            r'Transcreva a passagem do arquivo C:\\Livros\\Enoque.pdf',
            'Cite a passagem deste PDF',
        ):
            with self.subTest(question=question):
                self.assertFalse(self.resolve(question).general_quotation)

    def test_media_and_generic_references_not_quotations(self):
        for question in ('Reproduza o próximo áudio', 'Reproduza o áudio do livro de Enoque',
                         'Cite as fontes que encontrou no arquivo',
                         'Abra o primeiro arquivo da Music Lib',
                         'Procure o PDF de Enoque no meu computador'):
            with self.subTest(question=question):
                self.assertFalse(self.resolve(question).general_quotation)

    def test_work_authorization_handles_negation_not_embedded(self):
        self.assertFalse(TaskController('Não aplique essas correções').write_authorized)
        self.assertTrue(TaskController('Crie um projeto e garanta que não haverá erros').write_authorized)
        self.assertIsNotNone(TaskController('Analise o código').inspect('developer_replace_file', {'path': 'x.py'}))
        self.assertIsNone(TaskController('Implemente uma função').inspect('developer_replace_file', {'path': 'x.py'}))

    def test_file_tools_not_used_on_general_quotation(self):
        request = 'Site o primeiro livro de Enoch'
        for name in ('developer_map_codebase', 'developer_read_code',
                     'developer_run_python', 'open_application'):
            with self.subTest(name=name):
                self.assertIsNotNone(TaskController(request).inspect(name, {}))

    def test_delete_and_run_do_not_inherit_general_write_permission(self):
        self.assertIsNotNone(TaskController('Crie um projeto').inspect('developer_delete_file', {'path': 'x.py'}))
        self.assertIsNotNone(TaskController('Crie um projeto').inspect('developer_run_python', {'path': 'main.py'}))
        # A ferramenta real ainda precisa aplicar confirmação explícita do alvo.
        self.assertIsNone(TaskController('Apague o arquivo indicado').inspect('developer_delete_file', {'path': 'x.py'}))
        self.assertIsNone(TaskController('Crie um projeto e execute os testes').inspect('developer_run_derived_test', {'project': 'x'}))


class ToolGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.nav = NavigationContext(Path(self.temp.name) / 'jarvis.db')
        self.paths = [r'D:\\Music Lib\\musica{}.mp3'.format(i) for i in range(1, 5)]
        self.nav.observe('search_files_in_directory', {
            'scope': r'D:\\Music Lib',
            'results': [{'index': i, 'path': path} for i, path in enumerate(self.paths, 1)]
        })

    def test_load_is_allowed_for_audio_both_target_types(self):
        task = TaskController('Carregue o primeiro arquivo', navigation=self.nav)
        self.assertIsNone(task.inspect('open_search_result', {'index': 1}))
        task = TaskController('Carregue o primeiro arquivo', navigation=self.nav)
        self.assertIsNone(task.inspect('open_file', {'path': self.paths[0]}))

    def test_load_is_not_general_file_open(self):
        task = TaskController('Carregue o primeiro arquivo', navigation=self.nav)
        self.assertIsNotNone(task.inspect('open_file', {'path': r'C:\\code\\main.py'}))
        self.assertIsNotNone(TaskController('Carregue o primeiro arquivo').inspect('open_search_result', {'index': 1}))

    def test_latest_search_index_not_media_sequence_index(self):
        self.nav.observe('search_files', {'results': [
            {'index': 1, 'path': r'D:\\Docs\\manual.pdf'},
            {'index': 2, 'path': r'D:\\Music Lib\\song.mp3'},
        ]})
        self.assertIsNotNone(TaskController('Carregue o primeiro arquivo', navigation=self.nav).inspect('open_search_result', {'index': 1}))
        self.assertIsNone(TaskController('Carregue o segundo arquivo', navigation=self.nav).inspect('open_search_result', {'index': 2}))

    def test_open_permission_is_same_for_direct_and_llm_gates(self):
        for phrase in ('Abra o primeiro arquivo', 'Reproduza a primeira música',
                       'Carregue o primeiro arquivo'):
            with self.subTest(phrase=phrase):
                self.assertIsNone(TaskController(phrase, navigation=self.nav).inspect('open_file', {'path': self.paths[0]}))
        self.assertIsNotNone(TaskController('Não abra o primeiro arquivo', navigation=self.nav).inspect('open_file', {'path': self.paths[0]}))

    def test_media_cursor_only_moves_on_success(self):
        reference = self.nav.media_navigation('Abra o primeiro arquivo')
        self.assertEqual(reference['position'], 1)
        self.nav.observe('open_file', {'error': 'aplicativo indisponível', 'opened': reference['path']})
        self.assertIsNone(self.nav.state['media_sequence']['current_index'])
        self.nav.observe('open_file', {'opened': reference['path']})
        self.assertEqual(self.nav.media_navigation('Carregue o próximo arquivo')['position'], 2)

    def test_sqlite_navigation_persistence(self):
        self.nav.observe('open_file', {'opened': self.paths[0]})
        new = NavigationContext(self.nav.db_path)
        self.assertEqual(new.media_navigation('Reproduza o próximo arquivo')['path'], self.paths[1])


if __name__ == '__main__':
    unittest.main()
