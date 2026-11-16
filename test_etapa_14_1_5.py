import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_manager import budget_messages
from task_controller import TaskController


class Stage1415(unittest.TestCase):
    def test_calculation_remains_in_context(self):
        history = [{'role': 'system', 'content': 'Você é JARVIS.'},
                   {'role': 'user', 'content': 'Quanto é 4+13?'},
                   {'role': 'assistant', 'content': 'O resultado é 17.'}]
        for i in range(12):
            history += [{'role': 'user', 'content': 'Pergunta ' + str(i)},
                        {'role': 'assistant', 'content': 'Resposta ' + str(i)}]
        history += [{'role': 'user', 'content': 'Qual foi o último resultado?'}]
        compact = budget_messages(history, 8192, 900)
        self.assertIn('17', str(compact))
        self.assertEqual(len(compact), len(history))

    def test_old_tool_result_compressed_not_original(self):
        history = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'Busque'}]
        history += [{'role': 'assistant', 'tool_calls': [{'id': '1'}]},
                    {'role': 'tool', 'tool_call_id': '1', 'content': 'x' * 30000},
                    {'role': 'assistant', 'content': 'Achei.'},
                    {'role': 'user', 'content': 'Qual o resultado?'}]
        compact = budget_messages(history, 8192, 900)
        self.assertLess(len(str(compact)), len(str(history)))
        self.assertEqual(history[3]['content'], 'x' * 30000)

    def test_no_implicit_read(self):
        self.assertIsNotNone(TaskController('Tenho um PDF da Odisseia na pasta Documentos').inspect('read_document', {'path': 'x.pdf'}))
        self.assertIsNone(TaskController('Resuma o PDF da Odisseia').inspect('read_document', {'path': 'x.pdf'}))

    def test_no_implicit_open(self):
        self.assertIsNotNone(TaskController('Localize a pasta Música').inspect('open_directory', {'path': 'x'}))
        self.assertIsNone(TaskController('Abra a pasta Música').inspect('open_directory', {'path': 'x'}))

    def test_repeated_call_blocked(self):
        t = TaskController('Localize a música')
        self.assertIsNone(t.inspect('search_files', {'query': 'Sum41'}))
        self.assertIsNone(t.inspect('search_files', {'query': 'Sum41'}))
        self.assertIsNotNone(t.inspect('search_files', {'query': 'Sum41'}))

    def test_distinct_calls_not_blocked(self):
        t = TaskController('Localize a música')
        for i in range(12):
            self.assertIsNone(t.inspect('search_files', {'query': str(i)}))


if __name__ == '__main__':
    unittest.main()
