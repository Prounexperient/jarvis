"""Testa o Kokoro isoladamente, sem LM Studio/Whisper. WAV fica em data/tts_cache."""
import sys
import yaml
from pathlib import Path
from kokoro_tts import KokoroTTS

ROOT = Path(__file__).resolve().parent
config = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
settings = config['voice']['kokoro']
settings['use_cache'] = False
engine = KokoroTTS(settings)
try:
    print('[TESTE] abrindo o seu Kokoro com voz', settings.get('voice'))
    engine.warmup()
    print('[TESTE] Gerando frase com acentos e cedilha...')
    engine.speak("Eta caralho, CHUPETA! Tu é brabo demais viu pau no cu. Bom moço se faz de educado e vai arruma uma namoradinha em breve, confia nu pai, sô!")
    print('[OK] Voz reproduzida. Avalie a pronúncia.')
finally:
    engine.close()
