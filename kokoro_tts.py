"""Kokoro ONNX isolado. Reutiliza a fila/cachê de WAVs do NeuralTTS v0.5."""
import re
import hashlib
import json
import queue
import subprocess
import threading
from pathlib import Path
from speech_text_processor import SpeechTextProcessor
from speech_realization import SpeechRealizationLayer
from neural_tts import (
    NeuralTTS,
    SpeechPipeline,
    SentenceChunker,
    clean_speech,
    ROOT,
)


class KokoroSentenceChunker(SentenceChunker):
    """Fragmentador PT-BR que preserva limites de linhas e listas."""

    def _prepare_line(self, line):
        line = line.strip()

        # Remove marcadores de títulos e listas Markdown.
        line = re.sub(r'^#{1,6}\s+', '', line)
        line = re.sub(r'^(?:[-*•]|\d+[.)])\s+', '', line)

        line = clean_speech(line)

        if not line:
            return ''

        # Uma linha de lista ou título precisa de pausa própria.
        if line.endswith(':'):
            line = line[:-1].rstrip() + '.'
        elif line[-1] not in '.!?;':
            line += '.'

        return line

    def _split_long(self, text):
        ready = []

        while len(text) > self.limit:
            cut = text.rfind(' ', 0, self.limit + 1)

            if cut <= 0:
                cut = text.find(' ', self.limit)

            if cut <= 0:
                break

            part = text[:cut].strip()
            text = text[cut:].lstrip()

            if part:
                if part[-1] not in '.,;:!?':
                    part += ','
                ready.append(part)

        if text.strip():
            ready.append(text.strip())

        return ready

    def feed(self, text, final=False):
        self.buf += text.replace('\r\n', '\n').replace('\r', '\n')
        ready = []

        # Cada linha completa pode representar um item ou parágrafo.
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            prepared = self._prepare_line(line)

            if prepared:
                ready.extend(self._split_long(prepared))

        # Durante o streaming, libera frases completas.
        pattern = r"""[.!?]["”']?(?=\s)"""

        while True:
            match = re.search(pattern, self.buf)

            if not match:
                break

            part = self.buf[:match.end()]
            self.buf = self.buf[match.end():].lstrip()

            prepared = clean_speech(part)

            if prepared:
                ready.extend(self._split_long(prepared))

        # Evita acumular trechos excessivamente longos.
        if len(self.buf) >= self.limit:
            cut = self.buf.rfind(' ', 0, self.limit + 1)

            if cut > 0:
                part = clean_speech(self.buf[:cut])
                self.buf = self.buf[cut:].lstrip()

                if part:
                    ready.extend(self._split_long(part))

        if final and self.buf.strip():
            prepared = self._prepare_line(self.buf)
            self.buf = ''

            if prepared:
                ready.extend(self._split_long(prepared))

        return ready


class KokoroSpeechPipeline(SpeechPipeline):
    """Pipeline exclusivo do Kokoro."""

    def __init__(self, engine):
        super().__init__(engine)

        # Antes de qualquer submit(), seleciona o novo fragmentador.
        self.chunker = KokoroSentenceChunker(
            engine.settings.get('max_chunk_chars', 220)
        )



class KokoroTTS(NeuralTTS):
    def _start(self):
        if self.process and self.process.poll() is None:
            return
        python = ROOT / '.venv_kokoro' / 'Scripts' / 'python.exe'
        if not python.is_file():
            raise FileNotFoundError('Ambiente .venv_kokoro ausente: execute instalar_kokoro.bat')
        self.events = queue.Queue()
        self.process = subprocess.Popen(
            [str(python), '-u', str(ROOT / 'tts_kokoro_worker.py')],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8',
            errors='replace', bufsize=1,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        threading.Thread(target=self._reader, args=(self.process,), daemon=True).start()
        self._recv(30)

    def _cache_path_kokoro(self, text):
        model = ROOT / 'models' / 'kokoro' / 'kokoro-v1.0.onnx'
        voices = ROOT / 'models' / 'kokoro' / 'voices-v1.0.bin'
        key = {
            'engine': 'kokoro-onnx-v2-utf8-fixed',
            'text': text,
            'voice': self.settings.get('voice', 'pm_alex'),
            'speed': self.settings.get('speed', 1.0),
            'model_mtime': model.stat().st_mtime_ns if model.exists() else None,
            'voices_mtime': voices.stat().st_mtime_ns if voices.exists() else None,
        }
        raw = json.dumps(key, ensure_ascii=False, sort_keys=True)
        return self.cache / (hashlib.sha256(raw.encode('utf-8')).hexdigest() + '.wav')

    def _generate(self, text):
        path = self._cache_path_kokoro(text)

        # Permite desativar o cache durante testes
        use_cache = self.settings.get('use_cache', True)

        if use_cache and path.is_file() and path.stat().st_size > 44:
            print('[KOKORO CACHE]', text[:70])
            return path

        self._call({
            'command': 'generate',
            'text': text,
            'output': str(path),
            'voice': self.settings.get('voice', 'pm_alex'),
            'speed': float(self.settings.get('speed', 1.0)),
        })

        if not path.is_file() or path.stat().st_size <= 44:
            raise RuntimeError('Kokoro não produziu um WAV válido.')

        return path

    def warmup(self):
        return self._call({'command': 'warmup'})

    def begin_stream(self):
        if self.disabled:
            raise RuntimeError('Kokoro desabilitado')

        processor = SpeechRealizationLayer(
            mode=self.settings.get('tts_stream_mode', 'sentence'),
            safety_limit=self.settings.get('sentence_safety_chars', 650),
            enabled=self.settings.get('speech_realization_enabled', True),
        )

        return SpeechPipeline(
            self,
            chunker=processor
        )