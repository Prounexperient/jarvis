import unittest
from task_runtime import TaskRuntime


class TaskRuntimeTests(unittest.TestCase):
    def test_separate_channels_and_order(self):
        spoken = []
        runtime = TaskRuntime()
        result = runtime.run(lambda send: (send('olá'), send('mundo'), 42)[2], spoken.append)
        self.assertEqual(result, 42)
        self.assertEqual(spoken, ['olá', 'mundo'])
        self.assertEqual(runtime.task_status, 'completed')
        self.assertEqual(runtime.speech_status, 'completed')
        self.assertTrue(runtime.task_done.is_set())

    def test_speech_failure_does_not_cancel_work(self):
        calls = []
        def broken(_):
            raise RuntimeError('kokoro indisponível')
        def work(send):
            send('primeira frase')
            calls.append('implementação concluída')
            return 'arquivo criado'
        runtime = TaskRuntime()
        self.assertEqual(runtime.run(work, broken), 'arquivo criado')
        self.assertEqual(calls, ['implementação concluída'])
        self.assertEqual(runtime.task_status, 'completed')
        self.assertEqual(runtime.speech_status, 'failed')

    def test_work_failure_does_not_get_masked(self):
        runtime = TaskRuntime()
        def work(_):
            raise ValueError('falha da ferramenta')
        runtime.run(work, lambda _: None)
        self.assertIsInstance(runtime.task_error, ValueError)
        self.assertEqual(runtime.task_status, 'failed')
        self.assertEqual(runtime.speech_status, 'completed')

    def test_callback_failure_does_not_stop_work(self):
        runtime = TaskRuntime(event_callback=lambda event: 1 / 0)
        self.assertEqual(runtime.run(lambda _: 10), 10)
        self.assertEqual(runtime.task_status, 'completed')


if __name__ == '__main__':
    unittest.main()
