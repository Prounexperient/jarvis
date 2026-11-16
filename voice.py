"""Reconhecimento offline via Whisper para wake word e comandos; TTS Piper/SAPI."""
import re
import unicodedata
from pathlib import Path
import subprocess
import tempfile
import wave
import numpy as np
from faster_whisper import WhisperModel


class Speech:
    def __init__(self, config):
        self.config = config

        s = config['speech']
        print('[VOZ] Carregando Whisper.')

        self.whisper = WhisperModel(
            s['whisper_model'],
            device=s['whisper_device'],
            compute_type=s['whisper_compute_type'],
            local_files_only=True
        )

        self.neural_tts = None

        v = config.get('voice', {})
        provider = v.get('provider', 'sapi').lower()

        if v.get('enabled', True):
            if provider == 'kokoro':
                from kokoro_tts import KokoroTTS
                self.neural_tts = KokoroTTS(
                    v.get('kokoro', {})
                )

            elif provider == 'chatterbox':
                from neural_tts import NeuralTTS
                self.neural_tts = NeuralTTS(
                    v.get('chatterbox', {})
                )

            if self.neural_tts is not None:
                print(
                    '[VOZ] Sintetizador selecionado:',
                    provider
                )

                settings = v.get(provider, {})

                if settings.get('preload_on_start', False):
                    import threading

                    threading.Thread(
                        target=self._preload_voice,
                        daemon=True
                    ).start()

    def _preload_voice(self):
        try:
            self.neural_tts.warmup()

            provider = self.config['voice'].get(
                'provider', 'neural'
            )

            print(
                f'[VOZ] Modelo {provider} pré-carregado.'
            )

        except Exception as exc:
            print(
                '[VOZ] Falha no pré-carregamento:',
                type(exc).__name__,
                exc
            )

    def close(self):
        if self.neural_tts is not None:
            self.neural_tts.close()

    @staticmethod
    def _normalizar(texto):
        texto = unicodedata.normalize('NFKD', texto.casefold())
        texto = ''.join(ch for ch in texto if not unicodedata.combining(ch))
        return re.findall(r'\w+', texto)

    def detect_wake(self, samples):
        """Transcreve uma fala curta e verifica a palavra isolada, sem fuzzy matching."""
        detected = self.transcribe(samples)
        if detected:
            print('[WAKE WHISPER]', repr(detected))
        termo = self._normalizar(self.config['wake']['phrase'])
        tokens = self._normalizar(detected)
        if not termo:
            return False
        n = len(termo)
        return any(tokens[i:i+n] == termo for i in range(len(tokens)-n+1))

    def transcribe(self, samples):
        segments, _ = self.whisper.transcribe(
            np.asarray(samples,dtype=np.float32), language=self.config['speech']['language'],
            beam_size=3, vad_filter=True, condition_on_previous_text=False)
        return ' '.join(s.text.strip() for s in segments).strip()

    def start_neural_stream(self):
        v = self.config['voice']

        if not v.get('enabled', True):
            return None

        provider = v.get('provider', 'sapi').lower()

        if provider not in ('kokoro', 'chatterbox'):
            return None

        if self.neural_tts is None:
            if provider == 'kokoro':
                from kokoro_tts import KokoroTTS

                self.neural_tts = KokoroTTS(
                    v.get('kokoro', {})
                )

            elif provider == 'chatterbox':
                from neural_tts import NeuralTTS

                self.neural_tts = NeuralTTS(
                    v.get('chatterbox', {})
                )

        return self.neural_tts.begin_stream()

    def speak_legacy(self, text):
        """Fallback Windows SAPI/Piper, também usado quando TTS neural falha."""
        import re
        from neural_tts import clean_speech
        text = clean_speech(text)
        v = self.config['voice']
        if not text:
            return
        executable, model = Path(v.get('piper_executable') or ''), Path(v.get('piper_model') or '')
        if v.get('piper_executable') and v.get('piper_model') and executable.is_file() and model.is_file():
            with tempfile.TemporaryDirectory() as tmp:
                out = str(Path(tmp) / 'voice.wav')
                subprocess.run([str(executable), '--model', str(model), '--output_file', out],
                               input=text, text=True, encoding='utf-8', capture_output=True, check=True)
                import winsound
                winsound.PlaySound(out, winsound.SND_FILENAME)
            return
        import win32com.client
        win32com.client.Dispatch('SAPI.SpVoice').Speak(text)

    def speak(self, text):
        if not self.config['voice']['enabled'] or not text:
            return
        stream = None
        try:
            stream = self.start_neural_stream()
            if stream is not None:
                stream.submit(text)
                stream.finish()
                return
        except Exception as exc:
            print(
                '[VOZ] Erro TTS neural:',
                type(exc).__name__,
                exc
            )
            if stream is not None and stream.played:
                return  # não repetir frases que já foram reproduzidas
        self.speak_legacy(text)
