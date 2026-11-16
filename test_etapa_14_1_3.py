
import unittest
from unittest.mock import patch
from speech_text_processor import SpeechTextProcessor
from context_state import NavigationContext
from contextual_actions import resolve_action

class Tests(unittest.TestCase):
    def test_preserve_subject_and_facts(self):
        s = SpeechTextProcessor().process('A NVIDIA foi fundada em **15 de abril de 1993**.')
        self.assertEqual(s, 'A NVIDIA foi fundada em 15 de abril de 1993.')
        self.assertNotIn('Fui fundada', s)

    def test_path_for_speech(self):
        s = SpeechTextProcessor().process('Abri `D:\\Music Lib` no Explorador.')
        self.assertIn('Music Lib', s)
        self.assertNotIn('D:\\', s)

    def test_navigation(self):
        n = NavigationContext()
        n.observe('open_directory', {'opened_directory':'D:\\Music Lib'})
        self.assertIn('D:\\Music Lib', n.instruction())
        n.observe('search_files_in_directory', {'scope':'D:\\Music Lib', 'results':[]})
        self.assertEqual(n.active_directory, 'D:\\Music Lib')
        n.observe('open_directory', {'error':'falha'})
        self.assertEqual(n.active_directory, 'D:\\Music Lib')

    def test_contextual_ordinal(self):
        self.assertEqual(resolve_action('Abra o segundo', ['a','b']), ('open_search_result', 2))

    def test_context_guard(self):
        paths = ['D:\\Music Lib', 'D:\\AI Music']
        self.assertIsNone(resolve_action('Abra o segundo áudio desta pasta', paths))
        self.assertIsNone(resolve_action('Da pasta Music Lib, abra o segundo arquivo de música', paths))

if __name__ == '__main__':
    unittest.main()
