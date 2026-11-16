"""Baixa/carrega Chatterbox V3 uma vez e testa GPU/CPU sem reproduzir áudio."""
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
print('PyTorch:', torch.__version__)
print('CUDA disponivel:', torch.cuda.is_available())
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print('Preparando Chatterbox Multilingual V3 em',device)
model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model='v3')
print('[OK] Modelo carregado; sample rate:',model.sr)
print('Os pesos deverao ficar no cache local para proximos usos.')
