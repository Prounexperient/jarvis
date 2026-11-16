"""Teste isolado: python test_etapa_9_1.py (sem LM Studio)."""
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

base = Path(__file__).resolve().parent
fake_openai = types.ModuleType('openai')
fake_openai.OpenAI = lambda **kw: None
sys.modules['openai'] = fake_openai
fake_tools = types.ModuleType('tools')
fake_tools.SCHEMAS = []
fake_tools.get_last_search_paths = lambda: ()
fake_tools.run_tool = lambda name, args, config: {'path': 'MS_WO01.py', 'text': 'def validar_os():\n    return True'}
sys.modules['tools'] = fake_tools
fake_context = types.ModuleType('contextual_actions')
fake_context.resolve_action = lambda text, paths: None
sys.modules['contextual_actions'] = fake_context
fake_policy = types.ModuleType('conversation_policy')
fake_policy.search_feedback = lambda result: ''
fake_policy.voice_first_system = lambda: ''
sys.modules['conversation_policy'] = fake_policy
fake_manager = types.ModuleType('model_manager')
fake_manager.ModelManager = object
fake_manager.ModelManagerError = RuntimeError
sys.modules['model_manager'] = fake_manager
spec = importlib.util.spec_from_file_location('agent_patch_test', base / 'agent.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Obj:
    def __init__(self, **kw): self.__dict__.update(kw)

class DeltaStream:
    def __init__(self, d): self.choices = [Obj(delta=d)]

class FakeCompletions:
    def __init__(self): self.calls = []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            tool = Obj(id='call1', function=Obj(name='read_search_result', arguments='{"index":1}'))
            if kwargs.get('stream'):
                return iter([
                    DeltaStream(Obj(content='Encontrei o arquivo', tool_calls=[])),
                    DeltaStream(Obj(content=None, tool_calls=[Obj(index=0,id='call1',function=tool.function)])),
                ])
            msg = Obj(tool_calls=[tool], model_dump=lambda **kw: {'role':'assistant','tool_calls':[{'id':'call1','type':'function','function':{'name':'read_search_result','arguments':'{"index":1}'}}]})
            return Obj(choices=[Obj(message=msg)])
        assert kwargs['tool_choice'] == 'none'
        assert 'Tarefa ORIGINAL' in kwargs['messages'][-1]['content']
        answer = 'O script define uma função validar_os que retorna True.'
        if kwargs.get('stream'):
            return iter([DeltaStream(Obj(content=answer, tool_calls=[]))])
        msg = Obj(tool_calls=[],content=answer,model_dump=lambda **kw: {'role':'assistant','content':answer})
        return Obj(choices=[Obj(message=msg)])

for streaming in (False, True):
    agent = module.Agent({'lm_studio': {'base_url':'http://localhost:1234/v1','model':'test'}})
    completions = FakeCompletions()
    agent.client = Obj(chat=Obj(completions=completions))
    spoken = []
    answer = agent.ask_stream('Resuma o primeiro arquivo', spoken.append) if streaming else agent.ask('Resuma o primeiro arquivo')
    assert 'define uma função' in answer
    if streaming: assert spoken == [answer], spoken
    assert len(completions.calls) == 2
    print('PASSOU:', 'stream' if streaming else 'normal')
print('Testes isolados OK; integração real com LM Studio ainda precisa ser testada.')
