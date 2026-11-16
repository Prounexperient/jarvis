"""Prepara o checkpoint oficial de pt-BR com os recursos comuns do Chatterbox.
Executar uma vez, com internet, no .venv_tts.
"""
from pathlib import Path
import os
import shutil
from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'models' / 'chatterbox_ptbr'
OUT.mkdir(parents=True, exist_ok=True)

special = Path(snapshot_download(
    repo_id='ResembleAI/Chatterbox-Multilingual-pt-br',
    allow_patterns=['t3_pt_br.safetensors', 's3gen_v3.pt', 'grapheme_mtl_merged_expanded_v1.json'],
))
base = Path(snapshot_download(
    repo_id='ResembleAI/chatterbox',
    allow_patterns=['ve.pt'],
))

files = {
    't3_pt_br.safetensors': special / 't3_pt_br.safetensors',
    's3gen.pt': special / 's3gen_v3.pt',
    'grapheme_mtl_merged_expanded_v1.json': special / 'grapheme_mtl_merged_expanded_v1.json',
    've.pt': base / 've.pt',
}
for target_name, source in files.items():
    if not source.is_file():
        raise FileNotFoundError(f'Arquivo esperado ausente no repositório: {source}')
    dst = OUT / target_name
    if not dst.exists() or dst.stat().st_size != source.stat().st_size:
        if dst.exists():
            dst.unlink()
        try:
            os.link(source, dst)  # evita duplicar pesos quando no mesmo volume
        except OSError:
            shutil.copy2(source, dst)
    print('[OK]', dst.name, dst.stat().st_size, 'bytes')
print('\nCheckpoint PT-BR preparado em:', OUT)
print('Atenção: carregamento só funcionará com uma versão compatível do Chatterbox V3.')
