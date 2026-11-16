"""Etapa A: estado e eventos independentes para execução e narração.

Não implementa barge-in, cancelamento nem escuta simultânea (Etapa B).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Queue
from threading import Event, Lock, Thread
from uuid import uuid4


@dataclass(frozen=True)
class RuntimeEvent:
    task_id: str
    channel: str
    status: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    detail: str = ''


class TaskRuntime:
    """O resultado da tarefa nunca depende da disponibilidade do sintetizador."""
    def __init__(self, event_callback=None):
        self.task_id = uuid4().hex
        self.events = []
        self._lock = Lock()
        self._callback = event_callback
        self.task_status = 'pending'
        self.speech_status = 'pending'
        self.result = None
        self.task_error = None
        self.speech_error = None
        self._speech_queue = Queue()
        self._speech_end = object()
        self.task_done = Event()
        self.speech_done = Event()
        self._mute = Event()
        self._shorten = Event()

    def control_speech(self, command):
        """Controla fila de narração, sem cancelar a tarefa de ferramentas."""
        if command in ('silence', 'stop'):
            self._mute.set()
            self._emit('speech', 'muted')
        elif command in ('summarize', 'conclude'):
            self._shorten.set()
            self._emit('speech', 'shortened')
        else:
            raise ValueError('Comando de voz desconhecido.')

    def _emit(self, channel, status, detail=''):
        event = RuntimeEvent(self.task_id, channel, status, detail=detail)
        with self._lock:
            self.events.append(event)
            if channel == 'task':
                self.task_status = status
            elif channel == 'speech':
                self.speech_status = status
        try:
            from operational_store import save_task, add_event
            if channel == 'task':
                save_task(self.task_id, status)
            add_event(self.task_id, channel + ':' + status, {'detail': detail})
        except Exception as exc:
            print('[PERSISTENCIA] evento não gravado:', type(exc).__name__)
        if self._callback:
            try:
                self._callback(event)
            except Exception:
                pass  # Telemetria não pode interromper a tarefa.

    def run(self, work, speech_consumer=None, speech_finish=None):
        """Executa o agente e o TTS em threads distintas; aguarda ambos.

        work(on_text) produz o resultado técnico e trechos destinados à voz.
        speech_consumer(text) recebe os trechos na thread de narração.
        """
        def speak_worker():
            self._emit('speech', 'running' if speech_consumer else 'disabled')
            try:
                while True:
                    chunk = self._speech_queue.get()
                    if chunk is self._speech_end:
                        break
                    if speech_consumer and not self._mute.is_set():
                        if self._shorten.is_set():
                            self._shorten.clear()
                            speech_consumer('Vou resumir a narração. O trabalho continua em execução.')
                            self._mute.set()
                        else:
                            speech_consumer(chunk)
                if speech_consumer and speech_finish:
                    speech_finish()
                self._emit('speech', 'completed' if speech_consumer else 'disabled')
            except Exception as exc:
                self.speech_error = exc
                self._emit('speech', 'failed', '{}: {}'.format(type(exc).__name__, exc))
                # Consumir fila até sentinela, evitando bloquear a execução.
                while self._speech_queue.get() is not self._speech_end:
                    pass
            finally:
                self.speech_done.set()

        def task_worker():
            self._emit('task', 'running')
            try:
                self.result = work(self._speech_queue.put if speech_consumer else lambda _text: None)
                self._emit('task', 'completed')
            except Exception as exc:
                self.task_error = exc
                self._emit('task', 'failed', '{}: {}'.format(type(exc).__name__, exc))
            finally:
                self.task_done.set()
                self._speech_queue.put(self._speech_end)

        voice_thread = Thread(target=speak_worker, name='jarvis-speech', daemon=True)
        work_thread = Thread(target=task_worker, name='jarvis-task', daemon=True)
        voice_thread.start()
        work_thread.start()
        work_thread.join()
        voice_thread.join()
        return self.result
