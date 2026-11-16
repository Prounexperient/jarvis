import unittest
from context_priority import context_priority_instruction
from context_manager import budget_messages

class ContextPriorityTests(unittest.TestCase):
    def test_last_turn_and_reference(self):
        history = [{'role':'system','content':'base'}, {'role':'user','content':'Crie o projeto Tolkien'},
                   {'role':'assistant','content':'Criado'}, {'role':'user','content':'Agora corrija aquela função'}]
        before = repr(history)
        hint = context_priority_instruction(history)
        self.assertIn('ÚLTIMA mensagem', hint)
        self.assertIn('antecedente', hint)
        self.assertEqual(repr(history), before)
    def test_tool_cycle_remains_ordered(self):
        history = [{'role':'system','content':'base'}, {'role':'user','content':'Crie'},
                   {'role':'assistant','tool_calls':[{'id':'a'}]}, {'role':'tool','tool_call_id':'a','content':'ok'},
                   {'role':'user','content':'Continue'}]
        before = repr(history)
        result = budget_messages(history, context_length=8192)
        self.assertEqual(result, history)
        self.assertEqual(repr(history), before)

if __name__ == '__main__':
    unittest.main()
