"""AAA 02: validação real dos novos módulos e integração conservadora ao Agent."""
import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent_core import AgentCore
from experience_store import ExperienceStore
from context_state import NavigationContext
from quote_intent import is_general_quotation_request
from result_verifier import ResultVerifier
from recovery_engine import RecoveryEngine
from task_planner import TaskPlanner
from task_executor import TaskExecutor
from task_controller import TaskController
from task_completion import TaskCompletion


class FakeSkill:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def execute(self, name, args):
        self.calls.append((name, dict(args)))
        if not self.responses:
            raise AssertionError("unexpected tool call")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class PlannerTests(unittest.TestCase):
    def test_conversation_has_no_local_plan(self):
        plan = TaskPlanner().create('Qual é o significado de inteligência?')
        self.assertEqual(plan.category, 'conversation')
        self.assertEqual(plan.instruction(), '')

    def test_explicit_file_plan_includes_opening(self):
        plan = TaskPlanner().create('Encontre a pasta Música e abra o primeiro arquivo.')
        self.assertEqual(plan.category, 'files')
        self.assertEqual([s.name for s in plan.stages], ['localizar','listar','abrir'])

    def test_unverified_opening_claim_is_blocked(self):
        plan=TaskPlanner().create('Encontre a pasta Música e abra o primeiro arquivo.')
        answer=plan.guard_final_claim('Abri o arquivo solicitado.')
        self.assertIn('Não posso confirmar',answer)
        plan.record('open_file', {'path':r'C:\Música\x.mp3'},
                    ResultVerifier().verify('open_file', {'path':r'C:\Música\x.mp3'},
                                            {'opened':r'C:\Música\x.mp3'}))
        self.assertEqual(plan.guard_final_claim('Abri o arquivo solicitado.'),
                         'Abri o arquivo solicitado.')

    def test_only_real_direct_claims_are_guarded(self):
        plan=TaskPlanner().create('Encontre a pasta Música e abra o primeiro arquivo.')
        self.assertEqual(plan.guard_final_claim('Não abri o arquivo.'),
                         'Não abri o arquivo.')
        self.assertEqual(plan.guard_final_claim('Explico como abrir um arquivo.'),
                         'Explico como abrir um arquivo.')

    def test_code_edit_plan_requires_no_unauthorized_tests(self):
        plan = TaskPlanner().create('Analise e corrija o código Python no arquivo local.')
        self.assertEqual(plan.category, 'development')
        self.assertIn('inspecionar', [s.name for s in plan.stages])
        self.assertIn('modificar', [s.name for s in plan.stages])
        self.assertNotIn('validar', [s.name for s in plan.stages])
        self.assertTrue(all(x.status=='pending' for x in plan.stages))


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.v=ResultVerifier()

    def test_open_file_requires_exact_confirmation(self):
        path=r'C:\Música\a.mp3'
        good=self.v.verify('open_file',{'path':path},{'opened':path})
        self.assertEqual(good.status,'verified')
        bad=self.v.verify('open_file',{'path':path},{'opened':r'D:\Music Lib\a.mp3'})
        self.assertEqual(bad.status,'failed')

    def test_search_scope_mismatch_is_failure(self):
        result={'scope':r'D:\Music Lib','results':[{'path':r'D:\Music Lib\x.mp3'}]}
        self.assertEqual(self.v.verify('search_files_in_directory',
                  {'directory':r'C:\Vídeos'},result).status,'failed')
        result['scope']=r'C:\Vídeos'
        result['truncated']=True
        self.assertEqual(self.v.verify('search_files_in_directory',
                  {'directory':r'C:\Vídeos'},result).status,'partial')

    def test_empty_text_file_can_be_read(self):
        self.assertEqual(self.v.verify('read_text_file',
             {'path':'a.txt'}, {'path':'a.txt','content':''}).status,'verified')

    def test_test_exit_status_not_confused_with_successful_execution(self):
        self.assertEqual(self.v.verify('developer_run_python',{},
             {'executed':True,'exit_code':2,'passed':False}).status,'failed')
        self.assertEqual(self.v.verify('developer_run_python',{},
             {'executed':True,'exit_code':0,'passed':True}).status,'verified')

    def test_partial_project_creation_not_called_complete(self):
        args={'files':[{'path':'main.py','content':'print(1)'},{'path':'README.md','content':'Readme'}]}
        self.assertEqual(self.v.verify('developer_create_project_structured',args,
                       {'success':True,'files':['main.py']}).status,'partial')

    def test_syntax_check_is_not_functional_test(self):
        self.assertEqual(self.v.verify('developer_verify_code',{},
                {'syntax_valid':True,'structural_verified':True,'functional_tested':False}).status,'verified')
        self.assertEqual(self.v.verify('developer_verify_code',{},
                {'syntax_valid':True,'structural_verified':False,'functions_missing':['main']}).status,'failed')


