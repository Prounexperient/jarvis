"""AAA 04 — one semantic slot contract for local-media tasks.

This parser does not decide a filesystem path or grant tool permission. It
combines the request's action/position with *verified* navigation context.
The same slot contract is used by task continuity and media navigation.
"""
import re
from explicit_folder_controller import fold, parse_folder_request

VIDEO_EXTENSIONS = frozenset({'mp4','mkv','avi','mov','webm','wmv','mpeg','mpg','m4v'})
AUDIO_EXTENSIONS = frozenset({'mp3','wav','flac','ogg','m4a','aac','wma'})

_PLAY = frozenset({'reproduza','reproduzir','reproduz','reproduzo','reproduze',
                   'toque','tocar','tocando','abra','abrir','abre','carregue','carregar'})
# ASR often drops "re" from "reproduza". This spelling is accepted *only*
# when there is a confirmed media cursor and an explicit ordinal/direction.
_ASR_PLAY = frozenset({'produza','produzir','produz','produzo'})
_QUESTION = frozenset({'qual','quais','quantos','quantas','onde','porque','por','como','quando'})
_NEGATION = frozenset({'nao','nunca','jamais','sem'})
_CONDITIONAL = frozenset({'se','caso','quando'})


def _words(text):
    return re.findall(r'[a-z0-9]+', fold(text))


def _media_target(text, words, folder_name=None):
    """Media kind of the requested OBJECT, never a folder label.

    'pasta vídeos ... primeiro áudio' => audio, not video.
    An explicit extension is even more precise than generic nouns.
    """
    request = parse_folder_request(text)
    if request.extension in AUDIO_EXTENSIONS:
        return 'audio'
    if request.extension in VIDEO_EXTENSIONS:
        return 'video'
    normalized = fold(text)
    # Use the final action clause to distinguish the folder's name from the
    # thing the user wants to open. No filesystem guessing occurs here.
    matches = list(re.finditer(r'\b(?:reproduza|reproduzir|reproduz|reproduzo|reproduze|'
                               r'toque|tocar|abra|abrir|carregue|carregar|produza)\b', normalized))
    target = normalized[matches[-1].end():] if matches else normalized
    # Do not mistake the folder label for the requested media type.
    # 'segundo arquivo da pasta Vídeos' has no explicit media kind.
    target = re.split(r'\b(?:da|na|dessa|desta|dentro\s+da|do)\s+pasta\b',
                      target, maxsplit=1)[0]
    tokens = set(_words(target))
    audio = tokens & {'musica','musicas','audio','audios','faixa','faixas','mp3','wav','flac'}
    video = tokens & {'video','videos','filme','filmes','mp4','mkv','avi'}
    if audio and not video:
        return 'audio'
    if video and not audio:
        return 'video'
    # For 'abra o primeiro vídeo da pasta Vídeos', post-verb text contains
    # target explicitly. For 'abra primeiro arquivo da pasta Vídeos', only
    # the folder is qualified; preserve mixed media behavior.
    if not audio and not video:
        before_folder = re.split(r'\b(?:da|na|dessa|desta|de|do)\s+pasta\b', target, maxsplit=1)[0]
        t = set(_words(before_folder))
        if t & {'musica','musicas','audio','audios','faixa','faixas'}:
            return 'audio'
        if t & {'video','videos','filme','filmes'}:
            return 'video'
    # A folder's name is not a media type request by itself.
    return None


class MediaIntentResolver:
    def interpret(self, text, *, has_media_context=False):
        request = parse_folder_request(text)
        words = set(_words(text))
        has_position = request.position is not None
        denied = bool(words & (_NEGATION | _CONDITIONAL))
        questions = bool(words & _QUESTION and words & {'qual','quais','quando','como','onde'})
        play = bool(words & _PLAY) and not denied and not questions
        if not play and has_media_context and has_position and not denied and not questions:
            # Isolated "o próximo", or noisy "produza o próximo arquivo".
            stripped = words - {'o','a','os','as','agora','e','por','favor','arquivo',
                                'arquivos','video','videos','audio','audios','musica',
                                'musicas','faixa','faixas','proximo','proxima',
                                'seguinte','anterior','precedente','ultimo','ultima',
                                'primeiro','primeira','segundo','segunda','terceiro',
                                'terceira','quarto','quarta','quinto','quinta',
                                'sexto','sexta','setimo','setima','oitavo','oitava',
                                'nono','nona','decimo','decima'}
            play = not stripped or bool(stripped & _ASR_PLAY and (stripped - _ASR_PLAY) == set())
        # A request to create/generate an asset is not media navigation,
        # even when a media directory is active.
        if words & {'crie','criar','criacao','gere','gerar','geracao','edite','editar',
                    'exclua','excluir','apague','apagar','escreva','escrever',
                    'trecho','texto','paragrafo','capitulo','livro','citacao',
                    'poema','versiculo','versiculos','codigo','script',
                    'funcao','projeto','resposta','frase'}:
            play = False
        return {
            'folder_name': request.folder_name,
            'drive': request.drive,
            'position': request.position,
            'extension': request.extension,
            'wants_open': play,
            # A compound request may explicitly ask to open the Explorer
            # folder *and* play a file. This is separate from playing media.
            'open_directory': bool(re.search(r'\b(?:abra|abrir|abre)\s+(?:a\s+)?pasta\b',
                                              fold(text)) and not denied),
            'explicit_new_origin': request.explicit_new_origin,
            'media_kind': _media_target(text, words, request.folder_name),
        }
