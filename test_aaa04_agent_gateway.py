"""AAA 04 — actual Agent.ask / ask_stream with simulated safe local tools."""
import unittest
from test_aaa03_agent_gateway import GatewayTests


class AgentGateway04(unittest.TestCase):
    def setUp(self):
        helper=GatewayTests()
        self.agent,self.skills=helper._make()
        self.addCleanup(lambda: [c() for c in self.agent._test_cleanups] if hasattr(self.agent,'_test_cleanups') else None)
        # The test fixture used by the original AAA03 gateway creates a
        # TemporaryDirectory via addCleanup. Keep a reference here so it
        # survives until this test is over (and remove when done).
        self._helper=helper
        self.addCleanup(helper.doCleanups)
        self.c=r'C:\Users\rodco\Videos'
        self.skills.config['paths']['allowed_roots']=[self.c]
        self.skills.replies[self.c]=[
            self.c+r'\01.txt',self.c+r'\02.mp4',
            self.c+r'\03.mkv',self.c+r'\04.mp3']

    def test_noisy_voice_and_followup_ask_without_model(self):
        answer=self.agent.ask('Jarvis, abra a pasta de vídeo e reproduzo o primeiro vídeo que encontrar na pasta.')
        self.assertIn('Abri o arquivo 1',answer)
        self.assertEqual(self.skills.opened_directories,[self.c])
        self.agent.navigation.observe('open_directory',{'opened_directory':self.c},{'path':self.c})
        second=self.agent.ask('e produza o próximo arquivo.')
        self.assertIn('arquivo 2',second)
        self.assertEqual(self.skills.opened[-1],self.c+r'\03.mkv')
        third=self.agent.ask('Da pasta de vídeos reproduza o segundo arquivo.')
        self.assertIn('arquivo 2',third)
        self.assertEqual(self.skills.opened[-1],self.c+r'\03.mkv')
        self.assertEqual(len(self.agent.history),6)

    def test_stream_contextual_list_next_previous(self):
        spoken=[]
        for request in ('Procure pela pasta vídeos no disco C e reproduza o primeiro vídeo.',
                        'Liste os arquivos dentro dela.',
                        'Agora o próximo.',
                        'Reproduza o anterior.'):
            result=self.agent.ask_stream(request,spoken.append)
            self.assertEqual(result,spoken[-1])
        self.assertEqual(len(spoken),4)
        self.assertIn('01.txt',spoken[1])
        self.assertEqual(self.skills.opened,[self.c+r'\02.mp4',
                                              self.c+r'\03.mkv',
                                              self.c+r'\02.mp4'])

    def test_stream_rejects_audio_video_substitution(self):
        spoken=[]
        result=self.agent.ask_stream(
            'Procure pela pasta vídeos no disco local C e reproduza o primeiro arquivo de música.',spoken.append)
        self.assertEqual(result,spoken[-1])
        self.assertEqual(self.skills.opened,[self.c+r'\04.mp3'])


if __name__=='__main__':
    unittest.main()