class ExecutorTests(unittest.TestCase):
    def test_verified_action_raises_plan_state(self):
        skill=FakeSkill([{'results':[]}])
        plan=TaskPlanner().create('Encontre a pasta Música.')
        result=TaskExecutor(skill,plan).execute('search_directories',{'query':'Música'})
        self.assertEqual(result['results'],[])
        self.assertEqual(plan.tool_events[0]['status'],'verified')

    def test_failed_open_becomes_tool_error(self):
        skill=FakeSkill([{'success':True}])
        plan=TaskPlanner().create('Abra o arquivo a.mp3.')
        result=TaskExecutor(skill,plan).execute('open_file',{'path':r'C:\a.mp3'})
        self.assertIn('Verificação AAA',result['error'])
        self.assertEqual(len(skill.calls),1)
        self.assertEqual(plan.tool_events[0]['status'],'failed')

    def test_transient_read_retry_once(self):
        skill=FakeSkill([{'error':'TimeoutError: temporarily unavailable'},
                         {'results':[{'path':r'C:\Música'}]}])
        plan=TaskPlanner().create('Encontre a pasta Música.')
        result=TaskExecutor(skill,plan).execute('search_directories',{'query':'Música'})
        self.assertEqual(len(skill.calls),2)
        self.assertNotIn('error',result)
        self.assertEqual(plan.tool_events[-1]['attempts'],2)

    def test_never_retry_writes_or_deletion_or_program_execution(self):
        for tool in ('developer_replace_file','developer_delete_file',
                     'developer_run_python','open_file'):
            with self.subTest(tool=tool):
                skill=FakeSkill([{'error':'TimeoutError: temporarily unavailable'}])
                plan=TaskPlanner().create('Corrija o arquivo')
                result=TaskExecutor(skill,plan).execute(tool,{'path':'C:\\a.py'})
                self.assertEqual(len(skill.calls),1)
                self.assertIn('error',result)

    def test_permission_failure_is_not_retried(self):
        skill=FakeSkill([{'error':'PermissionError: fora das pastas autorizadas'}])
        plan=TaskPlanner().create('Encontre arquivos')
        result=TaskExecutor(skill,plan).execute('search_files',{'query':'a'})
        self.assertEqual(len(skill.calls),1)
        self.assertIn('contorne',result['_aaa_recovery'])

    def test_limit_tool_calls_blocks_extra_actions(self):
        skill=FakeSkill([{'results':[]}])
        plan=TaskPlanner().create('Encontre arquivos')
        plan.max_tool_calls=1
        exe=TaskExecutor(skill,plan)
        exe.execute('search_files',{'query':'a'})
        result=exe.execute('search_files',{'query':'b'})
        self.assertIn('Limite',result['error'])
        self.assertEqual(len(skill.calls),1)

    def test_results_partial_retain_items_and_warn(self):
        skill=FakeSkill([{'results':[{'path':'a.mp3'}], 'timed_out':True}])
        plan=TaskPlanner().create('Encontre arquivos')
        result=TaskExecutor(skill,plan).execute('search_files',{'query':'a'})
        self.assertEqual(result['results'],[{'path':'a.mp3'}])
        self.assertEqual(result['_aaa_verification']['status'],'partial')


