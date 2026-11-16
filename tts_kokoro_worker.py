"""Worker residente Kokoro: texto PT-BR -> fonemas espeak-ng -> ONNX -> WAV.
Rodar somente com .venv_kokoro. Usa protocolo JSON por linha do JARVIS.
"""
import json
import os
import sys
import traceback
from pathlib import Path
from kokoro_onnx import Kokoro
from misaki.espeak import EspeakG2P
from phonemizer.backend.espeak.wrapper import EspeakWrapper
from soundfile import write
sys.stdin.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent
PREFIX = 'JARVIS_TTS_JSON:'
MODEL_DIR = ROOT / 'models' / 'kokoro'
_model = None
_g2p = None


def emit(data):
    print(PREFIX + json.dumps(data, ensure_ascii=False), flush=True)


def load():
    global _model, _g2p
    if _model is not None:
        return _model, _g2p
    model_path = MODEL_DIR / 'kokoro-v1.0.onnx'
    voice_path = MODEL_DIR / 'voices-v1.0.bin'
    missing = [p.name for p in (model_path, voice_path) if not p.is_file() or p.stat().st_size == 0]
    if missing:
        raise FileNotFoundError('Arquivos Kokoro ausentes: ' + ', '.join(missing) + '. Execute preparar_kokoro.bat')

    ESPEAK_ROOT = Path(r"C:\Program Files (x86)\eSpeak NG")
    ESPEAK_DLL = ESPEAK_ROOT / "libespeak-ng.dll"
    ESPEAK_DATA = ESPEAK_ROOT / "espeak-ng-data"

    if not ESPEAK_DLL.is_file():
        raise FileNotFoundError(f"DLL ausente: {ESPEAK_DLL}")

    if not (ESPEAK_DATA / "phontab").is_file():
        raise FileNotFoundError(
            f"Arquivo phontab ausente: {ESPEAK_DATA}"
        )

    # O eSpeak NG acrescenta "espeak-ng-data" internamente
    # neste cenário. Portanto, informamos o diretório pai.
    os.environ["ESPEAK_DATA_PATH"] = str(ESPEAK_ROOT)

    EspeakWrapper.set_library(str(ESPEAK_DLL))
    EspeakWrapper.set_data_path(str(ESPEAK_ROOT))

    _g2p = EspeakG2P(language="pt-br")
    _model = Kokoro(str(model_path), str(voice_path))
    print('[KOKORO] Modelo ONNX e fonemizador pt-br carregados.', file=sys.stderr, flush=True)
    return _model, _g2p


def run(req):
    command = req.get('command')
    if command == 'ping':
        return {'ok': True, 'ready': True}
    if command not in ('generate', 'warmup'):
        raise ValueError('Comando Kokoro desconhecido')
    model, g2p = load()
    if command == 'warmup':
        return {'ok': True}
    text = str(req['text']).strip()
    if not text:
        raise ValueError('Texto vazio')
    voice = str(req.get('voice', 'pm_alex'))
    if voice not in ('pm_alex', 'pm_santa', 'pf_dora'):
        raise ValueError('Voz PT-BR desconhecida: ' + voice)
    speed = float(req.get('speed', 1.0))
    if not (0.7 <= speed <= 1.3):
        raise ValueError('Velocidade deve estar entre 0.7 e 1.3')

    print(
        "[DEBUG] TEXTO RECEBIDO:",
        ascii(text),
        file=sys.stderr,
        flush=True
    )

    # Converter o texto em fonemas
    resultado = g2p(text)

    if isinstance(resultado, str):
        phonemes = resultado
    elif isinstance(resultado, (tuple, list)):
        phonemes = resultado[0]
    else:
        raise TypeError(
            f"Retorno inesperado: {type(resultado)}"
        )

    if not isinstance(phonemes, str) or not phonemes.strip():
        raise ValueError("Fonemas inválidos.")

    # Exibir somente no log, sem modificar os fonemas

    print(
        "[KOKORO] Fonemas:",
        ascii(phonemes),
        file=sys.stderr,
        flush=True
    )

    # Gerar áudio interpretando a entrada como fonemas
    samples, sample_rate = model.create(
        phonemes,
        voice=req.get("voice", "pm_alex"),
        speed=float(req.get("speed", 1.0)),
        is_phonemes=True
    )

    print(
        "[DEBUG] Fonemas:",
        ascii(phonemes),
        file=sys.stderr,
        flush=True
    )

    print(
        "[DEBUG] Contem escapes literais:",
        "\\u" in phonemes or "\\x" in phonemes,
        file=sys.stderr,
        flush=True
    )

    out = Path(req['output']).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.part.wav')
    write(str(tmp), samples, sample_rate, subtype='PCM_16')
    os.replace(tmp, out)
    return {'ok': True, 'path': str(out), 'voice': voice}

if __name__ == '__main__':
    emit({'ok': True, 'status': 'ready'})
    for line in sys.stdin:
        try:
            emit(run(json.loads(line)))
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            emit({'ok': False, 'error': type(exc).__name__ + ': ' + str(exc)})
