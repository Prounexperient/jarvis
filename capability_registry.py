"""Inventário operacional somente-leitura, derivado das ferramentas e configuração reais."""
import os
from pathlib import Path


def _drive_of(path):
    drive = os.path.splitdrive(str(path))[0]
    return drive.upper() if drive else None


def available_drives():
    """Unidades montadas visíveis ao processo no Windows (não equivale a autorização)."""
    if os.name != 'nt':
        return []
    return [f'{chr(letter)}:' for letter in range(ord('A'), ord('Z') + 1)
            if os.path.exists(f'{chr(letter)}:\\')]


def describe_capabilities(config, functions, schemas):
    """Sem alterar permissões; informa apenas recursos registrados e raízes configuradas."""
    roots = []
    for raw in config.get('paths', {}).get('allowed_roots', []):
        expanded = Path(raw).expanduser().resolve()
        roots.append({
            'configured': str(raw),
            'resolved': str(expanded),
            'exists': expanded.exists(),
            'is_directory': expanded.is_dir(),
            'drive': _drive_of(expanded),
        })
    # Keep the capability inventory consistent with actual implicit Windows
    # user-library roots admitted by tools._resolve_roots.
    if os.name == 'nt':
        configured = {str(Path(r['resolved'])) for r in roots}
        for label in ('Music', 'Videos', 'Documents', 'Downloads', 'Pictures'):
            folder = (Path.home() / label).resolve()
            if folder.is_dir() and str(folder) not in configured:
                roots.append({
                    'configured': '[biblioteca pessoal padrão]',
                    'resolved': str(folder),
                    'exists': True,
                    'is_directory': True,
                    'drive': _drive_of(folder),
                })
                configured.add(str(folder))
    descriptions = {item['function']['name']: item['function']['description'] for item in schemas}
    tools = [{'name': name, 'description': descriptions.get(name, ''), 'registered': True}
             for name in sorted(functions) if name != 'get_system_capabilities']
    return {
        'allowed_roots': roots,
        'available_drives': available_drives(),
        'tools': tools,
        'security': {
            'confirm_writes': bool(config.get('security', {}).get('confirm_writes', True)),
            'confirm_program_launch': bool(config.get('security', {}).get('confirm_program_launch', False)),
            'access_rule': 'Somente caminhos sob raízes autorizadas; permissões do sistema operacional também se aplicam.',
        },
        'limitations': [
            'Uma unidade detectada não é necessariamente autorizada.',
            'Uma raiz configurada não garante acesso a todos os arquivos: o sistema operacional pode negar acesso.',
            'O inventário descreve capacidades disponíveis, não ações já executadas.',
        ],
    }