class AgentIntegrationTests(unittest.TestCase):
    @staticmethod
    def _extract_method(name):
        source=(Path(__file__).parent/'agent.py').read_text(encoding='utf8')
        tree=ast.parse(source)
        obj=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='Agent')
        return next(n for n in obj.body if isinstance(n,ast.FunctionDef) and n.name==name)

    def test_live_agent_methods_reference_new_executor(self):
        for method in ('ask','ask_stream'):
            text=ast.unparse(self._extract_method(method))
            self.assertIn('self.agent_core.begin(text)',text)
            self.assertIn('aaa_session.executor.execute(effective_name, args)',text)
            self.assertIn('aaa_session.plan.instruction()',text)

    def test_ask_routes_tool_through_verifier_and_preserves_memory_on_failure(self):
        # Executes the actual ask() function from agent.py via AST, without
        # importing LM Studio, OpenAI, microphone, or Windows-only packages.
        globals_={
            'is_general_quotation_request':is_general_quotation_request,
            'TaskController':TaskController,
            'TaskCompletion':TaskCompletion,
            'parse_folder_request':__import__('explicit_folder_controller').parse_folder_request,
            'json':json,
        }
        exec(compile(ast.Module(body=[self._extract_method('ask')],type_ignores=[]),
             'agent.py','exec'),globals_)
        ask=globals_['ask']

        class Call:
            id='one'
            function=SimpleNamespace(name='open_file',
                arguments=json.dumps({'path':r'C:\Música\a.mp3'}))
        class Message:
            def __init__(self, text, calls):
                self.content=text
                self.tool_calls=calls
            def model_dump(self, exclude_none=True):
                return {'role':'assistant','content':self.content or '',
                        **({'tool_calls':[{'id':'one','type':'function',
                           'function':{'name':'open_file',
                           'arguments':json.dumps({'path':r'C:\Música\a.mp3'})}}]}
                           if self.tool_calls else {})}
        replies=[
            SimpleNamespace(choices=[SimpleNamespace(finish_reason='tool_calls',
                   message=Message(None,[Call()]))]),
            SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
                   message=Message('Não consegui abrir o arquivo.',[]))])
        ]
        def complete(**kwargs):
            return replies.pop(0)

        with tempfile.TemporaryDirectory() as td:
            nav=NavigationContext(Path(td)/'memory.db')
            skill=FakeSkill([{'opened':r'D:\Old\wrong.mp3'}])
            fake=SimpleNamespace(
                navigation=nav, skills_manager=skill, agent_core=AgentCore(skill),
                developer_context=SimpleNamespace(observe=lambda *a,**k:None),
                client=SimpleNamespace(chat=SimpleNamespace(
                    completions=SimpleNamespace(create=complete))),
                history=[{'role':'system','content':'BASE'}],tool_schemas=[],
                config={'lm_studio':{'temperature':0.2}},dual_channel=False,
                _active_development_skill=False,
                _contextual_media_action=lambda text:None,
                _contextual_file_action=lambda text:None,
                _explicit_folder_action=lambda text:None,
                _get_model=lambda :'mock',
                _clean_tool_history=lambda :None,
                _update_navigation_instruction=lambda :None,
                _completion_messages=lambda instruction:[],
                _is_simple_greeting=lambda text:False,
                _project_operation=lambda name,args,completed:name,
                _project_result_diagnostics=lambda name,args,result:result,
                _ground_project_inspection=lambda name,args,result,text:result,
                _is_internal_response=lambda content:False,
                _final_channels=lambda content,model:(content,content),
            )
            response=ask(fake,'Abra o arquivo C:\\Música\\a.mp3')
            self.assertIn('Não consegui',response)
            tool_results=[x for x in fake.history if x.get('role')=='tool']
            self.assertEqual(len(tool_results),1)
            self.assertIn('Verificação AAA',tool_results[0]['content'])
            self.assertNotIn('active_file',nav.state)
            self.assertEqual(len(skill.calls),1)


