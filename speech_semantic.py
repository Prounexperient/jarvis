"""Etapa 13.4.1: reformulação oral isolada, concisa e com checagens conservadoras."""
import re
import unicodedata


def _fold(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


class SpeechSemanticRealizer:
    def __init__(self, client, config):
        self.client, self.config = client, config

    @staticmethod
    def _safe(technical, candidate, max_chars=650):
        candidate = (candidate or '').strip()
        if not candidate or len(candidate) > max_chars or len(candidate) > max(220, len(technical) * 1.6):
            return False, 'tamanho'
        if re.search(r'<\|[^>]+\|>|</?[a-z][^>]*>|```|\|\s*---', candidate, re.I):
            return False, 'marcacao'
        if re.search(r'(?m)^\s*(?:\||#{1,6}\s|\d+[.)]\s)', candidate):
            return False, 'formato'
        for item in re.findall(r'(?<!\w)\d+(?:[.,]\d+)?(?!\w)', candidate):
            if item not in technical:
                return False, 'numero_novo'
        for item in re.findall(r'\b[a-z][a-z0-9]*_[a-z0-9_]+\b', candidate, re.I):
            if item.casefold() not in technical.casefold():
                return False, 'identificador_novo'
        src, dst = _fold(technical), _fold(candidate)
        restricted = bool(re.search(r'\b(nao posso|nao consegue|nao e possivel|somente|apenas|limitad[oa]s?|bloqueia|autorizad[oa]s?|permissoes)\b', src))
        if restricted and not re.search(r'\b(nao|somente|apenas|limitad[oa]s?|autorizad[oa]s?|permissoes|preciso|depende|restric)', dst):
            return False, 'restricoes_omitidas'
        # Proteções focadas em fatos críticos, sem exigir repetição literal do texto.
        if re.search(r'nao (?:posso|consegue|tenho permissao para)\s+(?:executar|rodar)\s+(?:scripts?|codigo)', src):
            if not re.search(r'nao\s+(?:posso|consigo|e possivel|tenho permissao para)\s+(?:executar|rodar)\s+(?:scripts?|codigo)', dst):
                return False, 'execucao_omitida'
        if 'confirmacao' in src and ('editar' in src or 'modificar' in src or 'alterar' in src):
            if 'confirmacao' not in dst and 'confirme' not in dst and 'autorize' not in dst:
                return False, 'confirmacao_omitida'
        if 'backup' in src or 'copia de seguranca' in src:
            if 'backup' not in dst and 'copia de seguranca' not in dst:
                return False, 'backup_omitido'
        if ('pastas autorizadas' in src or 'raizes autorizadas' in src or 'permissoes' in src) and ('arquivo' in src):
            if not any(word in dst for word in ('autorizad', 'permitid', 'permiss', 'acesso restrito')):
                return False, 'acesso_omitido'
        # Uma afirmação genérica de que não abre aplicativos contradiz a capacidade autorizada.
        if ('abrir aplicativos' in src or 'aplicativos autorizados' in src) and re.search(r'nao (?:posso|consigo) (?:abrir|executar) (?:programas|aplicativos)', dst):
            return False, 'contradicao_aplicativos'
        return True, 'ok'

    def realize(self, technical, model, question=''):
        if not technical or len(technical.strip()) < 60:
            return technical
        settings = self.config.get('conversation', {})
        max_chars = max(180, int(settings.get('speech_semantic_max_chars', 650)))
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {'role': 'system', 'content': (
                        'Sua única tarefa é converter uma resposta técnica já concluída em uma fala natural em português brasileiro. '
                        'Não responda por conta própria; não use ferramentas. Use apenas fatos do texto técnico. '
                        'Responda primeiro à pergunta, em primeira pessoa, de forma direta. '
                        'Use de 2 a 5 frases curtas e no máximo ' + str(max_chars) + ' caracteres. '
                        'Não recite listas de funções, nomes internos de ferramentas, formatos ou etapas de uso se não forem pedidos. '
                        'Preserve explicitamente restrições pertinentes: execução de scripts, pastas permitidas, confirmação de edição e backup, quando mencionados. '
                        'Diferencie executar scripts arbitrários de abrir aplicativos autorizados. '
                        'Não afirme que não pode abrir programas se pode abrir aplicativos autorizados. '
                        'Não invente capacidades, resultados, permissões ou números. '
                        'Sem Markdown, tabelas, títulos, tags, JSON ou explicações sobre a reescrita. '
                        'Devolva somente o texto que será falado.'
                    )},
                    {'role': 'user', 'content': 'PERGUNTA:\n' + question + '\n\nRESPOSTA TÉCNICA:\n' + technical},
                ],
                tool_choice='none', stream=False, temperature=0.1,
                max_tokens=int(settings.get('speech_semantic_max_tokens', 320)),
            )
            candidate = (response.choices[0].message.content or '').strip()
            valid, reason = self._safe(technical, candidate, max_chars)
            if not valid:
                print('[SPEECH_SEMANTIC] fallback: ' + reason)
                return technical
            print('[SPEECH_SEMANTIC] fala reformulada; caracteres=' + str(len(candidate)))
            return candidate
        except Exception as exc:
            print('[SPEECH_SEMANTIC] indisponível: ' + type(exc).__name__)
            return technical
