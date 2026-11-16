"""Testes offline da etapa 14.1.4: python -m unittest test_etapa_14_1_4 -v"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from speech_text_processor import SpeechTextProcessor
from speech_realization import SpeechRealizationLayer
import tools


class Etapa1414(unittest.TestCase):
    def test_compatibilidade(self):
        p = SpeechTextProcessor(mode='sentence', safety_limit=650)
        self.assertTrue(callable(p.feed))
        self.assertTrue(callable(p.process))
        self.assertEqual(p.process('A NVIDIA foi fundada em 1993.'), 'A NVIDIA foi fundada em mil novecentos e noventa e três.')

    def test_caminho_pasta(self):
        s = SpeechTextProcessor().process(r'Abri `D:\Music Lib` no Explorador.')
        self.assertIn('disco D, pasta Music Lib', s)
        self.assertNotIn('D:\\', s)

    def test_caminho_arquivo(self):
        s = SpeechTextProcessor().process(r'`C:\Users\Rod\Music\track.mp3`')
        self.assertEqual(s, 'disco C, arquivo track')

    def test_math_latex(self):
        s = SpeechTextProcessor().process(r'O valor de \(5^{\sqrt{5}}\) é 36,5548.')
        self.assertIn('cinco elevado à raiz quadrada de cinco', s)
        self.assertNotIn('sqrt', s)
        s = SpeechTextProcessor().process(r'\(1{,}5^{\sqrt{1{,}5}}\)')
        self.assertIn('um vírgula cinco elevado à raiz quadrada de um vírgula cinco', s)

    def test_stream_original(self):
        p = SpeechTextProcessor(mode='sentence')
        self.assertEqual(p.feed('Olá, '), [])
        self.assertEqual(p.feed('Jarvis. Como vai? '), ['Olá, Jarvis.', 'Como vai?'])
        self.assertEqual(p.feed('', final=True), [])

    def test_speech_realizer_preserva_caminho(self):
        layer = SpeechRealizationLayer(mode='full')
        spoken = layer.feed('Abri `D:\\Music Lib` no Explorador.', final=True)
        self.assertIn('Music Lib', ' '.join(spoken))
        self.assertNotIn('um caminho local', ' '.join(spoken))

    def test_busca_pastas_por_conteudo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'Audios').mkdir()
            (root / 'Outros').mkdir()
            (root / 'Audios' / 'a.mp3').write_bytes(b'')
            (root / 'Audios' / 'b.flac').write_bytes(b'')
            (root / 'Outros' / 'c.txt').write_bytes(b'')
            config = {'paths': {'max_search_results': 12}, 'file_search': {'timeout_seconds': 30}}
            with patch.object(tools, '_resolve_roots', return_value=[root]):
                result = tools.search_directories_by_content(config)
            self.assertEqual(len(result['results']), 1)
            self.assertEqual(result['results'][0]['name'], 'Audios')
            self.assertEqual(result['results'][0]['count'], 2)
            self.assertEqual(tools.get_last_search_kind(), 'directories')
            self.assertEqual(tools.get_last_search_paths(), (str(root/'Audios'),))

    def test_ferramenta_registrada(self):
        self.assertIn('search_directories_by_content', tools.FUNCTIONS)
        self.assertTrue(any(x['function']['name']=='search_directories_by_content' for x in tools.SCHEMAS))


if __name__ == '__main__':
    unittest.main()
