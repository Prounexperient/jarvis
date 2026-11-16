
"""Preparação incremental de texto para TTS (Python 3.11+).

Preserva limites de linhas, títulos e listas Markdown sem modificar o texto
original exibido pelo agente. Não depende do Kokoro nem de serviços externos.
"""
import re


class SpeechTextProcessor:
    """Prepara streaming para fala: por sentenças ou resposta integral.

    sentence: emite frases completas, com corte de segurança apenas quando
              uma frase ultrapassa safety_limit caracteres.
    full: acumula a resposta inteira e emite uma única unidade no final.
    """

    def __init__(self, limit=220, normalize_ptbr=True, mode='sentence', safety_limit=650):
        if mode not in ('sentence', 'full'):
            raise ValueError('tts_stream_mode deve ser sentence ou full')
        self.mode = mode
        self.safety_limit = max(120, int(safety_limit))
        self.buffer = ''
        self.normalize_ptbr = normalize_ptbr


    def process(self, text):
        """Compatibilidade com agent.py 14.1.3.

        Prepara uma resposta completa para TTS sem
        utilizar uma segunda inferência do LLM.
        """
        if not text:
            return ""

        processor = SpeechTextProcessor(
            mode="full",
            normalize_ptbr=self.normalize_ptbr,
            safety_limit=self.safety_limit
        )

        return " ".join(
            processor.feed(str(text), final=True)
        )


    @staticmethod
    def _clean(line):
        line = line.strip()
        if line.startswith('```') or line.startswith('[CONCLUSAO_'):
            return ''
        line = _speech_math(line)
        line = _speech_paths(line)
        # Tabelas Markdown: nunca pronunciar pipes, separadores ou cabeçalhos.
        if line.startswith('|') and line.endswith('|'):
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            if not any(cells) or all(re.fullmatch(r':?-{2,}:?', cell or '-') for cell in cells):
                return ''
            if len(cells) == 2 and cells[0].casefold() in ('nome', 'name', 'ferramenta', 'tool') and cells[1].casefold() in ('função', 'funcao', 'descrição', 'descricao', 'description'):
                return ''
            line = ': '.join(cell for cell in cells if cell)
        # Não enviar linhas de separação Markdown para o TTS.
        if re.fullmatch(r'[-=_*|: ]{3,}', line):
            return ''
        line = re.sub(r'^#{1,6}\s+', '', line)
        line = re.sub(r'(?i)^c[oó]digo de exemplo dispon[ií]vel na resposta escrita\.?$', '', line)
        line = re.sub(r'^(?:[-*•+]\s+|\d+[.)]\s+)', '', line)
        line = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', line)
        line = re.sub(r'(?<!\w)(?:\*\*|__)(.+?)(?:\*\*|__)(?!\w)', r'\1', line)
        line = re.sub(r'(?<!\w)[*_](.+?)[*_](?!\w)', r'\1', line)
        line = line.replace('`', '')
        return re.sub(r'\s+', ' ', line).strip()

    def _emit(self, raw, line_end=False):
        text = self._clean(raw)
        if not text:
            return []
        if line_end and text[-1] not in '.!?;:':
            text += '.'
        if self.normalize_ptbr:
            text = _normalize_speech_ptbr(text)
        return [text]

    @staticmethod
    def _sentence_boundary(buffer):
        # Apenas pontuação de fim de sentença. Evita decimais e marcadores
        # enumerados simples. Uma pontuação só é conclusiva após espaço/newline.
        for match in re.finditer(r'[.!?]+["”\']?(?=\s)', buffer):
            before = buffer[:match.end()].strip()
            if re.fullmatch(r'\d{1,3}\.', before):
                continue
            # Evita algumas abreviações frequentes, sem alegar análise sintática.
            if re.search(r'(?i)\b(?:sr|sra|dr|dra|prof|etc|ex)\.$', before):
                continue
            return match.end()
        return -1

    def feed(self, text, final=False):
        self.buffer += (text or '').replace('\r\n', '\n').replace('\r', '\n')
        if self.mode == 'full':
            if not final:
                return []
            # Preserva pontuação existente, mas remove marcação por linha.
            parts = [self._clean(line) for line in self.buffer.split('\n')]
            self.buffer = ''
            joined = ' '.join(part for part in parts if part)
            if not joined:
                return []
            return [_normalize_speech_ptbr(joined) if self.normalize_ptbr else joined]

        ready = []
        while self.buffer:
            newline = self.buffer.find('\n')
            boundary = self._sentence_boundary(self.buffer)
            if newline >= 0 and (self.buffer.lstrip().startswith('|') or boundary < 0 or newline < boundary):
                part, self.buffer = self.buffer[:newline], self.buffer[newline + 1:]
                ready.extend(self._emit(part, line_end=True))
                continue
            if boundary >= 0:
                part, self.buffer = self.buffer[:boundary], self.buffer[boundary:].lstrip(' \t')
                ready.extend(self._emit(part))
                continue
            # Limite excepcional, não limite rotineiro de 220/260 caracteres.
            if len(self.buffer) > self.safety_limit:
                region = self.buffer[:self.safety_limit + 1]
                pauses = list(re.finditer(r'[,;:]\s+', region))
                candidates = [m.end() for m in pauses if m.end() >= self.safety_limit // 2]
                cut = candidates[-1] if candidates else region.rfind(' ')
                if cut <= 0:
                    cut = self.buffer.find(' ', self.safety_limit)
                if cut > 0:
                    part, self.buffer = self.buffer[:cut], self.buffer[cut:].lstrip(' \t')
                    # Não cria pontuação inexistente no texto original.
                    ready.extend(self._emit(part))
                    continue
            break
        if final:
            ready.extend(self._emit(self.buffer, line_end=True))
            self.buffer = ''
        return [item for item in ready if item]


_UNITS = dict(enumerate((
    'zero', 'um', 'dois', 'três', 'quatro', 'cinco',
    'seis', 'sete', 'oito', 'nove', 'dez', 'onze',
    'doze', 'treze', 'quatorze', 'quinze'
)))

_UNITS.update({
    16: 'dezesseis',
    17: 'dezessete',
    18: 'dezoito',
    19: 'dezenove'
})

_TENS = {
    20: 'vinte',
    30: 'trinta',
    40: 'quarenta',
    50: 'cinquenta',
    60: 'sessenta',
    70: 'setenta',
    80: 'oitenta',
    90: 'noventa'
}

_HUNDREDS = {
    100: 'cento',
    200: 'duzentos',
    300: 'trezentos',
    400: 'quatrocentos',
    500: 'quinhentos',
    600: 'seiscentos',
    700: 'setecentos',
    800: 'oitocentos',
    900: 'novecentos'
}


def _number_words(n):
    if n < 20:
        return _UNITS[n]

    if n < 100:
        return (
            _TENS[n // 10 * 10]
            + (
                ' e ' + _number_words(n % 10)
                if n % 10 else ''
            )
        )

    if n < 1000:
        if n == 100:
            return 'cem'

        return (
            _HUNDREDS[n // 100 * 100]
            + (
                ' e ' + _number_words(n % 100)
                if n % 100 else ''
            )
        )

    if n < 1000000:
        q, r = divmod(n, 1000)

        prefix = (
            'mil'
            if q == 1
            else _number_words(q) + ' mil'
        )

        join = (
            ' e '
            if r < 100 or r % 100 == 0
            else ' '
        )

        return prefix + (
            join + _number_words(r)
            if r else ''
        )

    return str(n)


def _normalize_speech_ptbr(text):
    # Evita alterar identificadores numéricos dentro de palavras,
    # versões e datas.
    text = re.sub(
        r'(?<!\w)ODS(?!\w)',
        'ó dê ésse',
        text,
        flags=re.I
    )

    # ONU é uma sigla pronunciada como palavra em português.
    # Portanto, permanece inalterada.

    def replace_number(m):
        value = m.group(0)
        n = int(value)

        return (
            _number_words(n)
            if n < 1000000
            else value
        )

    text = re.sub(
        r'(?<![\w/.,:-])\d{1,6}(?![\w/]|[.,:-]\d)',
        replace_number,
        text
    )

    return text


# Etapa 14.1.4: conversão exclusiva para fala. Não altera o log.
_WINDOWS_PATH = re.compile(r'(?<![\w])(?:`?)([A-Za-z]):\\((?:[^\\\s`"<>|]+\\)*[^\\\s`"<>|.,;!?)]*(?:\.[A-Za-z0-9]+)?)(?:`?)')

def _speech_paths(text):
    def replacement(match):
        drive, tail = match.group(1).upper(), match.group(2)
        last = tail.split('\\')[-1]
        if not last:
            return 'disco ' + drive
        suffix = last.rsplit('.', 1)[-1].lower() if '.' in last else ''
        is_file = suffix in {'mp3','wav','flac','ogg','m4a','mp4','mkv','avi','pdf','docx','txt','py','json','yaml','jpg','jpeg','png','gif','zip','exe','csv'}
        if is_file:
            last = last.rsplit('.', 1)[0]
        return 'disco ' + drive + ', ' + ('arquivo ' if is_file else 'pasta ') + last
    return _WINDOWS_PATH.sub(replacement, text)


def _speech_math(text):
    """Lê somente estruturas LaTeX reconhecidas; não calcula nem inventa."""
    def number(n):
        n = n.replace('{,}', ',')
        if re.fullmatch(r'\d+', n):
            v = int(n)
            return _number_words(v) if v < 1000000 else n
        if re.fullmatch(r'\d+,\d+', n):
            a, b = n.split(',')
            return number(a) + ' vírgula ' + ' '.join(number(c) for c in b)
        return n
    # Evita processar LaTeX genérico com regex incompleta; só formas explícitas.
    operand = r'(?:\d+(?:\{,\}|,)\d+|\d+)'
    pat = re.compile(r'\\\(\s*(' + operand + r')\s*\^\s*\{\s*\\sqrt\{\s*(' + operand + r')\s*\}\s*\}\s*\\\)')
    text = pat.sub(lambda m: number(m.group(1)) + ' elevado à raiz quadrada de ' + number(m.group(2)), text)
    pat_root = re.compile(r'\\\(\s*\\sqrt\{\s*(' + operand + r')\s*\}\s*\\\)')
    text = pat_root.sub(lambda m: 'raiz quadrada de ' + number(m.group(1)), text)
    return text
