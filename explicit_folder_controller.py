"""Resolve novas pastas antes de reutilizar o cursor de mídia.

Não executa shell, não supõe caminhos e mantém a sequência anterior intacta
até uma abertura bem-sucedida na nova origem.
"""
from dataclasses import dataclass
import ntpath
import re
import unicodedata

from task_controller import TaskController


def fold(value):
    text = unicodedata.normalize('NFKD', str(value or '').casefold())
    return ''.join(ch for ch in text if not unicodedata.combining(ch))


_ORDINALS = {
    'primeiro': 1, 'primeira': 1, 'segundo': 2, 'segunda': 2,
    'terceiro': 3, 'terceira': 3, 'quarto': 4, 'quarta': 4,
    'quinto': 5, 'quinta': 5, 'sexto': 6, 'sexta': 6,
    'setimo': 7, 'setima': 7, 'oitavo': 8, 'oitava': 8,
    'nono': 9, 'nona': 9, 'decimo': 10, 'decima': 10,
}
_OPEN = re.compile(r'\b(?:abra|abrir|abre|reproduza|reproduzir|reproduz|toque|tocar|carregue|carregar|carrega)\b')
_FIND = re.compile(r'\b(?:encontre|encontrar|procure|procurar|busque|buscar|localize|localizar|pesquise|pesquisar)\b')
_DONT = re.compile(r'\b(?:nao|nunca|jamais|sem)\b')
_EXPLICIT_DRIVE = re.compile(r'\b(?:disco|unidade)\s+(?:(?:local|colocar)(?:\s+o)?\s+)?(?:de\s+)?([a-z])\s*:?\b')
_EXT = re.compile(r'\b(mp3|mp4|mkv|wav|flac|ogg|m4a|aac|avi|mov|webm|pdf|jpg|jpeg|png)\b')
_POSITION = re.compile(r'\b(?:' + '|'.join(_ORDINALS) + r'|ultimo|ultima|proximo|proxima|seguinte|anterior|precedente)\b')
_FILE_TYPE = re.compile(r'\b(?:arquivo|musica|audio|video|faixa|midia|mp3|mp4)\b')
_SEPARATORS = re.compile(
    r'\s+(?:no|na|do|da)\s+(?:disco|unidade)\b'
    r'|\s+dentro\s+(?:do|da|no|na)\s+(?:disco|unidade)\b'
    r'|\s+e\s+(?:abra|abrir|reproduza|reproduzo|reproduzir|produza|toque|carregue|localize|procure|encontre)\b'
    r'|\s+(?:para\s+)?(?:abrir|reproduzir|carregar)\b'
    r'|\s+(?:reproduza|reproduzir|reproduzo|produza|toque|tocar|abra|abrir|carregue)\b'
    r'|[.,;:!?]'
)
_SKIP_NAMES = {
    'outra', 'outras', 'uma', 'um', 'essa', 'esse', 'esta', 'este',
    'dessa', 'desta', 'mesma', 'anterior', 'atual', 'que', 'onde',
    'seguinte', 'primeiro', 'primeira', 'arquivo', 'arquivos',
}


@dataclass(frozen=True)
class FolderRequest:
    explicit_new_origin: bool
    folder_name: str | None
    drive: str | None
    extension: str | None
    position: int | str | None
    wants_open: bool


def parse_folder_request(text):
    normalized = fold(text)
    drive_match = _EXPLICIT_DRIVE.search(normalized)
    drive = drive_match.group(1).upper() if drive_match else None
    found_folder = None
    # Use todos os tokens "pasta"; uma menção como "outra pasta" não
    # deve impedir a captura posterior de "pasta chamada Música".
    for match in re.finditer(r'\bpasta\b', normalized):
        rest = normalized[match.end():].lstrip(' \t:,"\u201c\u201d')
        rest = re.sub(r'^(?:chamad[ao]|denominad[ao]|com\s+o\s+nome\s+de|de\s+nome)\s+', '', rest)
        candidate = _SEPARATORS.split(rest, maxsplit=1)[0].strip(' \t"\'\u201c\u201d')
        # 'pasta de vídeos' / 'pasta de vídeo' denote the known media folder.
        # Do not strip 'de' from arbitrary proper directory names.
        canonical = {'de video': 'videos', 'de videos': 'videos',
                     'de musica': 'musica', 'de musicas': 'musica',
                     'de audio': 'audio', 'de audios': 'audio'}
        candidate = canonical.get(candidate, candidate)
        if not candidate:
            continue
        words = candidate.split()
        if words and words[0] not in _SKIP_NAMES and len(candidate) <= 80:
            found_folder = candidate
            break
    searching = bool(_FIND.search(normalized))
    # Somente "dessa pasta" ou "na mesma pasta" não é uma origem nova.
    new_origin = bool(found_folder or (searching and re.search(r'\bpasta\b', normalized))
                      or re.search(r'\boutra\s+pasta\b', normalized))
    if (not found_folder and
            re.search(r'\b(?:dessa|desta|nessa|nesta|da mesma|na mesma)\s+pasta\b', normalized)
            and not re.search(r'\boutra\s+pasta\b', normalized)):
        # "Encontre o primeiro arquivo dessa pasta" se refere ao diretório em foco.
        new_origin = False
    # Uma simples troca de unidade também é origem explícita.
    if drive and re.search(r'\bpasta\b', normalized):
        new_origin = True
    ext_match = _EXT.search(normalized)
    extension = ext_match.group(1) if ext_match else None
    position_match = _POSITION.search(normalized)
    position = None
    if position_match:
        key = position_match.group(0)
        position = _ORDINALS.get(key, key)
    else:
        number_match = re.search(r'\b(?:arquivo|faixa|musica|audio|video)\s+(\d+)\b', normalized)
        if number_match:
            position = int(number_match.group(1))
    wants_open = bool(_OPEN.search(normalized) and not _DONT.search(normalized))
    return FolderRequest(new_origin, found_folder, drive, extension, position, wants_open)


