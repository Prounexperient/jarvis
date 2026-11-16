"""Intenções observáveis por turno; não concede permissões.

A classificação é conservadora e distingue a menção a uma obra da intenção
explícita de acessar um arquivo no PC. O LLM continua interpretando pedidos
complexos, mas a classificação local protege a execução das ferramentas.
"""
from dataclasses import dataclass
import re
import unicodedata


def normalize(text):
    value = unicodedata.normalize('NFKD', str(text or '').casefold())
    return ''.join(c for c in value if not unicodedata.combining(c))


_CITATION_VERB = re.compile(r'\b(?:cite|cita|citar|site|siti|recite|recitar|transcreva|transcrever|declame|declamar|reproduza|reproduzir)\b')
_PASSAGE = re.compile(r'\b(?:trecho|passagem|versiculo|versiculos|frase|paragrafo|excerto|citacao|citacoes|poema|estrofe|texto)\b')
_WORK = re.compile(r'\b(?:livro|livros|obra|obras|evangelho|evangelhos|biblia|enoch|enoque|odisseia|iliada|homero|tolkien|daniel|platao|aristoteles|capitulo|canto)\b')
_LOCAL = re.compile(
    r'\b(?:no|do|em|pelo|pelo meu)\s+(?:meu\s+)?(?:pc|computador|notebook|hd|ssd|disco)\b'
    r'|\b(?:meu|neste|nesse|deste|desse)\s+(?:pc|computador|notebook|disco)\b'
    r'|\b(?:arquivo|pdf|documento)\s+(?:que\s+(?:voce\s+)?(?:encontrou|abriu|localizou)|aberto|local|salvo)\b'
    r'|\b(?:este|esse|deste|desse|neste|nesse|meu)\s+(?:arquivo|pdf|documento)\b'
    r'|\b(?:da|na|dentro\s+da)\s+pasta\s+\w+'
    r'|\b(?:caminho|diretorio|pasta)\s+[a-z]:[\\/]'
    r'|\b[a-z]:[\\/]', re.I)
_EXPLICIT_LOCAL_ACTION = re.compile(r'\b(?:procure|pesquise|busque|encontre|localize|abra|abrir|carregue|acesse|leia|ler|resuma|resumir)\b')
_FILE_NOUN = re.compile(r'\b(?:arquivo|pdf|documento|pasta|diretorio)\b')
_MEDIA_NOUN = re.compile(r'\b(?:musica|audio|faixa|video|filme|mp3|mp4|mkv|wav|flac)\b')
_OPEN = re.compile(r'\b(?:abra|abrir|abre|abri|execute|executar|toque|tocar|reproduza|reproduzir|reproduz|mostre|mostrar|explorador|navegue|navegar)\b')
_LOAD = re.compile(r'\b(?:carregue|carregar|carrega|coloque|colocar)\b')
_READ = re.compile(r'\b(?:ler|leia|leitura|carreg\w*|resum\w*|analis\w*|explic\w*|traduz\w*|inspecion\w*|conteudo|pagina|linha|texto|verifi\w*|mostr\w*)\b')
_WRITE = re.compile(r'\b(?:cri\w*|faz\w*|fac\w*|ger\w*|salv\w*|grav\w*|escrev\w*|edit\w*|alter\w*|modific\w*|corrig\w*|corrij\w*|correc\w*|consert\w*|acrescent\w*|adicion\w*|inclu\w*|implement\w*|refator\w*|ajust\w*|substitu\w*|remov\w*|exclu\w*|apag\w*|aplic\w*|atualiz\w*)\b')
_NEGATION = re.compile(r'^\s*(?:nao|nunca|jamais|cancele|cancelar|desista|pare|interrompa)\b')


@dataclass(frozen=True)
class IntentFrame:
    text: str
    normalized: str
    general_quotation: bool
    explicit_local_source: bool
    requested_open: bool
    requested_load: bool
    requested_read: bool
    requested_write: bool
    media_reference: bool
    negative_command: bool


class IntentResolver:
    def resolve(self, text):
        s = normalize(text)
        local = bool(_LOCAL.search(s))
        # "Cite o trecho do PDF Enoque" é pedido de conhecimento geral;
        # "Cite ... do PDF que abriu" refere um recurso local confirmado.
        explicit_file_command = bool(_EXPLICIT_LOCAL_ACTION.search(s) and _FILE_NOUN.search(s))
        citation = bool(_CITATION_VERB.search(s) and (
            _PASSAGE.search(s) or _WORK.search(s) or
            (not _FILE_NOUN.search(s) and not _MEDIA_NOUN.search(s))))
        # "Cite as fontes que encontrou no arquivo" não é citação de obra.
        source_file = bool(re.search(r'\b(?:fontes|caminho|nome|localizacao)\b', s)
                           and _FILE_NOUN.search(s))
        # "reproduza o ultimo audio" é pedido de execução de mídia.
        media = bool(_MEDIA_NOUN.search(s))
        quotation = citation and not local and not source_file and not (
            media and not _PASSAGE.search(s))
        # O simples verbo "cite" com 'arquivo' não torna uma citação local.
        return IntentFrame(
            text=str(text or ''), normalized=s,
            general_quotation=quotation,
            explicit_local_source=local or (explicit_file_command and not quotation),
            requested_open=bool(_OPEN.search(s)), requested_load=bool(_LOAD.search(s)),
            requested_read=bool(_READ.search(s)), requested_write=bool(_WRITE.search(s)),
            media_reference=media, negative_command=bool(_NEGATION.search(s)),
        )
