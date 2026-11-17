"""Exercise real Agent methods without loading LM Studio/Whisper/Kokoro."""
import ast
import tempfile
import unittest
from pathlib import Path

from context_state import NavigationContext
from explicit_folder_controller import ExplicitFolderController, parse_folder_request
from quote_intent import is_general_quotation_request
from task_continuity import TaskContinuityManager
from test_aaa03_continuity import FakeSkills


def agent_method(name):
    syntax = ast.parse((Path(__file__).with_name('agent.py')).read_text(encoding='utf-8'))
    klass = next(x for x in syntax.body if isinstance(x,ast.ClassDef) and x.name=='Agent')
    code = next(x for x in klass.body if isinstance(x, ast.FunctionDef) and x.name==name)
    scope = {'ExplicitFolderController': ExplicitFolderController,
             'parse_folder_request': parse_folder_request,
             'is_general_quotation_request': is_general_quotation_request}
    exec(compile(ast.Module(body=[code],type_ignores=[]), 'agent.py','exec'),scope)
    return scope[name]


class GatewayTests(unittest.TestCase):
    def _make(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        d=Path(td.name)/'jarvis.db'
        folders=[r'C:\Users\rodco\Videos',r'D:\Videos']
        skills=FakeSkills(folders)
        skills.replies={folders[0]:[r'C:\Users\rodco\Videos\intro.mp4'],
                        folders[1]:[r'D:\Videos\outro.mp4']}
        def should_not_call(*_args):
            raise AssertionError('Old media cursor or LLM was invoked')
        TestAgent = type('TestAgent', (), {
            'ask':agent_method('ask'),
            'ask_stream':agent_method('ask_stream'),
            '_explicit_folder_action':agent_method('_explicit_folder_action'),
            '_contextual_media_action':should_not_call,
            '_contextual_file_action':should_not_call,
            '_get_model':should_not_call,
        })
        agent=TestAgent()
        agent.history=[]
        agent.skills_manager=skills
        agent.navigation=NavigationContext(d)
        agent.task_continuity=TaskContinuityManager(d)
        return agent,skills

    def test_actual_ask_multi_turn_without_llm(self):
        agent,skills=self._make()
        first=agent.ask('Abra o primeiro vídeo da pasta vídeos')
        self.assertIn('mais de uma',first)
        second=agent.ask('do disco local C')
        self.assertIn('Abri o arquivo 1',second)
        third=agent.ask('Liste os arquivos dentro dela')
        self.assertIn('intro.mp4',third)
        self.assertEqual(len(agent.history),6)
        self.assertEqual(skills.opened,[r'C:\Users\rodco\Videos\intro.mp4'])

    def test_actual_ask_stream_multi_turn_with_speech(self):
        agent,skills=self._make()
        spoken=[]
        for text in ('Abra o primeiro vídeo da pasta vídeos', 'do disco C',
                     'Liste os arquivos dentro dela'):
            result=agent.ask_stream(text,spoken.append)
            self.assertEqual(result,spoken[-1])
        self.assertEqual(len(spoken),3)
        self.assertEqual(skills.opened,[r'C:\Users\rodco\Videos\intro.mp4'])

if __name__=='__main__':
    unittest.main()
