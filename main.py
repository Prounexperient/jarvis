"""JARVIS local v0.4: ativação inicial por F9/Whisper e sessão conversacional contínua."""
import argparse
import queue
from pathlib import Path
import re
import threading
import time
import unicodedata

import numpy as np
import sounddevice as sd
import yaml
from pynput import keyboard

from agent import Agent
from task_runtime import TaskRuntime
from model_commands import parse_model_command, execute_model_command, ModelCommand

BASE = Path(__file__).resolve().parent


def load_config():
    return yaml.safe_load((BASE / 'config.yaml').read_text(encoding='utf-8'))


def normalize(text):
    """Normalização conservadora somente para comandos explícitos de encerramento."""
    text = unicodedata.normalize('NFKD', text.casefold())
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', text)).strip()


def is_session_end(text, config):
    normalized = normalize(text)
    wake = normalize(config.get('wake', {}).get('phrase', 'jarvis'))
    if wake and normalized.startswith(wake + ' '):
        normalized = normalized[len(wake) + 1:]
    phrases = config.get('conversation', {}).get('end_phrases', [
        'pode descansar', 'jarvis pode descansar', 'encerrar conversa',
        'encerre a conversa', 'voltar ao modo de espera', 'modo de espera',
    ])
    return normalized in {normalize(x) for x in phrases}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--text', action='store_true', help='Modo texto para testar o agente')
    args = parser.parse_args()
    config = load_config()
    agent = Agent(config)
    if args.text:
        print('JARVIS - texto. Digite sair para terminar.')
        while True:
            try:
                request = input('Você> ').strip()
                if request.casefold() in {'sair', 'exit', 'quit'}:
                    break
                if request:
                    cmd = parse_model_command(request, config.get('wake', {}).get('phrase', 'jarvis'))
                    print('JARVIS>', execute_model_command(cmd, agent, announce=lambda msg: print('JARVIS>', msg)) if cmd else agent.ask(request))
            except (KeyboardInterrupt, EOFError):
                break
            except Exception as exc:
                print('[ERRO]', type(exc).__name__, exc)
        return

    from voice import Speech
    speech = Speech(config)
    audio_queue = queue.Queue(maxsize=200)
    activate = threading.Event()
    model_key_queue = queue.Queue(maxsize=2)
    busy = threading.Event()
    speaking = threading.Event()
    conversation = config.get('conversation', {})
    continuous = conversation.get('enabled', True)
    timeout_seconds = float(conversation.get('timeout_seconds', 120))
    if timeout_seconds <= 0:
        raise ValueError('conversation.timeout_seconds deve ser maior que zero.')

    def clear_audio():
        while True:
            try:
                audio_queue.get_nowait()
            except queue.Empty:
                break

    def say(text):
        speaking.set()
        clear_audio()
        try:
            speech.speak(text)
        finally:
            clear_audio()
            speaking.clear()

    def on_press(key):
        if busy.is_set() or speaking.is_set():
            return
        if key == keyboard.Key.f9:
            activate.set()
        elif key in (keyboard.Key.f10, keyboard.Key.f11):
            try:
                model_key_queue.put_nowait('gpt_oss' if key == keyboard.Key.f10 else 'qwen')
            except queue.Full:
                pass

    def callback(indata, frames, timing, status):
        if speaking.is_set():
            return
        try:
            audio_queue.put_nowait(bytes(indata))
        except queue.Full:
            pass

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    rate = config['speech']['sample_rate']
    opts = config['speech']
    wake_opts = config['wake']
    wake_recorded = []
    wake_start = 0.0
    wake_last_voice = 0.0
    session_active = False
    idle_since = 0.0
    listening_announced = False

    print('\nJARVIS v0.5 ativo. Pressione F9 ou diga "Jarvis". Ctrl+C encerra.')
    print(f'[CONVERSA] Contínua: {continuous}; timeout: {timeout_seconds:g} segundos.')
    print('F10: GPT-OSS | F11: Qwen | F9: ativar conversa.')
    print('Recomendado usar fones para evitar que a voz sintetizada seja recapturada.')
    try:
        with sd.RawInputStream(samplerate=rate, blocksize=1600, dtype='int16', channels=1, callback=callback):
            while True:
                # Teclas administrativas são processadas pela thread principal,
                # nunca pelo callback do teclado ou durante uma resposta.
                if not busy.is_set() and not speaking.is_set():
                    try:
                        target = model_key_queue.get_nowait()
                    except queue.Empty:
                        pass
                    else:
                        busy.set()
                        speaking.set()
                        clear_audio()
                        try:
                            answer = execute_model_command(
                                ModelCommand('switch', target), agent,
                                announce=lambda msg: (print('JARVIS>', msg), say(msg)),
                            )
                            print('JARVIS>', answer)
                            say(answer)
                        finally:
                            clear_audio()
                            speaking.clear()
                            busy.clear()
                            idle_since = time.monotonic()
                        continue
                # ESTADO 1: aguarda a ativação, com F9 ou Whisper identificando "Jarvis".
                if not session_active:
                    if not activate.is_set():
                        if not wake_opts['enabled']:
                            try:
                                audio_queue.get(timeout=0.1)
                            except queue.Empty:
                                pass
                            continue
                        try:
                            chunk = audio_queue.get(timeout=0.1)
                        except queue.Empty:
                            continue
                        audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                        energy = float(np.sqrt(np.mean(audio * audio)))
                        now = time.monotonic()
                        if not wake_recorded:
                            if energy < opts['energy_threshold']:
                                continue
                            wake_start = now
                            wake_last_voice = now
                        wake_recorded.append(audio)
                        if energy >= opts['energy_threshold']:
                            wake_last_voice = now
                        elapsed = now - wake_start
                        ended = now - wake_last_voice >= wake_opts.get('silence_seconds', 0.7)
                        maxed = elapsed >= wake_opts.get('maximum_seconds', 3.0)
                        if ended or maxed:
                            samples = np.concatenate(wake_recorded)
                            wake_recorded = []
                            if elapsed >= wake_opts.get('minimum_seconds', 0.3):
                                busy.set()
                                try:
                                    if speech.detect_wake(samples):
                                        print('[WAKE] Jarvis detectado!')
                                        activate.set()
                                except Exception as exc:
                                    print('[WAKE ERRO]', type(exc).__name__, exc)
                                finally:
                                    clear_audio()
                                    busy.clear()
                        continue
                    # Primeira ativação: inicia uma sessão, sem reiniciar o Agent/histórico.
                    activate.clear()
                    wake_recorded = []
                    session_active = True
                    idle_since = time.monotonic()
                    listening_announced = False
                    clear_audio()
                    print(f'\n[SESSÃO] Conversa iniciada. Após {timeout_seconds:g}s sem falar, volto à espera.')
                    continue

                # ESTADO 2: sessão ativa. Aguardamos uma fala até o timeout, SEM pedir "Jarvis".
                if not listening_announced:
                    print('\n[OUVINDO] Pode falar sem repetir "Jarvis"...')
                    listening_announced = True
                if continuous and time.monotonic() - idle_since >= timeout_seconds:
                    session_active = False
                    listening_announced = False
                    clear_audio()
                    print('[SESSÃO] Inatividade: voltando a aguardar "Jarvis" ou F9.')
                    continue
                try:
                    chunk = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                energy = float(np.sqrt(np.mean(audio * audio)))
                if energy < opts['energy_threshold']:
                    continue

                # Detectou início de fala: registra até silêncio ou limite máximo da frase.
                busy.set()
                started = time.monotonic()
                last_voice = started
                recorded = [audio]
                try:
                    while time.monotonic() - started < opts['maximum_seconds']:
                        try:
                            chunk = audio_queue.get(timeout=0.1)
                        except queue.Empty:
                            if time.monotonic() - last_voice > opts['silence_seconds'] and time.monotonic() - started >= opts['minimum_seconds']:
                                break
                            continue
                        audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                        recorded.append(audio)
                        energy = float(np.sqrt(np.mean(audio * audio)))
                        if energy >= opts['energy_threshold']:
                            last_voice = time.monotonic()
                        elif time.monotonic() - last_voice > opts['silence_seconds'] and time.monotonic() - started >= opts['minimum_seconds']:
                            break

                    request = speech.transcribe(np.concatenate(recorded)).strip()
                    print('Você>', request or '(sem transcrição)')
                    if not request:
                        # Transcrição vazia não deve encerrar sessão nem reiniciar o tempo
                        continue
                    if is_session_end(request, config):
                        print('[SESSÃO] Encerramento por comando de voz.')
                        print('JARVIS> À disposição. Voltando ao modo de espera.')
                        say('À disposição. Voltando ao modo de espera.')
                        session_active = False
                        listening_announced = False
                        wake_recorded = []
                        continue

                    # Comandos administrativos usam a transcrição existente.
                    # Não há chamada extra ao LLM para frases normais.
                    cmd = parse_model_command(request, config.get('wake', {}).get('phrase', 'jarvis'))
                    if cmd:
                        speaking.set()
                        clear_audio()
                        try:
                            answer = execute_model_command(
                                cmd, agent,
                                announce=lambda msg: (print('JARVIS>', msg), say(msg)),
                            )
                            print('JARVIS>', answer)
                            say(answer)
                        finally:
                            clear_audio()
                            speaking.clear()
                        continue

                    # Pausa a captação durante resposta, geração neural e reprodução.
                    speaking.set()
                    clear_audio()
                    try:
                        pipeline = None
                        response = None
                        if (
                            config['voice'].get('enabled', True)
                            and config['voice'].get('provider') in ('chatterbox', 'kokoro')
                        ):
                            pipeline = speech.start_neural_stream()
                        if pipeline:
                            # Etapa A: execução e narração têm ciclos de vida independentes.
                            # Falha no Kokoro não cancela ferramentas nem perde o resultado.
                            runtime = TaskRuntime(
                                event_callback=lambda event: print(
                                    '[RUNTIME_A] {}={} task={}'.format(
                                        event.channel, event.status, event.task_id[:8]
                                    ) + (' detail=' + event.detail if event.detail else '')
                                )
                            )
                            response = runtime.run(
                                lambda publish: agent.ask_stream(request, on_text=publish),
                                speech_consumer=pipeline.submit,
                                speech_finish=pipeline.finish,
                            )
                            if runtime.task_error is not None:
                                raise runtime.task_error
                            if runtime.speech_error is not None:
                                print('[TTS/STREAM] Falha apenas na narração:',
                                      type(runtime.speech_error).__name__, runtime.speech_error)
                        else:
                            response = agent.ask(request)
                            speech.speak_legacy(response) if config['voice'].get('enabled', True) else None
                        print('JARVIS>', response)
                    except Exception as exc:
                        print('[TTS/STREAM] Falha:', type(exc).__name__, exc)
                        if response and (pipeline is None or pipeline.played == 0):
                            speech.speak_legacy(response)
                        elif response:
                            print('[TTS] Parte da resposta já foi falada; não será repetida.')
                        else:
                            raise
                    finally:
                        clear_audio()
                        speaking.clear()
                    if not continuous:
                        session_active = False
                        listening_announced = False
                        print('[SESSÃO] Voltei ao modo de espera.')
                    else:
                        print('[SESSÃO] Conversa aberta. Pode continuar.')
                except Exception as exc:
                    print('[ERRO]', type(exc).__name__, exc)
                finally:
                    # Contagem da inatividade só começa DEPOIS da resposta/erro.
                    idle_since = time.monotonic()
                    clear_audio()
                    busy.clear()
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        speech.close()
        print('JARVIS encerrado.')


if __name__ == '__main__':
    main()
