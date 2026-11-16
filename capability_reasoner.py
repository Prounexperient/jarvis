"""Raciocínio operacional fundamentado exclusivamente no inventário real."""
from capability_registry import describe_capabilities


def capability_matrix(config, schemas):
    names = {s['function']['name'] for s in schemas}
    security = config.get('security', {})
    tasks = (
        ('localizar arquivos', {'search_files'}),
        ('ler arquivos de texto e código', {'read_text_file', 'read_document', 'read_search_result'}),
        ('inspecionar documentos e procurar trechos', {'inspect_document', 'inspect_search_result'}),
        ('abrir arquivos', {'open_file', 'open_search_result'}),
        ('editar trechos específicos de arquivos', {'replace_in_text_file'}),
        ('criar documentos do Word', {'create_word_document'}),
        ('abrir aplicativos autorizados', {'open_application'}),
        ('executar scripts Python diretamente', {'execute_python', 'run_python', 'developer_run_python'}),
        ('criar arquivos Python', {'developer_create_python'}),
        ('inspecionar projetos Python', {'developer_inspect_project'}),
    )
    available = {label: bool(names & required) for label, required in tasks}
    return {
        'available': available,
        'can_analyze_code': available['ler arquivos de texto e código'],
        'can_execute_python': available['executar scripts Python diretamente'],
        'writes_require_confirmation': bool(security.get('confirm_writes', True)),
        'inventory': describe_capabilities(config, names, schemas),
    }


def capability_context(config, schemas):
    matrix = capability_matrix(config, schemas)
    available = [name for name, yes in matrix['available'].items() if yes]
    unavailable = [name for name, yes in matrix['available'].items() if not yes]
    roots = [r['resolved'] for r in matrix['inventory']['allowed_roots'] if r['exists']]
    confirmation = ('A configuração exige confirmação para gravações; a ferramenta ainda deve aplicar suas verificações.'
                    if matrix['writes_require_confirmation'] else
                    'A configuração não exige confirmação global para gravações; cada ferramenta ainda aplica suas próprias verificações.')
    return ('CAPACIDADES OPERACIONAIS DERIVADAS DAS FERRAMENTAS REGISTRADAS, NÃO AÇÕES JÁ REALIZADAS. '
            'Disponíveis: ' + '; '.join(available) + '. '
            'Não disponíveis como operação direta: ' + '; '.join(unavailable) + '. '
            + ('Pode analisar, explicar e resumir código após ler seu conteúdo; isso é raciocínio do modelo, não execução.'
               if matrix['can_analyze_code'] else 'Não afirme que leu ou analisou arquivos locais sem ferramenta de leitura.')
            + (' É possível abrir aplicativos específicos autorizados; isso NÃO equivale a executar scripts Python nem comandos arbitrários. Não afirme proibição universal de abrir aplicativos ou iniciar processos. ' if matrix['available']['abrir aplicativos autorizados'] else ' Não existe ferramenta registrada para abrir aplicativos. ') 
            + confirmation + ' '
            + 'Caminhos e permissões devem ser verificados em cada operação. Para modificações, a exigência de confirmação depende da configuração e das verificações da ferramenta. Não diga que não pode abrir executáveis de forma universal: distinga abrir aplicativos permitidos de executar código arbitrário. '
            + 'Ao responder perguntas sobre capacidades, selecione SOMENTE as tarefas pertinentes ao pedido atual; não recite o inventário completo. Diga explicitamente o que pode e o que não pode fazer nas tarefas perguntadas, '
            + 'especialmente quando o usuário perguntar sobre executar código. '
            + 'Responda em linguagem natural, por tarefas; não enumere nomes internos nem caminhos completos, salvo pedido explícito. '
            + 'Raízes autorizadas atualmente existentes: ' + (', '.join(roots) if roots else 'nenhuma') + '.')
