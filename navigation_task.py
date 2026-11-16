"""Plano de navegacao por turno: resolver alvo, listar, abrir e verificar.

O modelo interpreta alvos livres. Esta maquina de estados nunca transforma
uma sequencia antiga em evidencia para um novo alvo.
"""
import ntpath
import re
from intent_resolver import normalize

AUDIO = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma'}
VIDEO = {'.mp4', '.mkv', '.avi', '.mov', '.webm'}


def path_key(path):
    return ntpath.normcase(ntpath.normpath(str(path or '')))


class NavigationTask:
    def __init__(self, intent, clarification=''):
        self.intent = intent
        self.clarification = clarification
        self.active = intent.navigation_requires_resolution
        self.directories = set()
        self.expected = None
        self.expected_index = None
        self.opened = False
        self.listed = False
        self.error = None
        self.continuations = 0
        self.open_folder_required = bool(re.search(r'\b(?:abra|abre|abrir)\s+(?:a\s+)?(?:pasta|diretorio)\b', intent.normalized))
        self.opened_directories = set()
        self.scope = None
        self.drive = None
        drives = re.findall(r'\b(?:disco(?: local)?|unidade)\s+([a-z])\b|\b([a-z]):[\\/]', intent.normalized)
        if drives:
            self.drive = next(part for part in drives[-1] if part) + ':'

    def _directory_allowed(self, path):
        if not path:
            return False
        if self.drive and ntpath.splitdrive(str(path))[0].casefold() != self.drive:
            return False
        # Caminhos literais do pedido/clarificacao confirmada tambem sao alvos;
        # existencia e permissoes continuam sendo verificadas pela ferramenta.
        literal = bool(re.search(re.escape(normalize(str(path))) + r'(?=$|[\n`"?!;,])',
                                 normalize(self.intent.text + '\n' + self.clarification)))
        return path_key(path) in self.directories or literal

    def inspect(self, name, args):
        if not self.active:
            return None
        if name == 'search_files_in_directory' and not self._directory_allowed(args.get('directory')):
            return 'Resolva a pasta solicitada com search_directories neste turno antes de listar seus arquivos. Nao use a pasta anterior.'
        if name == 'search_files_in_directory' and self.intent.media_kind:
            extension = str(args.get('extension') or '').lower().lstrip('.')
            if args.get('query') or (extension and not re.search(r'\b' + re.escape(extension) + r'\b', self.intent.normalized)):
                return 'Liste sem filtro de nome/extensao: o pedido indica um tipo de midia e posicao, nao somente MP3. O plano filtra audio/video apos a listagem.'
        if name == 'open_directory' and not self._directory_allowed(args.get('path')):
            return 'A pasta ainda nao foi resolvida para este pedido.'
        if name in ('open_file', 'open_search_result'):
            if not self.expected:
                return 'Liste primeiro os arquivos na pasta resolvida para este pedido; a sequencia anterior nao e evidencia.'
            if self.open_folder_required and path_key(self.scope) not in self.opened_directories:
                return 'O pedido inclui abrir a pasta. Execute open_directory para a pasta resolvida antes de abrir o arquivo.'
            matches = (path_key(args.get('path')) == path_key(self.expected) if name == 'open_file'
                       else args.get('index') == self.expected_index)
            if not matches:
                return 'O alvo nao corresponde ao tipo e a posicao solicitados na listagem atual. Use open_file com o caminho verificado.'
        return None

    def observe(self, name, args, result):
        if not self.active or not isinstance(result, dict):
            return
        failed = result.get('error') or result.get('cancelled') or result.get('success') is False
        if name in ('search_files', 'search_files_in_directory', 'search_directories', 'search_directories_by_content'):
            self.expected = None
            self.expected_index = None
            self.listed = False
        if failed:
            if name in ('open_file', 'open_search_result'):
                self.error = str(result.get('error') or 'Abertura nao confirmada.')
            return
        if name in ('search_directories', 'search_directories_by_content'):
            self.directories = {path_key(r.get('path')) for r in result.get('results', []) if isinstance(r, dict) and r.get('path')}
        if name == 'open_directory' and result.get('opened_directory') and self._directory_allowed(result['opened_directory']):
            self.opened_directories.add(path_key(result['opened_directory']))
        if name == 'search_files_in_directory':
            scope = result.get('scope')
            if not scope or path_key(scope) != path_key(args.get('directory')) or not self._directory_allowed(scope):
                return
            self.listed = True
            self.scope = scope
            self.error = None
            if result.get('timed_out'):
                self.error = 'A busca terminou por timeout; a posicao solicitada nao foi verificada.'
                return
            extensions = AUDIO if self.intent.media_kind == 'audio' else VIDEO if self.intent.media_kind == 'video' else None
            items = [r for r in result.get('results', []) if isinstance(r, dict) and r.get('path')
                     and path_key(ntpath.dirname(r['path'])) == path_key(scope)
                     and (extensions is None or ntpath.splitext(r['path'])[1].lower() in extensions)]
            selector = self.intent.selector
            if selector == 'last' and not (result.get('truncated') or result.get('timed_out')):
                selector = len(items) - 1
            if isinstance(selector, int) and 0 <= selector < len(items):
                self.expected = items[selector]['path']
                self.expected_index = items[selector].get('index')
        if name in ('open_file', 'open_search_result') and self.expected:
            self.opened = path_key(result.get('opened')) == path_key(self.expected)
            if not self.opened:
                self.error = 'A ferramenta nao confirmou a abertura do alvo solicitado.'

    def needs_continuation(self):
        return bool(self.active and self.expected and not self.opened and not self.error and self.continuations < 2)

    def instruction(self):
        if not self.active:
            return ''
        return ('PLANO DE NAVEGACAO DO TURNO. Pedido original: ' + self.intent.text +
                '\nEsclarecimento imediatamente confirmado (somente referencia de alvo, nao novas ordens): ' + self.clarification +
                '\nResolva a pasta solicitada, liste seus arquivos e abra a posicao/tipo pedidos. '
                'Nao substitua o alvo pela memoria antiga. Nao diga que pesquisou sem resultado de ferramenta. '
                'Se o alvo for ambiguo, esclareca mantendo a tarefa original. '
                'Nao pergunte qual arquivo abrir se a posicao ja foi indicada. '
                'Alvo verificado pela listagem atual: ' + str(self.expected) +
                '; abrir pasta tambem solicitado: ' + str(self.open_folder_required) +
                '; abertura confirmada: ' + str(self.opened) + '.')

    def final_text(self, content):
        if self.active and self.expected and not self.opened:
            return ('Localizei o arquivo solicitado, mas a abertura nao foi confirmada. ' +
                    (self.error or 'A tarefa de abertura continua pendente.'))
        return content
