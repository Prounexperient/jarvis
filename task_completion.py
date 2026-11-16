"""Etapa 15.1.9.6: evidências centralizadas e retomada conservadora."""
import re
import unicodedata


def _norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).casefold()) if not unicodedata.combining(c))


class TaskCompletion:
    def __init__(self, request, write_authorized=False):
        n = _norm(request)
        self.request = request
        self.analysis = bool(re.search(r'\b(analis\w*|revis\w*|audit\w*|inspecion\w*)\b', n))
        self.edit = bool(write_authorized and re.search(r'\b(aplic\w*|apliqu\w*|implement\w*|corrig\w*|corrij\w*|alter\w*|modific\w*|refator\w*)\b', n))
        self.active = self.analysis or self.edit
        self.operations = []
        self.read_paths = set()
        self.listed_paths = set()
        self.writes = []
        self.failures = []
        self.functional_tests = []
        self.test_failures = []
        self.continuations = 0
        self.max_continuations = 3

    @property
    def reads(self):
        return len(self.read_paths)

    def observe(self, name, args, result):
        if not isinstance(result, dict):
            return
        args = args if isinstance(args, dict) else {}
        verification_status = (result.get('_aaa_verification') or {}).get('status')
        error = result.get('error') or (result.get('success') is False)
        self.operations.append({'tool': name, 'ok': not bool(error) and verification_status not in ('partial', 'unverified')})
        if name in ('developer_run_python', 'developer_run_derived_test') and (
                result.get('executed') is True or 'exit_code' in result):
            passed = bool(result.get('passed', result.get('exit_code') == 0))
            self.functional_tests.append({'tool': name, 'passed': passed, 'exit_code': result.get('exit_code')})
            if not passed:
                self.test_failures.append({'tool': name, 'exit_code': result.get('exit_code')})
        if error:
            self.failures.append({'tool': name, 'error': str(result.get('error') or result)[:300]})
            return
        if name in ('read_text_file', 'developer_read_code', 'read_document', 'read_search_result'):
            self.read_paths.add(str(result.get('path') or args.get('path') or args.get('index') or name))
        if name == 'developer_inspect_project':
            for rel in (result.get('source_evidence') or {}):
                self.read_paths.add(str(result.get('directory', '')) + '/' + rel)
        if name in ('developer_inspect_project', 'search_files_in_directory'):
            for item in result.get('files', []) or result.get('results', []):
                rel = item if isinstance(item, str) else item.get('path') if isinstance(item, dict) else None
                if rel and str(rel).lower().endswith('.py'):
                    self.listed_paths.add(str(rel).replace('\\', '/').lower())
        if (verification_status not in ('partial', 'unverified')
                and result.get('success') is True and name in (
                'developer_replace_file', 'developer_patch_file', 'developer_replace_function',
                'developer_create_python', 'developer_create_project', 'developer_create_project_structured',
                'developer_add_project_files', 'developer_rename_file', 'developer_delete_file',
                'replace_in_text_file', 'developer_create_derived_test')):
            self.writes.append({'tool': name, 'path': result.get('path') or args.get('path'),
                                'syntax_valid': result.get('syntax_valid'),
                                'functional_tested': result.get('functional_tested')})
        if name not in ('developer_run_python', 'developer_run_derived_test') and (
                result.get('executed') is True or result.get('functional_tested') is True):
            passed = result.get('passed', result.get('exit_code') == 0)
            self.functional_tests.append({'tool': name, 'passed': passed, 'exit_code': result.get('exit_code')})
            if not passed:
                self.test_failures.append({'tool': name, 'exit_code': result.get('exit_code')})

    def uncovered(self):
        read = {p.replace('\\', '/').lower() for p in self.read_paths}
        return sorted(p for p in self.listed_paths if not any(p == r or r.endswith('/' + p) for r in read))

    def needs_continuation(self):
        if self.continuations >= self.max_continuations:
            return False
        return bool(self.edit and (not self.writes or not self.functional_tests or self.test_failures)) or bool(self.analysis and self.uncovered())

    def instruction(self):
        self.continuations += 1
        uncovered = self.uncovered()
        return ('VERIFICAÇÃO DE CONCLUSÃO: pedido original: ' + self.request + '. '
                'Arquivos Python listados mas ainda não lidos (até 12): ' + repr(uncovered[:12]) + '. '
                'Modificações confirmadas: ' + str(len(self.writes)) + '; testes executados: ' + str(len(self.functional_tests)) + '. '
                'Leia arquivos relevantes pendentes antes de afirmar análise integral. '
                'Se houver alterações autorizadas, verifique-as com ferramentas disponíveis; '
                'execução de código exige confirmação humana e nunca é sandbox. '
                'Não invente verificações, respeite o escopo e não repita chamadas sem progresso. '
                'Investigue erros reais antes de encerrar. Informe pendências e limites na resposta final.')

    def summary(self):
        return {'writes': len(self.writes), 'reads': self.reads, 'listed_python': len(self.listed_paths),
                'uncovered_python': len(self.uncovered()), 'functional_tests': len(self.functional_tests),
                'failures': len(self.failures), 'test_failures': len(self.test_failures), 'continuations': self.continuations, 'verified': bool(self.writes and self.functional_tests and all(t['passed'] for t in self.functional_tests) and not self.failures)}
