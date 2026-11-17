"""AAA06 exercises the actual Agent.ask and Agent.ask_stream with grounded FS."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import test_aaa05_integrated as fixture05
import navigation_workspace as ws_mod


class Gateway06(unittest.TestCase):
    def setUp(self):
        original=fixture05.FullStack05()
        original.setUp()
        self.agent=original.agent
        self.addCleanup(original.doCleanups)
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp=Path(td.name)
        self.folder=self.tmp/'C'/'Videos'
        self.folder.mkdir(parents=True)
        (self.folder/'a.mp4').write_text('a')
        (self.folder/'b.mkv').write_text('b')
        (self.folder/'c.mp3').write_text('c')
        self.agent.config['paths']['allowed_roots']=[str(self.folder)]
        self.skills=type('MockOpenSkills',(),{})()
        self.skills.config=self.agent.config
        self.skills.opened=[]
        self.skills.directories=[]
        def execute(name,args):
            if name=='open_file':
                self.skills.opened.append(args['path'])
                return {'opened':args['path']}
            if name=='open_directory':
                self.skills.directories.append(args['path'])
                return {'opened_directory':args['path']}
            raise AssertionError(name)
        self.skills.execute=execute
        self.agent.skills_manager=self.skills
        self._original_drive=ws_mod._drive
        d=str(self.folder)
        self._patcher=patch.object(ws_mod,'_drive',lambda p:'C:' if str(p).startswith(d) else self._original_drive(p))
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        # A direct workspace command must not call the LLM.
        self.agent._get_model=lambda: (_ for _ in ()).throw(AssertionError('Não deveria chamar LLM'))

    def test_ask_context_page_and_play_without_model(self):
        result=self.agent.ask('Entre na pasta Videos')
        self.assertIn('Entrei no contexto Videos',result)
        first=self.agent.ask('Reproduza o primeiro vídeo')
        self.assertIn('vídeo número 1',first)
        self.assertEqual(Path(self.skills.opened[-1]).name,'a.mp4')
        next_one=self.agent.ask('Agora o próximo')
        self.assertIn('vídeo número 2',next_one)
        self.assertEqual(Path(self.skills.opened[-1]).name,'b.mkv')
        self.assertEqual(len(self.agent.history),7)

    def test_ask_stream_stays_on_same_workspace(self):
        spoken=[]
        for req in ('Entre na pasta Videos', 'Mostre os vídeos',
                    'Reproduza o primeiro vídeo', 'O próximo'):
            result=self.agent.ask_stream(req,spoken.append)
            self.assertEqual(result,spoken[-1])
        self.assertEqual(Path(self.skills.opened[-1]).name,'b.mkv')
        self.assertIn('Página 1',spoken[1])

    def test_preference_response_routes_without_invoking_model(self):
        self.agent.ask('Entre na pasta Videos')
        question=self.agent.ask('Reproduza uma música')
        self.assertIn('Prefere escolher',question)
        answer=self.agent.ask('sem preferência')
        self.assertIn('música número',answer)
        self.assertEqual(Path(self.skills.opened[-1]).name,'c.mp3')

    def test_session_history_contains_workspace_turns(self):
        self.agent.ask('Entre na pasta Videos')
        self.agent.ask('Mostre os vídeos')
        self.assertEqual([x['role'] for x in self.agent.history],
                         ['system','user','assistant','user','assistant'])

    def test_reading_dialogue_not_hijacked_by_file_workspace(self):
        self.agent.ask('Entre na pasta Videos')
        from adaptive_toolset import AdaptiveToolset
        scope=self.agent.autonomy.catalog.select('Quando viveu Enoque?',has_workspace=True)
        self.assertEqual(scope.category,'knowledge')
        self.assertIsNone(self.agent.navigation_workspace.handle(
            'Quando viveu Enoque?',self.skills,self.agent.navigation))


if __name__=='__main__':unittest.main()
