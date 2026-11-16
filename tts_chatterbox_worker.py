"""Gerador neural isolado: somente sintetiza arquivos, não faz playback.
Uma instância permanece carregada. O player do processo principal reproduz
um WAV pronto enquanto este worker sintetiza o próximo segmento.
"""
import inspect
import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREFIX = 'JARVIS_TTS_JSON:'
_model = None
_device = None
_checkpoint = None
_reference_key = None

def emit(data):
    print(PREFIX + json.dumps(data, ensure_ascii=False), flush=True)

def load_model(payload):
    global _model, _device, _checkpoint
    checkpoint = str((ROOT / 'models' / 'chatterbox_ptbr').resolve())
    offline = bool(payload.get('offline_only', False))
    if offline:
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
    if _model is not None:
        return _model
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    selected = payload.get('device', 'auto')
    if selected == 'auto':
        selected = 'cuda' if torch.cuda.is_available() else 'cpu'
    if selected == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA indisponível para Chatterbox')
    if 't3_model' not in inspect.signature(ChatterboxMultilingualTTS.from_local).parameters:
        raise RuntimeError('Instalação antiga do Chatterbox: execute atualizar_chatterbox_v3.bat')
    needed = ('t3_pt_br.safetensors', 's3gen.pt', 've.pt', 'grapheme_mtl_merged_expanded_v1.json')
    absent = [x for x in needed if not (Path(checkpoint) / x).is_file()]
    if absent:
        raise RuntimeError('Checkpoint PT-BR incompleto: ' + ', '.join(absent) + '. Execute preparar_checkpoint_ptbr.bat')
    # NUNCA usa from_pretrained() aqui: isso carregaria o checkpoint genérico.
    _model = ChatterboxMultilingualTTS.from_local(checkpoint, device=selected, t3_model='t3_pt_br.safetensors')
    _device, _checkpoint = selected, checkpoint
    print('[PT-BR] Checkpoint dedicado carregado:', checkpoint, file=sys.stderr, flush=True)
    return _model

def run(req):
    global _reference_key
    if req.get('command') == 'ping':
        return {'ok': True, 'ready': True}
    if req.get('command') not in ('generate', 'warmup'):
        raise ValueError('Comando de TTS desconhecido')
    model = load_model(req)
    if req.get('command') == 'warmup':
        return {'ok': True, 'device': _device, 'checkpoint': _checkpoint}
    reference = Path(req['reference']).resolve(strict=True)
    text = str(req['text']).strip()
    output = Path(req['output']).resolve()
    if not text:
        raise ValueError('Texto vazio')
    import soundfile as sf
    ref_key = (str(reference), reference.stat().st_mtime_ns, float(req.get('exaggeration', 0.5)))
    audio_prompt = None
    if ref_key != _reference_key:
        audio_prompt = str(reference)
    # Quando audio_prompt é omitido, condicionais previamente calculadas são reutilizadas.
    wav = model.generate(
        text, language_id=req.get('language', 'pt'),
        audio_prompt_path=audio_prompt,
        exaggeration=float(req.get('exaggeration', 0.5)),
        cfg_weight=float(req.get('cfg_weight', 0.5)),
    )
    _reference_key = ref_key
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix('.part.wav')
    sf.write(str(temp), wav.squeeze().detach().cpu().numpy(), int(model.sr))
    os.replace(temp, output)
    return {'ok': True, 'path': str(output), 'device': _device}

if __name__ == '__main__':
    emit({'ok': True, 'status': 'ready'})
    for line in sys.stdin:
        try:
            emit(run(json.loads(line)))
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            emit({'ok': False, 'error': type(exc).__name__ + ': ' + str(exc)})
