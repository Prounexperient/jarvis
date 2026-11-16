"""Contexto efêmero de trabalho de código; nunca persiste conteúdo de arquivos."""
import ast
from pathlib import Path


class DeveloperContext:
    def __init__(self):
        self.path = None
        self.function = None
        self.project = None

    def observe(self, name, args, result):
        if not isinstance(result, dict) or result.get('error') or result.get('success') is False:
            return
        if name in ('developer_create_project', 'developer_create_project_structured') and result.get('success'):
            self.project = result.get('directory')
            files = result.get('files') or []
            main = next((f for f in files if str(f).replace('\\', '/').endswith('/main.py') or f == 'main.py'), None)
            if main:
                self.path = str(Path(self.project) / main)
                self.function = None
        elif name in ('developer_read_code', 'developer_patch_file', 'developer_create_python', 'developer_inspect_project', 'read_text_file', 'read_document', 'open_file', 'developer_verify_code'):
            path = result.get('path') or args.get('path')
            if path:
                if path != self.path:
                    self.function = None
                self.path = str(path)
                self.project = str(Path(path).parent)
            if name in ('developer_read_code', 'read_text_file', 'read_document'):
                if result.get('function_name'):
                    self.function = result['function_name']
                content = result.get('content', result.get('text', ''))
                try:
                    tree = ast.parse(content)
                    names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    if self.function not in names:
                        self.function = names[0] if len(names) == 1 else None
                except (SyntaxError, TypeError):
                    self.function = None
        elif name == 'open_directory' and result.get('opened_directory'):
            self.project = result['opened_directory']
        elif name == 'developer_map_codebase' and result.get('modules') is not None:
            self.project = result.get('directory')

    def instruction(self):
        if not self.path and not self.project:
            return ''
        lines = ['\n[CONTEXTO DE DESENVOLVIMENTO - RAM, REFERÊNCIAS, NÃO CONTEÚDO]']
        if self.project:
            lines.append('Projeto/diretório em foco: ' + self.project)
        if self.path:
            lines.append('Arquivo em foco: ' + self.path)
        if self.function:
            lines.append('Função candidata em foco: ' + self.function + ' (confirme no código e no pedido antes de editar)')
        lines.append('Carregar/ler arquivo = acessar conteúdo com developer_read_code; abrir arquivo = open_file no aplicativo padrão. Nunca confunda as duas ações.')
        lines.append('Referências como "esse arquivo" podem apontar para o arquivo em foco; se ambíguas, pergunte. Sempre releia com developer_read_code antes de editar. Não presuma que conteúdo antigo ainda é válido.')
        return '\n'.join(lines)
