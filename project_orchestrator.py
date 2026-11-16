"""Resolução determinística de projetos: nunca escolher pastas arbitrárias."""
from pathlib import Path
import re
from workspace_session import load, activate


def projects_root():
    return (Path.home() / 'JARVIS_DERIVED_PROJECTS').resolve()


def resolve_project(name=None, explicit_path=None, create=False):
    if explicit_path:
        target = Path(explicit_path).expanduser().resolve()
        if not target.is_dir() and not create:
            raise FileNotFoundError(str(target))
        return target
    if name is None:
        active = load().get('active_root')
        if not active:
            raise ValueError('Nenhum projeto ativo; informe um nome de projeto.')
        return Path(active).resolve()
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name):
        raise ValueError('Nome de projeto inválido.')
    return projects_root() / name


def select_project(path):
    path = Path(path).resolve()
    if not path.is_dir():
        raise FileNotFoundError(str(path))
    activate(path)
    return path


def tests_directory(project):
    return Path(project).resolve() / 'tests'
