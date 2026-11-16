"""Canal oral incremental, independente do texto técnico do terminal.

Não chama outro LLM, não executa ferramentas, não altera o histórico.
A adaptação é conservadora: não inventa capacidades nem reescreve conclusões.
"""
import re
from speech_text_processor import SpeechTextProcessor

# Glossário de pronúncia/apresentação, NÃO registro de permissões.
_TOOL_SPOKEN = {
    'read_search_result': 'leitura do resultado da busca',
    'read_document': 'leitura de documentos',
    'read_text_file': 'leitura de arquivos de texto',
    'inspect_search_result': 'inspeção de resultados da busca',
    'inspect_document': 'inspeção de documentos',
    'replace_in_text_file': 'edição de trechos de arquivos',
    'search_files': 'pesquisa de arquivos',
    'open_search_result': 'abertura de resultados da busca',
    'reveal_search_result': 'localização no Explorador',
    'open_file': 'abertura de arquivos',
    'open_application': 'abertura de aplicativos',
    'create_word_document': 'criação de documentos do Word',
    'get_system_capabilities': 'consulta das capacidades do sistema',
    'calculator': 'calculadora',
}

class SpeechRealizationLayer:
    """Adapta unidades textuais completas antes de segmentá-las para o TTS.

    O canal visual permanece intocado. Não remove negações, números nem limites.
    """
    def __init__(self, mode='sentence', safety_limit=650, enabled=True):
        self.enabled = bool(enabled)
        self.processor = SpeechTextProcessor(mode=mode, safety_limit=safety_limit)
        self._pending = ''
        self._code_fence = False

    @staticmethod
    def _realize_line(line):
        if not line.strip():
            return line
        # Normalização de caminhos ocorre no SpeechTextProcessor.
        # Evita descartar o nome do arquivo/pasta antes da síntese.
        # Nomes internos só são adaptados quando são identificadores isolados.
        for name, spoken in _TOOL_SPOKEN.items():
            line = re.sub(r'(?<![\w])' + re.escape(name) + r'(?![\w])', spoken, line)
        # Extensões e siglas frequentes, sem mexer no texto técnico original.
        line = re.sub(r'(?<!\w)\.py\b', ' Python', line, flags=re.I)
        line = re.sub(r'(?<!\w)\.docx\b', ' do Word', line, flags=re.I)
        line = re.sub(r'(?<!\w)\.pdf\b', ' PDF', line, flags=re.I)
        line = re.sub(r'(?<!\w)\.txt\b', ' de texto', line, flags=re.I)
        return line

    def _line(self, line):
        if line.lstrip().startswith('```'):
            self._code_fence = not self._code_fence
            return ''
        if self._code_fence:
            return ''  # Código permanece disponível integralmente no terminal.
        return self._realize_line(line) if self.enabled else line

    def feed(self, text, final=False):
        self._pending += (text or '').replace('\r\n', '\n').replace('\r', '\n')
        ready = []
        while '\n' in self._pending:
            line, self._pending = self._pending.split('\n', 1)
            ready.extend(self.processor.feed(self._line(line) + '\n'))
        # No streaming, só processa texto que não pode ser parte de um
        # identificador ainda em formação. Frases completas são limites seguros.
        if not final:
            match = list(re.finditer(r'[.!?](?=\s)', self._pending))
            if match:
                cut = match[-1].end()
                part, self._pending = self._pending[:cut], self._pending[cut:]
                ready.extend(self.processor.feed(self._line(part) + ' '))
        else:
            ready.extend(self.processor.feed(self._line(self._pending), final=True))
            self._pending = ''
        return ready
