"""Regression tests for safe plain-text output and API failure recovery."""
from unittest.mock import Mock
from agent import Agent

cfg = {'lm_studio': {'base_url':'http://localhost:1234/v1', 'model':'test', 'max_tokens':900}, 'conversation':{'dual_channel_enabled':True,'dual_channel_format':'plain'}, 'model_management':{'enabled':False}}
a = Agent(cfg)
assert '<fatos>' not in a.history[0]['content']
assert a._final_channels('Resposta normal.', 'test') == ('Resposta normal.', 'Resposta normal.')
spoken=[]
msg=Mock(); msg.content='Recuperação normal.'
choice=Mock(); choice.message=msg
response=Mock(); response.choices=[choice]
a.client.chat.completions.create=Mock(return_value=response)
assert a._stream_failure(RuntimeError('peg-native format'), 'test', spoken.append)=='Recuperação normal.'
assert spoken==['Recuperação normal.']
assert a.client.chat.completions.create.call_args.kwargs['tool_choice']=='none'
assert a.client.chat.completions.create.call_args.kwargs['stream'] is False
print('PASSOU: Etapa 13.3.1 - plain, sem tags e recuperação sem ferramentas')