class CompletionAccountingTests(unittest.TestCase):
    def test_failed_functional_test_is_counted_even_with_aaa_error(self):
        tracker = TaskCompletion('Corrija o código e execute os testes.', True)
        tracker.observe('developer_run_python', {'path': 'a.py'},
                        {'error': 'Verificação AAA: exit code 2', 'executed': True,
                         'passed': False, 'exit_code': 2})
        self.assertEqual(len(tracker.functional_tests), 1)
        self.assertEqual(len(tracker.test_failures), 1)
        self.assertEqual(len(tracker.failures), 1)

    def test_partial_write_is_not_counted_as_completed(self):
        tracker = TaskCompletion('Corrija o código Python.', True)
        tracker.observe('developer_add_project_files', {}, {
            'success': True,
            '_aaa_verification': {'status': 'partial', 'detail': 'arquivos ausentes'}})
        self.assertEqual(len(tracker.writes), 0)

    def test_corrija_is_real_write_intent(self):
        self.assertTrue(TaskController('Corrija este arquivo').write_authorized)
        self.assertFalse(TaskController('Não corrija este arquivo').write_authorized)

    def test_no_false_positive_when_verified_false(self):
        self.assertEqual(ResultVerifier().verify('developer_replace_file',
                         {}, {'success': True, 'verified': False}).status, 'failed')


class ExperienceStoreTests(unittest.TestCase):
    def test_sqlite_persistence_without_file_paths_or_request_text(self):
        with tempfile.TemporaryDirectory() as td:
            location=Path(td)/'jarvis.db'
            store=ExperienceStore(location)
            store.record('sessao1','open_file','verified',1)
            store2=ExperienceStore(location)
            entries=store2.recent()
            self.assertEqual(len(entries),1)
            self.assertEqual(entries[0]['tool'],'open_file')
            self.assertEqual(entries[0]['status'],'verified')
            self.assertNotIn('path', entries[0])

    def test_executor_writes_verified_experience(self):
        with tempfile.TemporaryDirectory() as td:
            store=ExperienceStore(Path(td)/'jarvis.db')
            tool=FakeSkill([{'opened':r'C:\Música\file.mp3'}])
            session=AgentCore(tool, experience_store=store).begin('Abra o arquivo da pasta Música.')
            result=session.executor.execute('open_file',{'path':r'C:\Música\file.mp3'})
            self.assertIn('opened',result)
            events=store.recent()
            self.assertEqual(events[0]['status'],'verified')
            self.assertEqual(events[0]['attempts'],1)
            import sqlite3
            with sqlite3.connect(str(store.db_path)) as db:
                rows=db.execute('SELECT * FROM aaa_tool_experiences').fetchall()
                self.assertNotIn('file.mp3',str(rows))

    def test_storage_failure_never_breaks_file_action(self):
        class BrokenStore:
            def record(self,*args):
                raise OSError('simulated sqlite outage')
        plan=TaskPlanner().create('Abra um arquivo local')
        tool=FakeSkill([{'opened':r'C:\file.mp3'}])
        result=TaskExecutor(tool,plan,experience_store=BrokenStore(),session_id='s1').execute(
            'open_file',{'path':r'C:\file.mp3'})
        self.assertEqual(result['opened'],r'C:\file.mp3')

    def test_recorded_retry_attempts_is_two(self):
        with tempfile.TemporaryDirectory() as td:
            store=ExperienceStore(Path(td)/'db.sqlite')
            tool=FakeSkill([{'error':'ConnectionError: temporarily unavailable'},
                            {'results':[]}])
            executor=AgentCore(tool,experience_store=store).begin('Encontre a pasta Música.').executor
            result=executor.execute('search_directories',{'query':'Música'})
            self.assertEqual(store.recent()[0]['attempts'],2)


if __name__=='__main__':
    unittest.main()
