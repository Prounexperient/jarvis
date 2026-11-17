"""AAA 05: behavioral tests of the real Agent + integrated runtime.

Windows tools and LM Studio are simulated; no file is opened, deleted or run.
The tests exercise the actual Agent.ask / ask_stream methods.
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# The offline test suite has no OpenAI SDK dependency. This stub never calls network.
if 'openai' not in sys.modules:
    openai_stub=types.ModuleType('openai')
    openai_stub.OpenAI=lambda **_kw: None
    sys.modules['openai']=openai_stub

import yaml
import agent as agent_mod
from agent import Agent
from adaptive_toolset import AdaptiveToolset
from semantic_memory import SemanticMemory, phonetic
from autonomy_kernel import AutonomyKernel
from context_state import NavigationContext
from task_continuity import TaskContinuityManager
from experience_store import ExperienceStore
from skills_manager import SkillsManager
from test_aaa03_continuity import FakeSkills


class Message:
    def __init__(self, content='', tool_calls=None):
        self.content=content
        self.tool_calls=tool_calls or []
    def model_dump(self,**_):
        data={'role':'assistant','content':self.content}
        if self.tool_calls:
            data['tool_calls']=[{'id':c.id,'type':'function',
                                 'function':{'name':c.function.name,'arguments':c.function.arguments}}
                                for c in self.tool_calls]
        return data


class ToolCall:
    def __init__(self,name,args, ident='call1'):
        self.id=ident
        self.function=types.SimpleNamespace(name=name,arguments=json.dumps(args))


class Completions:
    def __init__(self, replies=None):
        self.replies=list(replies or [])
        self.calls=[]
    def create(self,**kwargs):
        self.calls.append(kwargs)
        reply=self.replies.pop(0) if self.replies else Message('Não consegui concluir.')
        if isinstance(reply,str):
            reply=Message(reply)
        if kwargs.get('stream'):
            events=[]
            if reply.tool_calls:
                for i,call in enumerate(reply.tool_calls):
                    part=types.SimpleNamespace(index=i,id=call.id,function=call.function)
                    delta=types.SimpleNamespace(tool_calls=[part],content=None)
                    events.append(types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta,finish_reason=None)]))
                events.append(types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(tool_calls=[],content=None),finish_reason='tool_calls')]))
            else:
                events.append(types.SimpleNamespace(choices=[types.SimpleNamespace(
                    delta=types.SimpleNamespace(tool_calls=[],content=reply.content),finish_reason='stop')]))
            return iter(events)
        reason='tool_calls' if reply.tool_calls else 'stop'
        return types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason=reason,message=reply)])


class FullStack05(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.path=Path(self.td.name)/'jarvis.db'
        cfg=yaml.safe_load((Path(__file__).with_name('config.yaml')).read_text(encoding='utf-8'))
        cfg['model_management']['enabled']=False
        cfg['lm_studio']['model']='local-mock'
        cfg['conversation']['dual_channel_enabled']=False
        self.cfg=cfg
        with patch.object(agent_mod,'NavigationContext',lambda:NavigationContext(self.path)),\
             patch.object(agent_mod,'ExperienceStore',lambda:ExperienceStore(self.path)):
            self.agent=Agent(cfg)
        self.agent._get_model=lambda:'local-mock'
        self.agent._speak_final=lambda technical,model,question,on_text:on_text(technical)
        self.agent._final_channels=lambda raw,model:(raw,raw)
        self.client=Completions()
        self.agent.client=types.SimpleNamespace(chat=types.SimpleNamespace(completions=self.client))

    def test_tools_shrink_by_subject_without_removing_registered_capabilities(self):
        all_count=len(self.agent.tool_schemas)
        self.assertGreater(all_count,25)
        data=[('Qual a época que viveu Enoki?', 'knowledge',0),
              ('Cite uma passagem de um livro de Tolkien', 'knowledge',0),
              ('Abra a primeira música da pasta Vídeos', 'files',18),
              ('Liste os arquivos dentro dela', 'files',18),
              ('Crie um projeto Python', 'development',19),
              ('Quais discos existem no meu computador?', 'capabilities',1)]
        for request,route,max_count in data:
            with self.subTest(request=request):
                scope=self.agent.autonomy.catalog.select(request)
                self.assertEqual(scope.category,route)
                self.assertLessEqual(len(scope.schemas),max_count)

    def test_semantic_asr_recovery_grounded_in_prior_subject(self):
        memory=self.agent.autonomy.semantic
        first=memory.prepare('Recite o segundo Livro de Enoch')
        self.assertEqual(first.subject,'Enoch')
        next_hint=memory.prepare('Qual a época que viveu Enoki?')
        self.assertEqual(next_hint.subject,'Enoch')
        self.assertEqual(next_hint.suggestion,'Enoch')
        self.assertEqual(next_hint.heard,'Enoki')
        self.assertGreater(next_hint.similarity,0.75)
        self.assertIn('erro de reconhecimento',next_hint.instruction())
        # Uma mudança expressa de assunto tem precedência sobre a hipótese do ASR.
        other=memory.prepare('Quem foi Aristóteles?')
        self.assertEqual(other.subject,'Aristóteles')
        self.assertFalse(other.suggestion)
        persisted=SemanticMemory(self.path)
        self.assertEqual(persisted.prepare('Em que época viveu Aristoteles?').subject,'Aristóteles')

    def test_knowledge_followup_has_zero_local_tools_and_relevant_topic(self):
        self.client.replies=['O Segundo Livro de Enoch é um texto apócrifo.',
                             'Enoque é uma figura literária e religiosa antiga.']
        self.agent.ask('Fale sobre o Segundo Livro de Enoch.')
        self.agent.ask('Qual a época que viveu Enoki?')
        self.assertEqual(len(self.client.calls),2)
        first,second=self.client.calls
        self.assertEqual(first['tool_choice'],'none')
        self.assertIsNone(second['tools'])
        self.assertIn('CONTEXTO SEMÂNTICO',second['messages'][0]['content'])
        self.assertIn('Enoki',second['messages'][0]['content'])
        self.assertIn('Enoch',second['messages'][0]['content'])
        self.assertGreaterEqual(len(second['messages']),4)
        self.assertIn('Segundo Livro de Enoch',str(second['messages']))

    def test_knowledge_stream_has_same_context_and_never_calls_local_search(self):
        self.client.replies=['Livro de Enoch.', 'Enoque pertence à tradição bíblica.']
        spoken=[]
        self.agent.ask_stream('Explique o Livro de Enoch',spoken.append)
        self.agent.ask_stream('Em que época viveu Enoki?',spoken.append)
        self.assertIn('Enoque',spoken[-1])
        self.assertEqual(self.client.calls[-1]['tool_choice'],'none')
        self.assertEqual(self.client.calls[-1]['tools'],None)

    def test_unverified_book_quote_is_not_presented_as_literal(self):
        self.client.replies=['Aqui está: “E então o Senhor me disse que...”']
        answer=self.agent.ask('Cite um trecho do Segundo Livro de Enoch.')
        self.assertIn('não tenho uma edição textual verificada',answer.lower())
        self.assertNotIn('E então o Senhor',answer)

    def test_no_local_tool_even_if_model_hallucinates_tool_call_for_knowledge(self):
        self.client.replies=[Message('',[ToolCall('search_files',{'query':'Enoki'})]),
                             'A referência anterior foi ao livro de Enoch.']
        self.agent.ask('Qual a época em que viveu Enoki?')
        with self.agent.autonomy._connect() as db:
            row=db.execute('SELECT evidence FROM aaa_autonomy_turns ORDER BY created DESC LIMIT 1').fetchone()
        events=json.loads(row[0]);self.assertTrue(events)
        self.assertEqual(events[0]['status'],'failed')
        self.assertIn('fora do escopo',events[0]['detail'])

    def test_direct_complete_media_goal_is_verified(self):
        c=r'C:\Users\rodco\Videos'
        fake=FakeSkills([c]);fake.replies={c:[c+r'\01.mp4',c+r'\02.mkv',c+r'\03.mp3']}
        self.agent.skills_manager=fake
        reply=self.agent.ask('Abra a pasta de vídeos e reproduza o primeiro vídeo')
        self.assertIn('Abri o arquivo 1',reply)
        self.assertEqual(fake.opened,[c+r'\01.mp4'])
        self.assertEqual(fake.opened_directories,[c])
        with self.agent.autonomy._connect() as db:
            rows=db.execute('SELECT status,evidence FROM aaa_autonomy_turns').fetchall()
        self.assertTrue(any(status=='verified' and any(e['tool']=='open_file' for e in json.loads(events))
                            for status,events in rows))
        next_answer=self.agent.ask('Agora reproduza o próximo')
        self.assertIn('arquivo 2',next_answer)
        self.assertEqual(fake.opened[-1],c+r'\02.mkv')

    def test_audio_filter_not_folder_name(self):
        c=r'C:\Users\rodco\Videos'
        fake=FakeSkills([c]);fake.replies={c:[c+r'\01.mp4',c+r'\02.mkv',c+r'\03.mp3']}
        self.agent.skills_manager=fake
        response=self.agent.ask('Procure a pasta vídeos no disco C e reproduza a primeira música')
        self.assertIn('Abri o arquivo',response)
        self.assertEqual(fake.opened,[c+r'\03.mp3'])

    def test_direct_list_after_media_preserves_cursor_and_sqlite(self):
        c=r'C:\Users\rodco\Videos'
        fake=FakeSkills([c]);fake.replies={c:[c+r'\01.mp4',c+r'\02.mkv',c+r'\03.mp3']}
        self.agent.skills_manager=fake
        self.agent.ask('Abra o primeiro vídeo da pasta vídeos no disco C')
        a=self.agent.ask('Liste os arquivos dentro dela')
        self.assertIn('01.mp4',a)
        self.assertIn('02.mkv',a)
        next_reply=self.agent.ask('Agora o próximo')
        self.assertIn('arquivo 2',next_reply)
        self.assertEqual(fake.opened[-1],c+r'\02.mkv')

    def test_model_context_preserves_many_turns(self):
        self.client.replies=['Resposta sobre Enoch.']
        self.agent.history.extend([{'role':r,'content':f'Mensagem conversacional {i}'}
                                  for i in range(18) for r in ('user','assistant')])
        self.agent.ask('Qual a época de Enoki?')
        history=self.client.calls[-1]['messages']
        self.assertGreater(len(history),12,'context budget should retain many short turns')

    def test_model_never_claims_opened_if_only_search_is_verified(self):
        t=self.agent.autonomy.begin('Abra o primeiro vídeo da pasta Videos',self.agent.navigation)
        self.agent.autonomy.observe(t,'search_directories',{'query':'Videos'},{'results':[{'path':'C:/Videos'}]})
        final=self.agent.autonomy.finish(t,'Abri o arquivo solicitado.',model_based=True)
        self.assertIn('não tenho confirmação',final.lower())
        self.assertNotEqual(t.status,'verified')

    def test_model_continuation_once_when_stops_without_executing_task(self):
        self.client.replies=['Claro, vou abrir a pasta.','Não foi possível localizar sem acesso.']
        with patch.object(self.agent,'_explicit_folder_action',return_value=None), \
             patch.object(self.agent,'_contextual_media_action',return_value=None), \
             patch.object(self.agent,'_contextual_file_action',return_value=None):
            result=self.agent.ask('Abra o primeiro arquivo da pasta Vídeos')
        self.assertNotIn('Abri o arquivo solicitado',result)
        self.assertEqual(len(self.client.calls),2)
        self.assertIn('OBJETIVO ORIGINAL ainda não',self.client.calls[-1]['messages'][0]['content'])

    def test_strategy_learning_records_only_tool_evidence(self):
        a=self.agent.autonomy
        t=a.begin('Abra primeiro arquivo da pasta Vídeos',self.agent.navigation)
        a.observe(t,'search_directories',{'query':'Videos'},{'results':[]})
        a.observe(t,'open_file',{'path':'C:/Videos/x.mp4'},{'error':'not found'})
        stats=a.strategies('files')
        self.assertEqual(next(x['ok'] for x in stats if x['tool']=='search_directories'),1)
        self.assertEqual(next(x['failed'] for x in stats if x['tool']=='open_file'),1)
        self.assertIn('RECUPERAÇÃO',a.recovery_hint(t))

    def test_phonetic_similarity_not_rewrite_original_text(self):
        self.assertNotEqual(phonetic('enoch'),phonetic('enoki'))
        self.assertEqual(self.agent.autonomy.semantic.prepare('Enoki').subject,None)


if __name__=='__main__':
    unittest.main()
