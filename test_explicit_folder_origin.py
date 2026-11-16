"""Regressões da troca explícita de origem e cursor contextual do JARVIS."""
import ast
import ntpath
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from action_policy import ActionPolicy
from context_state import NavigationContext
from explicit_folder_controller import ExplicitFolderController, parse_folder_request, fold
from quote_intent import is_general_quotation_request


class FakeTools:
    def __init__(self):
        self.dirs = [r'D:\Music Lib', r'C:\Música', r'C:\Users\rodco\Vídeos']
        self.files = {
            self.dirs[0]: [r'D:\Music Lib\01.mp3', r'D:\Music Lib\02.mp3'],
            self.dirs[1]: [r'C:\Música\01.mp3', r'C:\Música\02.mp3'],
            self.dirs[2]: [r'C:\Users\rodco\Vídeos\01.mp4',
                           r'C:\Users\rodco\Vídeos\02.mp3'],
        }
        self.calls = []
        self.fail_open = False
        self.truncated = False

    def execute(self, name, args):
        self.calls.append((name, dict(args)))
        if name == 'search_directories':
            q=fold(args['query'])
            drive = args.get('drive')
            dirs = [d for d in self.dirs
                    if (not drive or ntpath.splitdrive(d)[0].upper() == drive+':')
                    and (fold(ntpath.basename(d)) == q or
                         (args.get('minimum_score',60) == 50 and
                          q == 'mosica' and fold(ntpath.basename(d)) == 'musica'))]
            return {'results': [{'path': d, 'index': i+1, 'score': 100} for i,d in enumerate(dirs)],
                    'truncated': False}
        if name == 'search_files_in_directory':
            items = self.files.get(args['directory'], [])
            if args.get('extension'):
                items = [p for p in items if p.lower().endswith('.'+args['extension'])]
            return {'results': [{'path':p, 'index':i+1} for i,p in enumerate(items)],
                    'scope':args['directory'], 'truncated':self.truncated}
        if name == 'open_file':
            return {'error':'simulated open failure'} if self.fail_open else {'opened':args['path']}
        raise AssertionError(name)


def previous_memory(nav):
    folder = r'D:\Music Lib'
    results = [{'path': folder+r'\01.mp3'}, {'path':folder+r'\02.mp3'}]
    nav.observe('search_files_in_directory', {'scope':folder,'results':results})
    nav.observe('open_file', {'opened':results[0]['path']})
    return nav.state['media_sequence'].copy()