class ExplicitFolderController:
    """Executa pesquisa/abertura usando as ferramentas existentes do JARVIS."""

    def __init__(self, agent):
        self.agent = agent

    def handle(self, text):
        req = parse_folder_request(text)
        if not req.explicit_new_origin or not req.wants_open:
            return None
        if not req.folder_name:
            return 'Você indicou uma nova pasta, mas não identifiquei o nome. Qual pasta devo procurar?'
        if req.position is None:
            return None  # A pesquisa simples permanece com o LLM.
        if isinstance(req.position, str) and req.position in ('proximo', 'proxima', 'seguinte', 'anterior', 'precedente'):
            return 'Para navegar pela nova pasta, primeiro preciso abrir um arquivo dela. Indique uma posição inicial.'
        manager = self.agent.skills_manager
        guard = TaskController(text, navigation=self.agent.navigation)
        search_args = {'query': req.folder_name}
        if req.drive:
            search_args['drive'] = req.drive
        denial = guard.inspect('search_directories', search_args)
        if denial:
            return 'Não consegui pesquisar a pasta solicitada: ' + denial
        found = manager.execute('search_directories', search_args)
        if not isinstance(found, dict) or found.get('error'):
            return 'Não consegui localizar a pasta: ' + str((found or {}).get('error', 'falha na busca'))
        candidates = [r for r in found.get('results', []) if isinstance(r, dict) and r.get('path')]
        # A transcrição por voz pode trocar uma vogal de um nome (MÔSICA/MÚSICA).
        # Só realizar busca mais tolerante se não houve resultado; jamais escolher
        # uma pasta semelhante quando houver várias possibilidades.
        if not candidates and not found.get('timed_out'):
            softer = dict(search_args, minimum_score=50)
            alternative = manager.execute('search_directories', softer)
            if isinstance(alternative, dict) and not alternative.get('error'):
                found = alternative
                candidates = [r for r in found.get('results', [])
                              if isinstance(r, dict) and r.get('path')]
        if req.drive:
            candidates = [r for r in candidates if ntpath.splitdrive(str(r['path']))[0].upper() == req.drive + ':']
        exact = [r for r in candidates if fold(ntpath.basename(ntpath.normpath(str(r['path'])))) == req.folder_name]
        if exact:
            candidates = exact
        if not candidates:
            if found.get('truncated') or found.get('timed_out'):
                return 'A pesquisa de pastas foi incompleta. Não vou reutilizar a pasta anterior.'
            drive_text = ' no disco ' + req.drive if req.drive else ''
            return f'Não encontrei a pasta {req.folder_name}{drive_text}. Não abri arquivos da pasta anterior.'
        if len(candidates) > 1:
            return 'Encontrei mais de uma pasta com esse nome. Informe a unidade ou o caminho completo.'
        directory = str(candidates[0]['path'])
        params = {'directory': directory}
        if req.extension:
            params['extension'] = req.extension
        denial = guard.inspect('search_files_in_directory', params)
        if denial:
            return 'Não consegui listar o diretório: ' + denial
        listing = manager.execute('search_files_in_directory', params)
        if not isinstance(listing, dict) or listing.get('error'):
            return 'Não consegui listar a nova pasta: ' + str((listing or {}).get('error', 'falha na leitura'))
        # A ferramenta responsável por listar já aplica os limites de resultados,
        # extensão e diretórios autorizados.
        items = listing.get('results') or []
        if not items:
            return 'Não encontrei arquivos compatíveis na nova pasta. A sequência anterior foi preservada.'
        if req.position in ('ultimo', 'ultima'):
            if listing.get('truncated') or listing.get('timed_out'):
                return 'A lista foi truncada: não posso determinar o último arquivo com segurança.'
            index = len(items) - 1
        else:
            index = req.position - 1
        if index < 0 or index >= len(items):
            return 'A posição solicitada não está disponível na listagem da nova pasta.'
        target = str(items[index]['path'])
        # Evita executar scripts/executáveis acidentalmente pelo shell do Windows.
        unsafe = {'.exe', '.bat', '.cmd', '.ps1', '.vbs', '.js', '.msi', '.scr', '.com'}
        if ntpath.splitext(target)[1].lower() in unsafe:
            return 'O arquivo selecionado é executável. Não vou abri-lo automaticamente como mídia.'
        denial = guard.inspect('open_file', {'path': target}, verified_origin=directory)
        if denial:
            return 'Não consegui abrir o arquivo: ' + denial
        opened = manager.execute('open_file', {'path': target})
        if not isinstance(opened, dict) or not opened.get('opened'):
            return 'Não consegui abrir o arquivo da nova pasta: ' + str((opened or {}).get('error', 'falha na abertura'))
        # Só substituímos o contexto anterior APÓS a abertura confirmada.
        self.agent.navigation.observe('search_directories', found, {'query': req.folder_name})
        self.agent.navigation.observe('search_files_in_directory', listing, params)
        self.agent.navigation.observe('open_file', opened, {'path': target})
        print('[PASTA EXPLICITA] origem={} indice={} arquivo={}'.format(directory, index + 1, target))
        drive_text = (' no disco ' + req.drive) if req.drive else ''
        return f'Abri o arquivo {index + 1} da pasta {ntpath.basename(ntpath.normpath(directory))}{drive_text}.'
