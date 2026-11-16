"""Baixa exclusivamente pesos ONNX e banco de vozes Kokoro com SHA-256 oficial."""
import hashlib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / 'models' / 'kokoro'
BASE = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/'
FILES = {
    'kokoro-v1.0.onnx': 'beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a',
    'voices-v1.0.bin': 'bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d',
}

def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        path = DEST / name
        if path.exists() and sha256(path) == expected:
            print('[OK] Cache:', name)
            continue
        part = DEST / (name + '.download')
        print('[DOWNLOAD]', name)
        try:
            urllib.request.urlretrieve(BASE + name, str(part))
            got = sha256(part)
            if got != expected:
                raise RuntimeError(f'SHA-256 incorreto em {name}: {got}')
            part.replace(path)
            print('[OK] Validado:', name)
        finally:
            part.unlink(missing_ok=True)
    print('[OK] Modelos preparados. Sintese offline, apos instalar o fonemizador.')

if __name__ == '__main__':
    main()
