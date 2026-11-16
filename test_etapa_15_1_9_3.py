"""Regressoes de orquestracao: testes offline, sem LM Studio."""
import ast
import unittest
from unittest.mock import patch
from pathlib import Path
AGENT_SOURCE = Path(__file__).with_name("agent.py").read_text(encoding="utf-8")
TREE = ast.parse(AGENT_SOURCE)
AGENT = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
def method_source(name):
    node = next(n for n in AGENT.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(AGENT_SOURCE, node)
from context_manager import budget_messages, estimate_tokens


class TestToolContinuation(unittest.TestCase):
    def test_ask_does_not_disable_tools_after_document(self):
        source = method_source("ask")
        self.assertNotIn('document_pending', source)
        self.assertIn("tool_choice='none' if (force_final", source)

    def test_ask_stream_does_not_disable_tools_after_document(self):
        source = method_source("ask_stream")
        self.assertNotIn('document_pending', source)
        self.assertIn("tool_choice='none' if (force_final", source)

    def test_budget_accounts_for_tool_schemas(self):
        source = method_source("_model_messages")
        self.assertIn('schema_tokens', source)
        self.assertIn('reserve=reserve', source)

    def test_error_details_included(self):
        class Error(Exception):
            response = None
        self.assertIn('detail[:1600]', method_source('_log_model_error'))
        self.assertIn('body=', method_source('_log_model_error'))

    def test_budget_keeps_active_tool_cycle(self):
        history = [
            {'role': 'system', 'content': 'system'},
            {'role': 'user', 'content': 'analise os arquivos'},
            {'role': 'assistant', 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'read_text_file', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'c1', 'content': 'arquivo A'},
        ]
        prepared = budget_messages(history, context_length=8192, response_tokens=900, reserve=3000)
        self.assertEqual(prepared[-1]['tool_call_id'], 'c1')
        self.assertEqual(prepared[-2]['role'], 'assistant')


if __name__ == '__main__':
    unittest.main()
