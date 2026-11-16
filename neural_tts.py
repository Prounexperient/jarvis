"""Fila de TTS: geração e playback em threads diferentes; cache local.
Não cria threads de GPU concorrentes; a síntese é sequencial para poupar VRAM.
"""
import hashlib
import json
import queue
import re
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREFIX = 'JARVIS_TTS_JSON:'
END = object()


def clean_speech(text):
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'(?m)^\s{0,3}#{1,6}\s+', '', text)
    text = re.sub(r'(?m)^\s*[-•]\s+', '', text)
    text = re.sub(r'\*\*(.*?)\*\*|__(.*?)__', lambda m: m.group(1) or m.group(2), text)
    text = text.replace('`', '').replace('*', '')
    return re.sub(r'\s+', ' ', text).strip()


class SentenceChunker:
    def __init__(self, limit=195):
        self.buf = ''
        self.limit = max(50, int(limit))

    def feed(self, text, final=False):
        self.buf += text
        ready = []
        while self.buf:
            # Corte somente se houver espaço APÓS o sinal; números decimais não quebram.
            m = re.search(r'[.!?;:](?:["”\']?)(?=\s)', self.buf)
            if m:
                end = m.end()
                if end <= self.limit:
                    part, self.buf = self.buf[:end], self.buf[end:].lstrip()
                    if clean_speech(part):
                        ready.append(clean_speech(part))
                    continue
            if len(self.buf) >= self.limit:
                cut = self.buf.rfind(' ', 0, self.limit + 1)
                if cut <= 0:
                    next_space = self.buf.find(' ', self.limit)
                    if next_space != -1:
                        cut = next_space
                    elif not final:
                        break
                    else:
                        cut = len(self.buf)
                part, self.buf = self.buf[:cut], self.buf[cut:].lstrip()
                if clean_speech(part):
                    ready.append(clean_speech(part))
                continue
            break
        if final and self.buf.strip():
            ready.append(clean_speech(self.buf))
            self.buf = ''
        return [x for x in ready if x]


class NeuralTTS:
    def __init__(self, settings):
        self.settings = settings
        self.process = None
        self.events = queue.Queue()
        self.lock = threading.RLock()
        self.cache = ROOT / 'data' / 'tts_cache'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.disabled = False

    def _reader(self, process):
        for line in process.stdout:
            line = line.rstrip()
            if line.startswith(PREFIX):
                try:
                    self.events.put(json.loads(line[len(PREFIX):]))
                except json.JSONDecodeError:
                    pass
            elif line:
                print('[CHATTERBOX]', line[:600])
        self.events.put({'ok': False, 'error': 'Processo Chatterbox finalizado'})

    def _recv(self, seconds):
        try:
            answer = self.events.get(timeout=seconds)
        except queue.Empty:
            raise TimeoutError('Chatterbox não respondeu no prazo.')
        if not answer.get('ok'):
            raise RuntimeError(answer.get('error', 'Erro desconhecido do TTS'))
        return answer

    def _start(self):
        if self.process and self.process.poll() is None:
            return
        python = ROOT / '.venv_tts' / 'Scripts' / 'python.exe'
        if not python.is_file():
            raise FileNotFoundError('Ambiente .venv_tts ausente')
        self.events = queue.Queue()
        self.process = subprocess.Popen(
            [str(python), '-u', str(ROOT / 'tts_chatterbox_worker.py')], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        threading.Thread(target=self._reader, args=(self.process,), daemon=True).start()
        self._recv(30)

    def _call(self, payload):
        with self.lock:
            self._start()
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + '\n')
            self.process.stdin.flush()
            return self._recv(float(self.settings.get('timeout_seconds', 600)))

    def _reference(self):
        path = Path(self.settings.get('reference_audio', 'voices/jarvis_reference.wav'))
        path = (ROOT / path).resolve() if not path.is_absolute() else path
        if not path.is_file():
            raise FileNotFoundError(f'Referência ausente: {path}')
        return path

    def _cache_path(self, text, reference):
        st = reference.stat()
        key = json.dumps({
            'text': text, 'model': 'Chatterbox-Multilingual-pt-br',
            'ref': str(reference), 'refsize': st.st_size, 'refmtime': st.st_mtime_ns,
            'language': self.settings.get('language', 'pt'),
            'exaggeration': self.settings.get('exaggeration', .5),
            'cfg_weight': self.settings.get('cfg_weight', .5),
        }, ensure_ascii=False, sort_keys=True)
        return self.cache / (hashlib.sha256(key.encode('utf-8')).hexdigest() + '.wav')

    def _generate(self, text):
        reference = self._reference()
        path = self._cache_path(text, reference)
        if path.is_file() and path.stat().st_size > 44:
            print('[TTS CACHE]', text[:70]); return path
        self._call({
            'command': 'generate', 'text': text, 'output': str(path),
            'reference': str(reference), 'language': self.settings.get('language', 'pt'),
            'device': self.settings.get('device', 'auto'),
            'exaggeration': self.settings.get('exaggeration', .5),
            'cfg_weight': self.settings.get('cfg_weight', .5),
            'offline_only': self.settings.get('offline_only', True),
        })
        return path

    def warmup(self):
        return self._call({
            'command': 'warmup',
            'device': self.settings.get('device', 'auto'),
            'offline_only': self.settings.get('offline_only', True),
        })

    def begin_stream(self):
        if self.disabled:
            raise RuntimeError('Chatterbox desabilitado depois de um erro; reinicie para tentar de novo')
        return SpeechPipeline(self)

    def speak(self, text):
        pipe = self.begin_stream()
        pipe.submit(text)
        pipe.finish()

    def close(self):
        proc = self.process
        self.process = None
        if proc and proc.poll() is None:
            proc.terminate()


class SpeechPipeline:
    def __init__(self, engine, chunker=None):
        self.engine = engine
        self.incoming = queue.Queue(maxsize=12)
        self.playback = queue.Queue(maxsize=3)
        self.failures = []
        self.played = 0
        self.chunker = (
            chunker
            if chunker is not None
            else SentenceChunker(engine.settings.get('max_chunk_chars', 195))
        )
        self.gen_thread = threading.Thread(target=self._generator, daemon=True)
        self.play_thread = threading.Thread(target=self._player, daemon=True)
        self.gen_thread.start(); self.play_thread.start()

    def submit(self, text):
        for sentence in self.chunker.feed(text):
            while True:
                if self.failures:
                    raise RuntimeError(str(self.failures[0]))
                try:
                    self.incoming.put(sentence, timeout=0.2)
                    break
                except queue.Full:
                    continue

    def _generator(self):
        try:
            while True:
                text = self.incoming.get()
                if text is END:
                    break
                if self.failures:
                    break
                self.playback.put(self.engine._generate(text))
        except Exception as exc:
            self.failures.append(exc)
        finally:
            self.playback.put(END)

    def _player(self):
        try:
            import winsound
            while True:
                item = self.playback.get()
                if item is END:
                    return
                winsound.PlaySound(str(item), winsound.SND_FILENAME)
                self.played += 1
        except Exception as exc:
            self.failures.append(exc)

    def finish(self):
        for sentence in self.chunker.feed('', final=True):
            self.incoming.put(sentence)
        self.incoming.put(END)
        self.gen_thread.join()
        self.play_thread.join()
        if self.failures:
            raise RuntimeError(str(self.failures[0]))
