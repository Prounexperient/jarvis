"""AAA 04 — reproduce the reported Windows dialogue and cross-turn media safety.

Tools are simulated, while TaskContinuityManager, NavigationContext, Agent
entry points, SQLite, and both parser stages run their real Python code.
"""
import tempfile
import unittest
from pathlib import Path

from context_resolver import ContextResolver
from context_state import NavigationContext
from explicit_folder_controller import parse_folder_request
from task_continuity import TaskContinuityManager
from test_aaa03_continuity import FakeSkills
from test_aaa03_agent_gateway import GatewayTests


class MediaStateTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db=Path(temp.name)/'nav.db'
        self.nav=NavigationContext(self.db)
        self.manager=TaskContinuityManager(self.db)
        self.c=r'C:\Users\rodco\Videos'
        self.d=r'D:\Videos'
        self.skills=FakeSkills([self.c,self.d],roots=[self.c])
        self.skills.replies={
            self.c:[self.c+r'\01.txt',self.c+r'\02.mp4',self.c+r'\03.mkv',self.c+r'\04.mp3'],
            self.d:[self.d+r'\danger.mp4'],
        }

    def start_video(self):
        result=self.manager.handle('Procure pela pasta vídeos no disco local C e reproduza o primeiro vídeo',self.skills,self.nav)
        self.assertIn('Abri o arquivo 1',result)
        self.assertEqual(self.skills.opened[-1],self.c+r'\02.mp4')

    def test_spoken_names_and_noisy_drive(self):
        for utterance,folder,drive,kind in (
            ('Jarvis, abra a pasta de vídeo e reproduzo o primeiro vídeo que encontrar na pasta.',
             'videos',None,'video'),
            ('Contre a pasta de vídeos dentro do disco colocar o C e reproduza o primeiro arquivo de música que encontrar.',
             'videos','C','audio'),
            ('Procure pela pasta vídeos no disco local C e reproduza o primeiro áudio de música que encontrar.',
             'videos','C','audio'),
            ('Da pasta de vídeos reproduza o segundo arquivo.',
             'videos',None,None),
        ):
            with self.subTest(utterance=utterance):
                frame=ContextResolver().parse(utterance,has_media_context=True)
                self.assertEqual(frame['folder_name'],folder)
                self.assertEqual(frame['drive'],drive)
                self.assertEqual(frame['media_kind'],kind)
                self.assertTrue(frame['wants_open'])

    def test_actual_reported_sequence_and_next_media(self):
        result=self.manager.handle('Jarvis, abra a pasta de vídeo e reproduzo o primeiro vídeo que encontrar na pasta.',
                                   self.skills,self.nav)
        self.assertIn('Abri',result)
        self.assertEqual(self.skills.opened[-1],self.c+r'\02.mp4')
        self.assertEqual(self.skills.opened_directories,[self.c])
        # Simulate successful LLM open_directory tool call from the report.
        self.nav.observe('open_directory',{'opened_directory':self.c},{'path':self.c})
        result=self.manager.handle('e produza o próximo arquivo.',self.skills,self.nav)
        self.assertIn('arquivo 2',result)
        self.assertEqual(self.skills.opened[-1],self.c+r'\03.mkv')
        self.assertEqual(self.nav.state['media_sequence']['current_index'],1)
        result=self.manager.handle('Da pasta de vídeos reproduza o segundo arquivo.',self.skills,self.nav)
        self.assertIn('arquivo 2',result)
        self.assertEqual(self.skills.opened[-1],self.c+r'\03.mkv')

    def test_explicit_audio_request_rejects_first_video(self):
        result=self.manager.handle('Procure pela pasta vídeos no disco local C e reproduza o primeiro áudio de música que encontrar.',
                                   self.skills,self.nav)
        self.assertIn('Abri',result)
        self.assertEqual(self.skills.opened,[self.c+r'\04.mp3'])
        self.assertEqual(self.nav.state['media_sequence']['current_index'],0)

    def test_audio_not_found_never_falls_back_to_video(self):
        self.skills.replies[self.c]=[self.c+r'\02.mp4',self.c+r'\03.mkv']
        result=self.manager.handle('Procure pela pasta vídeos no disco C e reproduza o primeiro áudio que encontrar.',
                                   self.skills,self.nav)
        self.assertIn('Não encontrei arquivos',result)
        self.assertEqual(self.skills.opened,[])

    def test_compound_open_directory_must_be_verified_separately(self):
        class BrokenExplorer(FakeSkills):
            def execute(self,name,args):
                if name == 'open_directory':
                    return {'opened_directory':r'D:\OtherFolder'}
                return super().execute(name,args)
        bad = BrokenExplorer([self.c],roots=[self.c])
        bad.replies=self.skills.replies
        result=self.manager.handle('Abra a pasta de vídeos e reproduza o primeiro vídeo',bad,self.nav)
        self.assertIn('Abri o arquivo 1',result)
        self.assertIn('não consegui confirmar',result)
        self.assertEqual(bad.opened,[self.c+r'\02.mp4'])

    def test_switching_media_kind_freshly_lists_same_directory(self):
        self.start_video()
        before=len([1 for n,a in self.skills.calls if n=='search_files_in_directory'])
        result=self.manager.handle('Reproduza o primeiro arquivo de música.',self.skills,self.nav)
        self.assertIn('Abri',result)
        self.assertEqual(self.skills.opened[-1],self.c+r'\04.mp3')
        self.assertGreater(len([1 for n,a in self.skills.calls if n=='search_files_in_directory']),before)

    def test_listing_all_does_not_erase_playback_position(self):
        self.start_video()
        out=self.manager.handle('Liste os arquivos dentro dela.',self.skills,self.nav)
        self.assertIn('01.txt',out)
        self.assertEqual(self.nav.state['media_sequence']['current_index'],0)
        out=self.manager.handle('Agora o próximo.',self.skills,self.nav)
        self.assertIn('arquivo 2',out)
        self.assertEqual(self.skills.opened[-1],self.c+r'\03.mkv')

    def test_reverse_and_persisted_session(self):
        self.start_video()
        new=TaskContinuityManager(self.db)
        nav2=NavigationContext(self.db)
        self.assertEqual(new.selected_directory(),self.c)
        self.assertIn('arquivo 2',new.handle('Reproduza o próximo arquivo.',self.skills,nav2))
        self.assertIn('arquivo 1',new.handle('Volte ao anterior e reproduza.',self.skills,nav2))
        self.assertEqual(self.skills.opened[-1],self.c+r'\02.mp4')

    def test_no_media_position_cannot_run_next_in_new_folder(self):
        self.start_video()
        result=self.manager.handle('Procure outra pasta Vídeos no disco local D e reproduza o próximo arquivo.',
                                   self.skills,self.nav)
        self.assertIn('Preciso de uma posição',result)
        self.assertEqual(self.skills.opened,[self.c+r'\02.mp4'])

    def test_switching_drive_does_not_reuse_old_cursor(self):
        self.start_video()
        self.assertIn('Não encontrei',self.manager.handle(
            'Encontre a pasta vídeos no disco E e reproduza o primeiro vídeo',self.skills,self.nav))
        self.assertEqual(self.skills.opened,[self.c+r'\02.mp4'])

    def test_media_navigation_is_not_authorized_by_question(self):
        self.start_video()
        for text in ('Qual será o próximo vídeo?', 'Crie o próximo arquivo.',
                     'Não reproduza o próximo arquivo.', 'e produza um arquivo novo.',
                     'Se eu disser reproduza o próximo, o que acontece?'):
            with self.subTest(text=text):
                self.assertIsNone(self.manager.handle(text,self.skills,self.nav))
        self.assertEqual(self.skills.opened,[self.c+r'\02.mp4'])

    def test_different_active_directory_blocks_stale_cursor(self):
        self.start_video()
        self.nav.observe('open_directory',{'opened_directory':self.d},{'path':self.d})
        result=self.manager.handle('Reproduza o próximo arquivo',self.skills,self.nav)
        self.assertIn('pasta ativa mudou',result)
        self.assertEqual(self.skills.opened,[self.c+r'\02.mp4'])

    def test_bad_reply_does_not_advance_cursor(self):
        self.start_video()
        self.skills.open_reply_override=self.d+r'\danger.mp4'
        result=self.manager.handle('Reproduza o próximo arquivo',self.skills,self.nav)
        self.assertIn('Não consegui confirmar',result)
        self.assertEqual(self.nav.state['media_sequence']['current_index'],0)

    def test_truncated_list_blocks_last(self):
        self.start_video()
        previous=dict(self.nav.state['media_sequence'], truncated=True)
        self.nav._set('media_sequence',previous)
        opened_before=list(self.skills.opened)
        response=self.manager.handle('Reproduza o último arquivo de vídeo',self.skills,self.nav)
        self.assertIn('truncada',response)
        self.assertEqual(self.skills.opened,opened_before)

    def test_named_same_folder_relative_uses_verified_cursor(self):
        self.start_video()
        searches=len([1 for name,args in self.skills.calls if name=='search_directories'])
        response=self.manager.handle('Da pasta de vídeos reproduza o próximo arquivo.',
                                     self.skills,self.nav)
        self.assertIn('arquivo 2',response)
        self.assertEqual(self.skills.opened[-1],self.c+r'\03.mkv')
        self.assertEqual(len([1 for name,args in self.skills.calls if name=='search_directories']),searches)

    def test_media_permission_requires_exact_positional_target(self):
        from task_controller import TaskController
        self.start_video()
        good=self.c+r'\03.mkv'
        bad=self.c+r'\02.mp4'
        guard=TaskController('Agora o próximo',navigation=self.nav)
        self.assertIsNone(guard.inspect('open_file',{'path':good},
                                        verified_origin=self.c,verified_media_context=True))
        other=TaskController('Agora o próximo',navigation=self.nav)
        self.assertIsNotNone(other.inspect('open_file',{'path':bad},
                                            verified_origin=self.c,verified_media_context=True))
        foreign=TaskController('Agora o próximo',navigation=self.nav)
        self.assertIsNotNone(foreign.inspect('open_file',{'path':self.d+r'\danger.mp4'},
                                              verified_origin=self.c,verified_media_context=True))
        not_media=TaskController('Agora o próximo',navigation=self.nav)
        self.assertIsNotNone(not_media.inspect('developer_delete_file',{'path':good},
                                                verified_origin=self.c,verified_media_context=True))


if __name__=='__main__':
    unittest.main()
