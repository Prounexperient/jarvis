import tempfile
import unittest
from pathlib import Path
from context_state import NavigationContext

class MediaSequenceRegression(unittest.TestCase):
    def test_full_logged_sequence(self):
        with tempfile.TemporaryDirectory() as td:
            nav = NavigationContext(Path(td) / 'memory.db')
            paths = [r'D:\Music Lib\song%d.mp3' % i for i in range(1, 9)]
            nav.observe('search_files_in_directory', {'scope': r'D:\Music Lib', 'results': [{'path': p, 'index': i} for i,p in enumerate(paths,1)]})
            for command, expected in [('Abra o primeiro arquivo', 1), ('Carregue o próximo arquivo', 2),
                                      ('Carregue o próximo arquivo', 3), ('Carregue o primeiro arquivo', 1),
                                      ('Carregue o último arquivo da pasta', 8), ('Reproduza o anterior', 7),
                                      ('Toque o próximo', 8)]:
                result = nav.media_navigation(command)
                self.assertEqual(result['path'], paths[expected-1], command)
                nav.observe('open_file', {'opened': result['path']})
            self.assertEqual(nav.state['active_directory'], r'D:\Music Lib')
            self.assertIsNone(nav.media_navigation('Carregue o primeiro arquivo da pasta Downloads'))
            self.assertIsNone(nav.media_navigation('Explique o primeiro capítulo'))
            self.assertIsNone(nav.media_navigation('Não abra o último arquivo'))
            self.assertEqual(NavigationContext(nav.db_path).media_navigation('Reproduza o anterior')['path'], paths[6])

    def test_failed_open_and_truncated(self):
        with tempfile.TemporaryDirectory() as td:
            nav = NavigationContext(Path(td)/'memory.db')
            paths = [r'D:\Music Lib\song%d.mp3' % i for i in range(1, 4)]
            nav.observe('search_files_in_directory', {'scope': r'D:\Music Lib', 'truncated': True, 'results': [{'path':p} for p in paths]})
            self.assertIn('truncada', nav.media_navigation('Carregue o último arquivo')['error'])
            first = nav.media_navigation('Carregue o primeiro arquivo')
            nav.observe('open_file', {'error':'failed', 'opened':first['path']})
            self.assertIsNone(nav.state['media_sequence']['current_index'])
            nav.observe('open_file', {'opened':first['path']})
            self.assertEqual(nav.media_navigation('Carregue o próximo arquivo')['path'], paths[1])

if __name__ == '__main__': unittest.main()
