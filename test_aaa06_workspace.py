"""AAA06 regressions: real filesystem catalogs, simulated Windows open APIs.

No LM Studio, microphone or file execution. Temporary directory trees model
separate disk roots; all file creation is restricted to TemporaryDirectory.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from context_state import NavigationContext
from navigation_workspace import NavigationWorkspace
import navigation_workspace as ws_mod


class OpenSkills:
    def __init__(self, config):
        self.config=config
        self.opened=[]
        self.directories=[]
        self.fail_open=False
    def execute(self,name,args):
        if name=='open_file':
            if self.fail_open: return {'error':'arquivo inacessível'}
            self.opened.append(args['path'])
            return {'opened':args['path']}
        if name=='open_directory':
            if self.fail_open: return {'error':'explorador indisponível'}
            self.directories.append(args['path'])
            return {'opened_directory':args['path']}
        raise AssertionError('Ferramenta inesperada '+name)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.base=Path(td.name)
        self.c=(self.base/'C'/'Users').resolve()
        self.d=(self.base/'D').resolve()
        self.c.mkdir(parents=True)
        self.d.mkdir(parents=True)
        self.videos=self.c/'Videos'
        self.music=self.c/'Music'
        self.documents=self.c/'Documents'
        self.videos.mkdir()
        self.music.mkdir()
        self.documents.mkdir()
        self.films=self.d/'Filmes'
        self.films.mkdir()
        for name in ['01.mp4','02.mkv','03.mp3','04.flac','05.txt']:
            (self.videos/name).write_text('amostra',encoding='utf8')
        for i in range(1,26):
            (self.music/f'musica{i:03d}.mp3').write_text('amostra',encoding='utf8')
        (self.music/'Rock').mkdir()
        (self.music/'Pop').mkdir()
        (self.music/'Rock'/'faixa.mp3').write_text('a',encoding='utf8')
        (self.films/'a.mkv').write_text('a',encoding='utf8')
        self.cfg={'paths':{'allowed_roots':[str(self.c),str(self.d)]},
                  'navigation_workspace':{'page_size':10,'scan_timeout_seconds':5,'search_timeout_seconds':5}}
        self.db=self.base/'jarvis.db'
        self.nav=NavigationContext(self.db)
        self.ws=NavigationWorkspace(self.db,self.cfg)
        self.skills=OpenSkills(self.cfg)
        original=ws_mod._drive
        def mocked_drive(p):
            # Real Windows tests use ntpath. On POSIX these are simulated disks.
            path=str(p)
            if str(self.d) in path: return 'D:'
            if str(self.c.parent) in path: return 'C:'
            return original(p)
        self.patcher=patch.object(ws_mod,'_drive',mocked_drive)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def send(self,text):
        return self.ws.handle(text,self.skills,self.nav)

    def test_catalog_classification_and_no_auto_play(self):
        reply=self.send('Vá para a pasta Videos do disco C')
        self.assertIn('Entrei no contexto Videos',reply)
        self.assertIn('2 vídeos',reply)
        self.assertIn('2 músicas',reply)
        self.assertEqual(self.skills.opened,[])
        self.assertEqual(self.ws.current()['drive'],'C:')

    def test_mixed_media_target_obeys_file_type(self):
        answer=self.send('Abra a pasta Videos e reproduza o primeiro áudio')
        self.assertIn('música número 1',answer)
        self.assertEqual(Path(self.skills.opened[-1]).name,'03.mp3')
        self.assertEqual(self.skills.directories,[str(self.videos)])

    def test_media_next_previous_and_last_use_category_cursor(self):
        self.send('Entre na pasta Videos do disco C')
        self.assertIn('vídeo número 1',self.send('Reproduza o primeiro vídeo'))
        self.assertEqual(Path(self.skills.opened[-1]).name,'01.mp4')
        self.assertIn('vídeo número 2',self.send('Agora o próximo'))
        self.assertIn('vídeo número 1',self.send('O anterior'))
        self.assertIn('vídeo número 2',self.send('Reproduza o último vídeo'))
        self.assertEqual(Path(self.skills.opened[-1]).name,'02.mkv')

    def test_page_is_distinct_from_media_cursor_and_global_indexes(self):
        self.send('Entre na pasta Music do disco C')
        self.assertIn('Página 1 de 3',self.send('Mostre as músicas'))
        self.assertIn('11: musica011.mp3',self.send('Próxima página'))
        self.assertIn('música número 22',self.send('Reproduza a música 22'))
        self.assertEqual(Path(self.skills.opened[-1]).name,'musica022.mp3')
        self.assertIn('23: musica023.mp3',self.send('Mostre página 3'))
        self.assertIn('música número 23',self.send('Reproduza a próxima música'))

    def test_switch_between_disks_narrates_and_preserves_cursor(self):
        self.send('Entre na pasta Music do disco C')
        self.send('Reproduza a música 4')
        self.assertIn('deixando o contexto Music',self.send('Vá para a pasta Filmes do disco D'))
        self.assertIn('disco D:',self.send('Volte para a pasta Music do disco C'))
        self.assertIn('música número 5',self.send('Reproduza a próxima música'))
        self.assertEqual(Path(self.skills.opened[-1]).name,'musica005.mp3')

    def test_return_parent_and_history_forward(self):
        self.send('Entre na pasta Music do disco C')
        self.assertIn('Rock',self.send('Entre na pasta Rock'))
        self.assertIn('contexto Music',self.send('Volte uma pasta'))
        self.assertIn('retornando a Rock',self.send('Volte ao contexto anterior'))
        self.assertIn('retornando a Music',self.send('Avance uma pasta'))

    def test_ambiguity_competition_counts_and_selection(self):
        other=self.documents/'Videos'
        other.mkdir()
        (other/'m01.wav').write_text('a')
        msg=self.send('Procure a pasta Videos no disco C')
        self.assertIn('2 pastas candidatas',msg)
        self.assertIn('1 músicas',msg)
        self.assertIn('2 vídeos',msg)
        self.assertIsNone(self.ws.current())
        self.assertIn('Entrei no contexto Videos',self.send('A segunda'))
        self.assertIsNotNone(self.ws.current())
        self.assertIsNone(self.ws.state['pending'])

    def test_pending_choice_survives_restart_and_unrelated_turn(self):
        other=self.documents/'Videos';other.mkdir()
        self.send('Procure a pasta Videos do disco C')
        self.assertIsNone(self.send('Conte sobre o Segundo Livro de Enoque'))
        resumed=NavigationWorkspace(self.db,self.cfg)
        self.assertEqual(len(resumed.state['pending']['ids']),2)
        answer=resumed.handle('a primeira',self.skills,self.nav)
        self.assertIn('Entrei no contexto Videos',answer)

    def test_duplicate_roots_do_not_count_as_ambiguous_directories(self):
        self.cfg['paths']['allowed_roots']=[str(self.c),str(self.c),str(self.d)]
        self.ws=NavigationWorkspace(self.db,self.cfg)
        self.assertIn('Entrei no contexto',self.send('Vá para a pasta Videos do disco C'))

    def test_failed_open_retains_old_context(self):
        self.send('Vá para a pasta Music do disco C')
        self.skills.fail_open=True
        out=self.send('Abra a pasta Videos do disco C')
        self.assertIn('mantive o contexto anterior',out)
        self.assertEqual(self.ws.current()['path'],str(self.music))

    def test_cursor_not_advanced_on_tool_failure(self):
        self.send('Entre na pasta Videos do disco C')
        self.send('Reproduza o primeiro vídeo')
        self.skills.fail_open=True
        self.assertIn('Não foi possível confirmar',self.send('Reproduza o próximo vídeo'))
        self.assertEqual(self.ws.current()['cursor']['video'],'01.mp4')

    def test_unauthorized_ancestors_not_accessed(self):
        self.send('Entre na pasta Videos do disco C')
        self.send('Volte uma pasta')
        self.assertIn('Não tenho autorização',self.send('Suba uma pasta'))

    def test_different_directories_with_same_names_do_not_get_merged(self):
        other=self.documents/'Videos';other.mkdir()
        (other/'special.mp4').write_text('1')
        self.send('Procure a pasta Videos do disco C')
        contexts=[c for c in self.ws.state['contexts'].values() if c['folder']=='Videos']
        self.assertEqual(len(contexts),2)
        self.assertNotEqual(contexts[0]['identity'],contexts[1]['identity'])

    def test_full_restart_restores_page_and_media_cursor(self):
        self.send('Entre na pasta Music do disco C')
        self.send('Mostre as músicas')
        self.send('Próxima página')
        self.send('Reproduza a música 14')
        restored=NavigationWorkspace(self.db,self.cfg)
        self.assertEqual(restored.current()['cursor']['audio'],'musica014.mp3')
        self.assertEqual(restored.current()['page']['audio'],2)

    def test_catalog_partial_does_not_claim_exact_last(self):
        self.ws.max_scan=1
        out=self.send('Entre na pasta Videos do disco C')
        self.assertIn('parcial',out)
        self.assertIn('inventário é parcial',self.send('Reproduza o último vídeo'))

    def test_preference_dialogue_and_random_only_after_consent(self):
        self.send('Entre na pasta Videos do disco C')
        result=self.send('Reproduza uma música')
        self.assertIn('Prefere escolher',result)
        self.assertEqual(self.skills.opened,[])
        result=self.send('sem preferência')
        self.assertIn('música número',result)
        self.assertIn(Path(self.skills.opened[-1]).suffix,{'.mp3','.flac'})

    def test_preference_choose_ordinal_after_reply(self):
        self.send('Entre na pasta Videos do disco C')
        self.send('Reproduza uma música')
        self.assertIn('Você tem 2 músicas',self.send('sim'))
        self.assertIn('música número 2',self.send('a segunda'))
        self.assertEqual(Path(self.skills.opened[-1]).name,'04.flac')

    def test_documents_are_paginated_and_selectable(self):
        (self.documents/'docs').mkdir()
        for i in range(12):
            (self.documents/'docs'/f'a{i:02}.txt').write_text(f'documento-{i}',encoding='utf8')
        self.send('Entre na pasta docs do disco C')
        self.assertIn('Página 1 de 2',self.send('Mostre os documentos'))
        self.assertIn('11: a10.txt',self.send('Próxima página'))
        self.assertIn('documentos número 11',self.send('Abra o documento 11'))
        self.assertEqual(Path(self.skills.opened[-1]).name,'a10.txt')

    def test_code_is_never_launched_by_workspace(self):
        (self.documents/'example.py').write_text('print(123)',encoding='utf8')
        self.send('Entre na pasta Documents do disco C')
        self.send('Mostre os códigos')
        reply=self.send('Abra o primeiro código')
        self.assertIn('não serão abertos',reply)
        self.assertEqual(self.skills.opened,[])

    def test_candidate_pagination_preserves_global_number(self):
        for i in range(15):
            path=self.documents/f'example{i}'/'Videos'
            path.mkdir(parents=True)
        answer=self.send('Procure a pasta Videos no disco C')
        self.assertIn('Página 1 de 2',answer)
        self.assertIn('Página 2 de 2',self.send('Próxima página'))
        answer=self.send('pasta 12')
        self.assertIn('Entrei no contexto Videos',answer)
        self.assertIsNone(self.ws.state['pending'])

    def test_changing_drive_only_selects_verified_allowed_root(self):
        self.send('Entre na pasta Videos do disco C')
        result=self.send('Mude para o disco D')
        self.assertIn('disco D:',result)
        self.assertEqual(self.ws.current()['path'],str(self.d))

    def test_explicit_catalog_refresh_does_not_reset_cursor(self):
        self.send('Entre na pasta Videos do disco C')
        self.send('Reproduza o primeiro vídeo')
        (self.videos/'new.mkv').write_text('x',encoding='utf8')
        self.assertIn('Atualizei o catálogo',self.send('Atualize o catálogo'))
        self.assertIn('vídeo número 2',self.send('Reproduza o próximo vídeo'))

    def test_external_tool_context_switch_is_reconciled(self):
        self.send('Entre na pasta Music do disco C')
        self.send('Reproduza a primeira música')
        self.nav.observe('open_directory',{'opened_directory':str(self.videos)},
                         {'path':str(self.videos)})
        reply=self.send('Reproduza o primeiro vídeo')
        self.assertIn('deixando o contexto Music',reply)
        self.assertIn('vídeo número 1',reply)
        self.assertEqual(self.ws.current()['path'],str(self.videos))
        self.assertEqual(Path(self.skills.opened[-1]).name,'01.mp4')

    def test_global_first_not_assumed_when_scan_incomplete(self):
        self.ws.max_scan=1
        self.send('Entre na pasta Videos do disco C')
        self.assertIn('inventário é parcial',self.send('Reproduza o primeiro vídeo'))
        self.assertEqual(self.skills.opened,[])

    def test_unverified_external_folder_cannot_become_active(self):
        self.send('Entre na pasta Music do disco C')
        self.nav._set('active_directory',str(self.base/'blocked'))
        out=self.send('Reproduza a próxima música')
        self.assertIn('não tenho acesso',out)
        self.assertEqual(self.ws.current()['path'],str(self.music))
        self.assertEqual(self.skills.opened,[])

    def test_read_python_from_catalog_without_executing(self):
        py=self.documents/'example.py'
        py.write_text('def answer():\n    return 42',encoding='utf-8')
        def mock_execute(name,args):
            if name=='read_document':
                return {'path':args['path'],'content':py.read_text(encoding='utf-8')}
            return OpenSkills.execute(self.skills,name,args)
        self.skills.execute=mock_execute
        self.send('Entre na pasta Documents do disco C')
        result=self.send('Leia o primeiro código')
        self.assertIn('return 42',result)
        self.assertEqual(self.skills.opened,[])

    def test_failed_restore_keeps_history_entry(self):
        self.send('Entre na pasta Music do disco C')
        self.send('Entre na pasta Videos do disco C')
        prior=list(self.ws.state['history'])
        with patch.object(self.ws,'_context',side_effect=FileNotFoundError):
            self.assertIn('mantive o contexto atual',self.send('Volte ao contexto anterior'))
        self.assertEqual(self.ws.state['history'],prior)

    def test_open_current_folder_without_unrequested_media(self):
        self.send('Entre na pasta Videos do disco C')
        answer=self.send('Abra a pasta')
        self.assertIn('contexto Videos',answer)
        self.assertEqual(self.skills.directories,[str(self.videos)])
        self.assertEqual(self.skills.opened,[])


if __name__ == '__main__':
    unittest.main()
