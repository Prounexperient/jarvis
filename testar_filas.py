"""Testes locais sem TTS neural, LM Studio ou GPU."""
import sys
import threading
import time
import types
import unittest
from neural_tts import SentenceChunker, SpeechPipeline, clean_speech

class TestTTS(unittest.TestCase):
    def test_acentos_e_markdown(self):
        self.assertEqual(clean_speech('A **ação** é ótima!'), 'A ação é ótima!')

    def test_decimal(self):
        c = SentenceChunker()
        self.assertEqual(c.feed('O resultado é 3.14. Próxima frase. '), ['O resultado é 3.14.', 'Próxima frase.'])

    def test_streaming(self):
        c = SentenceChunker()
        self.assertEqual(c.feed('Olá, '), [])
        self.assertEqual(c.feed('Jarvis. Agora '), ['Olá, Jarvis.'])
        self.assertEqual(c.feed('vamos. ', final=True), ['Agora vamos.'])

    def test_fila_reproduz_enquanto_gera(self):
        stages = []
        original = sys.modules.get('winsound')
        fake = types.ModuleType('winsound')
        def play(file, flags):
            stages.append(('playing', file, time.monotonic()))
            time.sleep(.11)
            stages.append(('finished_play', file, time.monotonic()))
        fake.PlaySound = play
        fake.SND_FILENAME = 1
        sys.modules['winsound'] = fake
        class Engine:
            settings = {'max_chunk_chars': 195}
            def _generate(self, text):
                stages.append(('generating', text, time.monotonic()))
                time.sleep(.08)
                return text
        try:
            pipe = SpeechPipeline(Engine())
            pipe.submit('Primeira frase. Segunda frase. ')
            pipe.finish()
            self.assertEqual(pipe.played, 2)
            gen_second = next(x[2] for x in stages if x[0]=='generating' and 'Segunda' in x[1])
            play_first = next(x[2] for x in stages if x[0]=='playing' and 'Primeira' in x[1])
            play_end = next(x[2] for x in stages if x[0]=='finished_play' and 'Primeira' in x[1])
            self.assertLess(gen_second, play_end)
        finally:
            if original is None:
                sys.modules.pop('winsound', None)
            else:
                sys.modules['winsound'] = original

if __name__ == '__main__':
    unittest.main()
