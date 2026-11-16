import tempfile
import unittest
from pathlib import Path
from context_state import NavigationContext

class MediaNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory = NavigationContext(Path(self.temp.name) / 'nav.db')
        self.items = [{'index': i, 'path': 'D:\\Music Lib\\track%d.mp3' % i} for i in range(1, 6)]
        self.memory.observe('search_files_in_directory', {'results': self.items, 'scope': 'D:\\Music Lib', 'truncated': False}, {'directory': 'D:\\Music Lib', 'extension': 'mp3'})
        self.memory.observe('open_search_result', {'opened': self.items[3]['path']}, {'index': 4})

    def tearDown(self):
        self.temp.cleanup()

    def test_next_and_previous(self):
        self.assertEqual(self.memory.media_navigation('Agora reproduza o próximo arquivo')['path'], self.items[4]['path'])
        self.assertEqual(self.memory.media_navigation('Toque a faixa anterior')['path'], self.items[2]['path'])

    def test_progress_and_persistence(self):
        self.memory.observe('open_file', {'opened': self.items[4]['path']}, {'path': self.items[4]['path']})
        self.assertIn('Não há arquivo', self.memory.media_navigation('Reproduza o próximo arquivo')['error'])
        restored = NavigationContext(self.memory.db_path)
        self.assertEqual(restored.media_navigation('Reproduza o anterior')['path'], self.items[3]['path'])

    def test_no_guess_and_no_unwanted_actions(self):
        self.assertIsNone(self.memory.media_navigation('Não reproduza o próximo arquivo'))
        self.assertIsNone(self.memory.media_navigation('Explique o próximo capítulo'))
        self.assertIsNone(self.memory.media_navigation('Qual será a próxima música?'))

    def test_other_search_does_not_discard_sequence(self):
        self.memory.observe('search_files', {'results': [{'index': 1, 'path': '/book.pdf'}]})
        self.assertEqual(self.memory.media_navigation('Reproduza o próximo áudio')['path'], self.items[4]['path'])

    def test_failed_open_does_not_advance(self):
        self.memory.observe('open_file', {'error': 'denied', 'opened': self.items[4]['path']})
        self.assertEqual(self.memory.media_navigation('Reproduza o próximo arquivo')['path'], self.items[4]['path'])

if __name__ == '__main__':
    unittest.main()
