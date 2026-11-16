import tempfile
from pathlib import Path
from unittest.mock import patch
from tools import search_directories, search_files_in_directory, get_last_search_paths, run_tool
from intent_router import ROUTING_INSTRUCTION

def run():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        folder=root/'Music Lab'
        folder.mkdir()
        (folder/'A primeira.mp3').write_bytes(b'mp3')
        (folder/'B segunda.mp3').write_bytes(b'mp3')
        (root/'Outra.mp3').write_bytes(b'mp3')
        config={'paths':{'allowed_roots':[tmp], 'max_search_results':12},'file_search':{'timeout_seconds':5},'security':{'confirm_writes':True}}
        dirs=search_directories('music lab',config)
        assert len(dirs['results'])==1, dirs
        assert dirs['results'][0]['type']=='directory'
        scoped=search_files_in_directory(str(folder),config,extension='mp3')
        assert [r['name'] for r in scoped['results']]==['A primeira.mp3','B segunda.mp3'],scoped
        assert len(get_last_search_paths())==2
        assert search_files_in_directory(tmp,config,extension='wav')['results']==[]
        try:
            search_files_in_directory(str(root.parent),config)
        except PermissionError:
            pass
        else:
            raise AssertionError('Escape de diretório autorizado')
        assert 'apenas converse' in ROUTING_INSTRUCTION
        assert run_tool('search_files_in_directory',{'directory':str(folder),'extension':'mp3'},config)['results'][0]['index']==1
    print('PASSOU: 14.1.1 — pastas, escopo, ordem, permissões, schemas')

if __name__=='__main__': run()
