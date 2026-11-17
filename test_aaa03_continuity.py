"""AAA 03 regression: pending tasks survive turns, grounding, Windows media folders."""
from pathlib import Path
import tempfile
import unittest
import ntpath

from context_state import NavigationContext
from context_resolver import ContextResolver, drive_of
from task_continuity import TaskContinuityManager
from tools import search_directories, search_files_in_directory


class FakeSkills:
    def __init__(self, folders=None, roots=None):
        self.folders = list(folders or [])
        self.config = {'paths': {'allowed_roots': roots or []}}
        self.calls = []
        self.opened = []
        self.opened_directories = []
        self.open_reply_override = None
        self.fail_listing = False
        self.replies = {}

    def execute(self, name, args):
        self.calls.append((name, dict(args)))
        if name == 'search_directories':
            found = [f for f in self.folders
                     if (not args.get('drive') or drive_of(f)==args['drive'])
                     and ntpath.basename(f).casefold() == args['query'].casefold()]
            return {'results':[{'index':i+1,'path':f,'name':ntpath.basename(f)}
                               for i,f in enumerate(found)], 'truncated':False}
        if name == 'search_files_in_directory':
            if self.fail_listing:
                return {'error':'I/O error'}
            files = self.replies.get(args['directory'], [])
            if args.get('extensions'):
                allowed = set(args['extensions'].split(','))
                files = [x for x in files if ntpath.splitext(x)[1].lower().lstrip('.') in allowed]
            if args.get('extension'):
                files = [x for x in files if x.lower().endswith('.'+args['extension'])]
            return {'scope':args['directory'], 'results':[{'path':x,'index':i+1}
                                                         for i,x in enumerate(files)],
                    'truncated':False}
        if name == 'open_directory':
            self.opened_directories.append(args['path'])
            return {'opened_directory':args['path']}
        if name == 'open_file':
            self.opened.append(args['path'])
            return {'opened':self.open_reply_override or args['path']}
        raise AssertionError(name)


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.db=Path(td.name)/'jarvis.db'
        self.nav=NavigationContext(self.db)
        self.agent=TaskContinuityManager(self.db)
        self.folders=[r'C:\Users\rodco\Videos', r'D:\Videos']
        self.skills=FakeSkills(self.folders)
        self.skills.replies={
            self.folders[0]:[r'C:\Users\rodco\Videos\a.txt', r'C:\Users\rodco\Videos\b.mp4',
                             r'C:\Users\rodco\Videos\c.mkv'],
            self.folders[1]:[r'D:\Videos\z.mp4']}
        self.request='Jarvis por favor abra o primeiro arquivo de vídeo da pasta vídeos'

    def test_full_log_dialogue_across_three_turns(self):
        first=self.agent.handle(self.request,self.skills,self.nav)
        self.assertIn('mais de uma pasta',first)
        self.assertEqual(self.agent.pending()['status'],'awaiting_choice')
        self.assertEqual(self.skills.opened,[])
        second=self.agent.handle('Vídeos da pasta Vídeos do disco local C.',self.skills,self.nav)
        self.assertIn('Abri o arquivo 1',second)
        self.assertEqual(self.skills.opened,[r'C:\Users\rodco\Videos\b.mp4'])
        self.assertIsNone(self.agent.pending())
        self.assertEqual(self.agent.selected_directory(),r'C:\Users\rodco\Videos')
        third=self.agent.handle('Liste os arquivos dentro dela.',self.skills,self.nav)
        self.assertIn('a.txt',third)
        self.assertIn('b.mp4',third)
        self.assertEqual(len(self.skills.opened),1)
        self.assertIsNone(self.agent.pending())

    def test_uncertain_path_does_not_invent(self):
        first=self.agent.handle(self.request,self.skills,self.nav)
        self.assertIn('mais de uma',first)
        self.assertIsNone(self.agent.selected_directory())
        result=self.agent.handle('Liste os arquivos dentro dela.',self.skills,self.nav)
        self.assertIn('mais de uma pasta candidata',result)
        self.assertEqual(self.skills.opened,[])

    def test_canonical_root_is_selected_even_if_candidates_multiple(self):
        self.skills.config['paths']['allowed_roots']=[r'C:\Users\rodco\Videos','D:\\']
        result=self.agent.handle(self.request,self.skills,self.nav)
        self.assertIn('Abri o arquivo 1',result)
        self.assertEqual(self.skills.opened[-1],r'C:\Users\rodco\Videos\b.mp4')

    def test_pending_survives_restart(self):
        self.assertIn('mais de uma',self.agent.handle(self.request,self.skills,self.nav))
        recreated=TaskContinuityManager(self.db)
        self.assertEqual(recreated.pending()['request'],self.request)
        result=recreated.handle('no disco C',self.skills,NavigationContext(self.db))
        self.assertIn('Abri',result)
        self.assertIsNone(TaskContinuityManager(self.db).pending())

    def test_false_open_confirmation_is_not_said_as_success(self):
        self.skills.open_reply_override=r'D:\Videos\wrong.mp4'
        self.agent.handle(self.request,self.skills,self.nav)
        result=self.agent.handle('do disco C',self.skills,self.nav)
        self.assertIn('Não foi possível confirmar',result)
        self.assertIsNotNone(self.agent.pending())
        self.assertNotIn('active_file',self.nav.state)

    def test_missing_folder_never_reuses_previous_media(self):
        old=r'D:\Music Lib\old.mp3'
        self.nav.observe('open_file',{'opened':old},{'path':old})
        self.assertIn('mais de uma',self.agent.handle(self.request,self.skills,self.nav))
        result=self.agent.handle('do disco E',self.skills,self.nav)
        self.assertIn('Não encontrei',result)
        self.assertNotIn(old,self.skills.opened)
        self.assertEqual(self.nav.state['active_file'],old)

    def test_cancel_pending_without_deleting_files(self):
        self.agent.handle(self.request,self.skills,self.nav)
        result=self.agent.handle('cancele',self.skills,self.nav)
        self.assertIn('Cancelei',result)
        self.assertIsNone(self.agent.pending())
        self.assertEqual(self.skills.opened,[])

    def test_unrelated_turn_does_not_resume_pending(self):
        self.agent.handle(self.request,self.skills,self.nav)
        self.assertIsNone(self.agent.handle('Quem escreveu a Odisseia?',self.skills,self.nav))
        self.assertEqual(self.skills.opened,[])
        self.assertIsNotNone(self.agent.pending())

    def test_listing_failure_stays_pending(self):
        self.skills.config['paths']['allowed_roots']=[r'C:\Users\rodco\Videos']
        self.skills.fail_listing=True
        result=self.agent.handle(self.request,self.skills,self.nav)
        self.assertIn('Não consegui listar',result)
        self.assertEqual(self.agent.pending()['status'],'list_failed')
        self.assertEqual(self.skills.opened,[])

    def test_file_and_folder_context_references_from_db(self):
        self.skills.config['paths']['allowed_roots']=[r'C:\Users\rodco\Videos']
        self.agent.handle(self.request,self.skills,self.nav)
        manager2=TaskContinuityManager(self.db)
        nav2=NavigationContext(self.db)
        result=manager2.handle('Liste os arquivos dentro dela.',self.skills,nav2)
        self.assertIn('c.mkv',result)
        self.assertEqual(nav2.state['active_directory'],self.folders[0])

    def test_no_new_permission_from_clarification(self):
        self.agent.handle(self.request,self.skills,self.nav)
        self.agent.handle('do disco C',self.skills,self.nav)
        calls=[n for n,a in self.skills.calls]
        self.assertEqual(calls.count('open_file'),1)
        self.assertNotIn('developer_delete_file',calls)

    def test_followup_first_file_without_selected_folder_cannot_use_old_media(self):
        self.nav.observe('search_files_in_directory',
                         {'scope':r'D:\Music Lib', 'results':[{'path':r'D:\Music Lib\previous.mp3'}]})
        self.agent.handle(self.request,self.skills,self.nav)
        answer=self.agent.handle('Abra o primeiro arquivo dessa pasta.',self.skills,self.nav)
        self.assertIn('mais de uma pasta candidata',answer)
        self.assertFalse(self.skills.opened)

    def test_choose_second_folder_by_index(self):
        self.assertIn('mais de uma',self.agent.handle(self.request,self.skills,self.nav))
        result=self.agent.handle('É a segunda pasta.',self.skills,self.nav)
        self.assertIn('Abri',result)
        self.assertEqual(self.skills.opened, [r'D:\Videos\z.mp4'])

    def test_explicit_path_must_match_candidate(self):
        self.agent.handle(self.request,self.skills,self.nav)
        self.assertIsNone(self.agent.handle(r'C:\Somewhere\MadeUp\Videos', self.skills,self.nav))
        self.assertEqual(self.skills.opened,[])
        self.assertIn('mais de uma pasta candidata',self.agent.handle('Abra o primeiro dessa pasta',self.skills,self.nav))

    def test_last_video_selects_last_filtered_item(self):
        self.skills.config['paths']['allowed_roots']=[self.folders[0]]
        result=self.agent.handle('Abra o último vídeo da pasta Vídeos',self.skills,self.nav)
        self.assertIn('arquivo 2',result)
        self.assertEqual(self.skills.opened[-1],r'C:\Users\rodco\Videos\c.mkv')

    def test_initial_partial_search_requires_precise_location(self):
        class PartialSearch(FakeSkills):
            def execute(self,name,args):
                r=super().execute(name,args)
                if name=='search_directories':
                    r['truncated']=True
                return r
        skills=PartialSearch([self.folders[0]])
        skills.replies=self.skills.replies
        result=self.agent.handle(self.request,skills,self.nav)
        self.assertIn('interrompida',result)
        self.assertFalse(skills.opened)

    def test_new_explicit_request_supersedes_previous_pending(self):
        self.agent.handle(self.request,self.skills,self.nav)
        before=self.agent.pending()['id']
        result=self.agent.handle('Abra o primeiro vídeo da pasta Vídeos no disco C',self.skills,self.nav)
        self.assertIn('Abri',result)
        self.assertIsNone(self.agent.pending())
        self.assertEqual(self.skills.opened,[r'C:\Users\rodco\Videos\b.mp4'])

    def test_traversal_path_returned_by_tool_is_not_opened(self):
        self.skills.config['paths']['allowed_roots']=[self.folders[0]]
        self.skills.replies[self.folders[0]]=[r'C:\Users\rodco\Videos\..\secret.mp4']
        answer=self.agent.handle(self.request,self.skills,self.nav)
        self.assertIn('fora da pasta',answer)
        self.assertEqual(self.skills.opened,[])

    def test_voice_directory_reference_and_persistence_of_selected_location(self):
        self.skills.config['paths']['allowed_roots']=[self.folders[0]]
        self.assertIn('Abri',self.agent.handle(self.request,self.skills,self.nav))
        for utterance in ('mostre os arquivos nela', 'liste o conteúdo dessa pasta'):
            with self.subTest(utterance=utterance):
                self.assertIn('a.txt',self.agent.handle(utterance,self.skills,self.nav))


