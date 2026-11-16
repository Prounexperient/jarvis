"""Teste isolado do TTS sem carregar LM Studio/Whisper."""
import yaml
from neural_tts import NeuralTTS
from pathlib import Path
cfg = yaml.safe_load((Path(__file__).parent / 'config.yaml').read_text(encoding='utf-8'))['voice']['chatterbox']
tts = NeuralTTS(cfg)
try:
    print('Gerando a voz de teste...')
    tts.speak('Bom dia. Eu sou Jarvis. Estou pronto para auxiliar você em suas tarefas.')
    print('[OK] Voz sintetizada e reproduzida.')
finally:
    tts.close()
