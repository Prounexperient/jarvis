import tempfile
import unittest
from pathlib import Path
from context_state import NavigationContext

class OperationalMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'memory.db'
        self.memory = NavigationContext(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pdf_found_then_first_page(self):
        path = '/books/hill.pdf'
        self.memory.observe('search_files', {'results': [{'index': 1, 'path': path}]}, {'query': 'Hill'})
        ref = self.memory.resolve('Resuma a primeira página do PDF')
        self.assertEqual(ref, {'path': path, 'page': 1})
        self.assertIn(path, self.memory.instruction('Resuma a primeira página do PDF'))

    def test_restart_retains_pdf_and_page(self):
        path = '/books/hill.pdf'
        self.memory.observe('read_document', {'path': path})
        self.memory.observe('inspect_document', {'path': path, 'content': 'ok'}, {'page': 1})
        restored = NavigationContext(self.db)
        self.assertEqual(restored.resolve('próxima página'), {'path': path, 'page': 2})

    def test_directory_results_and_active_directory(self):
        self.memory.observe('search_directories', {'results': [
            {'index': 1, 'path': '/work/a'}, {'index': 2, 'path': '/work/b'}]}, {'query': 'work'})
        self.assertEqual(len(self.memory.state['last_dir_search']['results']), 2)
        self.memory.observe('open_directory', {'opened_directory': '/work/b'})
        self.assertEqual(self.memory.resolve('abra a pasta')['path'], '/work/b')
        self.assertEqual(len(NavigationContext(self.db).state['last_dir_search']['results']), 2)

    def test_audio_does_not_erase_pdf(self):
        self.memory.observe('search_files', {'results': [{'index': 1, 'path': '/books/hill.pdf'}]})
        self.memory.observe('open_file', {'opened': '/music/song.mp3'})
        self.assertEqual(self.memory.resolve('resuma o PDF')['path'], '/books/hill.pdf')
        self.assertEqual(self.memory.resolve('reproduza a música')['path'], '/music/song.mp3')

    def test_multiple_search_results_do_not_guess_file(self):
        self.memory.observe('search_files', {'results': [{'index': 1, 'path': '/a.pdf'}, {'index': 2, 'path': '/b.pdf'}]})
        self.assertIsNone(self.memory.resolve('resuma o PDF'))

    def test_errors_do_not_override_memory(self):
        self.memory.observe('open_file', {'opened': '/a.pdf'})
        self.memory.observe('open_file', {'error': 'blocked', 'opened': '/b.pdf'})
        self.assertEqual(self.memory.state['active_file'], '/a.pdf')

if __name__ == '__main__':
    unittest.main()