class RealToolTests(unittest.TestCase):
    def test_search_includes_authorized_root_itself(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'Videos'
            root.mkdir()
            (root/'env'/'site-packages'/'videos').mkdir(parents=True)
            cfg={'paths':{'allowed_roots':[str(root)]},'file_search':{'timeout_seconds':5}}
            res=search_directories('videos',cfg)
            self.assertIn(str(root),[x['path'] for x in res['results']])
            self.assertNotIn(str(root/'env'/'site-packages'/'videos'),
                             [x['path'] for x in res['results']])

    def test_list_group_extensions_filters_before_pagination(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for i in range(15):
                (root/('a%02d.txt'%i)).write_text('text')
            (root/'z.mp4').write_text('mp4')
            (root/'x.mkv').write_text('mkv')
            cfg={'paths':{'allowed_roots':[str(root)],'max_search_results':12},
                 'file_search':{'timeout_seconds':5}}
            res=search_files_in_directory(str(root),cfg,extensions='mp4,mkv')
            self.assertEqual({r['name'] for r in res['results']},{'z.mp4','x.mkv'})
            self.assertFalse(res['truncated'])

    def test_extension_and_extensions_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as td:
            cfg={'paths':{'allowed_roots':[str(Path(td))]}}
            res=search_files_in_directory(td,cfg,extension='mp4',extensions='mp4,mkv')
            self.assertIn('error',res)

if __name__=='__main__':
    unittest.main()