class ExplicitOriginRegression(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.navigation = NavigationContext(Path(tmp.name)/'test.db')
        self.tools = FakeTools()
        self.agent = SimpleNamespace(navigation=self.navigation,
                                     skills_manager=self.tools, history=[])
        self.controller = ExplicitFolderController(self.agent)
        self.old = previous_memory(self.navigation)

    def test_explicit_new_origins_are_not_relative_navigation(self):
        for query in [
            'Agora encontre outra pasta, uma pasta chamada MÔSICA no disco local C. Abra o primeiro arquivo dessa pasta.',
            'Encontre a pasta vídeos. Abra o primeiro arquivo MP3 que encontrar na pasta.',
            'Encontre a pasta Music Lib e abra o primeiro arquivo contido nesta pasta.',
        ]:
            with self.subTest(query=query):
                self.assertIsNone(self.navigation.media_navigation(query))

    def test_new_drive_precedes_old_cursor(self):
        response = self.controller.handle(
            'Agora encontre outra pasta, uma pasta chamada MÚSICA no disco local C. Abra o primeiro arquivo dessa pasta.')
        self.assertIn('disco C', response)
        self.assertEqual(self.tools.calls[-1], ('open_file', {'path':r'C:\Música\01.mp3'}))
        self.assertEqual(self.navigation.state['media_sequence']['directory'],r'C:\Música')
        self.assertEqual(self.navigation.state['media_sequence']['current_index'],0)
        self.assertEqual(self.navigation.media_navigation('Agora reproduza o próximo arquivo')['path'],
                         r'C:\Música\02.mp3')
        self.assertEqual(self.tools.calls[0], ('search_directories', {'query':'musica','drive':'C'}))

    def test_speech_mosica_falls_back_without_reusing_old(self):
        response = self.controller.handle(
            'Agora encontre outra pasta, uma pasta chamada MÔSICA no disco local C. Abra o primeiro arquivo dessa pasta.')
        self.assertIn('arquivo 1', response)
        self.assertIn(('search_directories',{'query':'mosica','drive':'C','minimum_score':50}),self.tools.calls)
        self.assertEqual(self.tools.calls[-1][1]['path'],r'C:\Música\01.mp3')

    def test_mp3_filter_in_videos_folder(self):
        self.assertIn('arquivo 1', self.controller.handle(
            'Encontre a pasta vídeos. Abra o primeiro arquivo MP3 que encontrar na pasta.'))
        self.assertIn(('search_files_in_directory',
                      {'directory':r'C:\Users\rodco\Vídeos','extension':'mp3'}), self.tools.calls)
        self.assertEqual(self.tools.calls[-1][1]['path'],r'C:\Users\rodco\Vídeos\02.mp3')

    def test_missing_folder_preserves_old_cursor(self):
        before=self.navigation.state['media_sequence'].copy()
        result=self.controller.handle('Encontre a pasta inexistente no disco C. Abra o primeiro arquivo.')
        self.assertIn('Não encontrei',result)
        self.assertEqual(self.navigation.state['media_sequence'],before)
        self.assertFalse(any(name=='open_file' for name,_ in self.tools.calls))
        self.assertEqual(self.navigation.media_navigation('Carregue o próximo arquivo')['path'],
                         r'D:\Music Lib\02.mp3')

    def test_other_drive_does_not_match_same_name(self):
        result=self.controller.handle('Encontre a pasta Music Lib no disco C. Abra o primeiro arquivo.')
        self.assertIn('Não encontrei',result)
        self.assertFalse(any(name=='open_file' for name,_ in self.tools.calls))

    def test_open_failure_preserves_old_cursor(self):
        self.tools.fail_open=True
        result=self.controller.handle('Encontre a pasta Música no disco C e abra o primeiro arquivo.')
        self.assertIn('Não consegui abrir',result)
        self.assertEqual(self.navigation.state['media_sequence'],self.old)

    def test_ambiguous_folder_needs_clarification(self):
        self.tools.dirs=[r'C:\Music Lib',r'D:\Music Lib']
        self.tools.files[r'C:\Music Lib']=[r'C:\Music Lib\01.mp3']
        result=self.controller.handle('Encontre a pasta Music Lib e abra o primeiro arquivo.')
        self.assertIn('mais de uma',result)
        self.assertFalse(any(n=='open_file' for n,a in self.tools.calls))

    def test_truncated_last_not_opened(self):
        self.tools.truncated=True
        result=self.controller.handle('Encontre a pasta Música no disco C e abra o último arquivo.')
        self.assertIn('truncada',result)
        self.assertFalse(any(n=='open_file' for n,a in self.tools.calls))
        self.assertEqual(self.navigation.state['media_sequence'],self.old)

    def test_no_reuse_in_context_instruction(self):
        text='Encontre a pasta vídeos. Abra o primeiro arquivo MP3 que encontrar na pasta.'
        instruction=self.navigation.instruction(text)
        self.assertIn('NOVA ORIGEM',instruction)
        self.assertNotIn(r'D:\Music Lib',instruction)

    def test_llm_policy_blocks_stale_other_drive(self):
        request='Agora encontre a pasta Música no disco C. Abra o primeiro arquivo.'
        policy=ActionPolicy(self.navigation)
        self.assertIn('outra pasta',policy.deny_reason(
            'open_file', {'path':r'D:\Music Lib\01.mp3'},request))
        self.assertIsNone(policy.deny_reason(
            'open_file', {'path':r'C:\Música\01.mp3'},request))
        self.assertIn('unidade',policy.deny_reason(
            'open_file', {'path':r'D:\Música\01.mp3'},request))

    def test_simple_relative_commands_unchanged(self):
        self.assertFalse(parse_folder_request('Encontre o primeiro arquivo dessa pasta').explicit_new_origin)
        self.assertFalse(parse_folder_request('Carregue o próximo arquivo').explicit_new_origin)
        self.assertEqual(self.navigation.media_navigation('Carregue o próximo arquivo')['position'],2)
        self.assertFalse(parse_folder_request('Abra o primeiro arquivo dessa pasta').explicit_new_origin)
        self.assertEqual(self.navigation.media_navigation('Abra o primeiro arquivo dessa pasta')['position'],1)

    def test_unsafe_script_not_opened(self):
        self.tools.files[r'C:\Música']=[r'C:\Música\aaa.bat']
        result=self.controller.handle('Encontre a pasta Música no disco C e abra o primeiro arquivo.')
        self.assertIn('executável',result)
        self.assertFalse(any(name=='open_file' for name,_ in self.tools.calls))


def actual_agent_function(name):
    code=ast.parse((Path(__file__).parent/'agent.py').read_text(encoding='utf8'))
    cls=next(n for n in code.body if isinstance(n,ast.ClassDef) and n.name=='Agent')
    body=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    globals_={'ExplicitFolderController':ExplicitFolderController,
              'parse_folder_request':parse_folder_request,
              'is_general_quotation_request':is_general_quotation_request}
    exec(compile(ast.Module(body=[body],type_ignores=[]),'agent.py','exec'),globals_)
    return globals_[name]


class EntryPointRegression(unittest.TestCase):
    def test_ask_and_stream_enter_explicit_origin_first(self):
        for name in ('ask','ask_stream'):
            with self.subTest(entry=name):
                tmp=tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                nav=NavigationContext(Path(tmp.name)/'memory.db')
                previous_memory(nav)
                tools=FakeTools()
                Agent=type('Agent',(),{
                    'ask':actual_agent_function('ask'),
                    'ask_stream':actual_agent_function('ask_stream'),
                    '_explicit_folder_action':actual_agent_function('_explicit_folder_action'),
                    '_contextual_media_action':lambda self,text: (_ for _ in ()).throw(AssertionError('old context called')),
                    '_contextual_file_action':lambda self,text: (_ for _ in ()).throw(AssertionError('old context file called')),
                })
                a=Agent()
                a.navigation=nav;a.skills_manager=tools;a.history=[]
                text='Encontre a pasta vídeos. Abra o primeiro arquivo MP3 que encontrar na pasta.'
                if name=='ask':
                    result=a.ask(text)
                else:
                    output=[]
                    result=a.ask_stream(text,output.append)
                    self.assertEqual(output,[result])
                self.assertIn('arquivo 1',result)
                self.assertEqual(tools.calls[-1][1]['path'],r'C:\Users\rodco\Vídeos\02.mp3')


if __name__=='__main__':
    unittest.main()
