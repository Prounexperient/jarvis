"""Pastas pessoais sempre autorizadas, sem depender do config.yaml."""
import os
from pathlib import Path

ALIASES = {
    'Music': ('Music', 'Música', 'Músicas', 'Minhas Músicas'),
    'Videos': ('Videos', 'Vídeos', 'Meus Vídeos'),
    'Documents': ('Documents', 'Documentos', 'Meus Documentos'),
}


def _windows_user_folders():
    """Consulta o Shell para respeitar redirecionamento/OneDrive/outro disco."""
    if os.name != 'nt':
        return {}
    import ctypes
    from ctypes import wintypes
    try:
        get_folder = ctypes.WinDLL('shell32').SHGetFolderPathW
        get_folder.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE,
                               wintypes.DWORD, wintypes.LPWSTR]
        get_folder.restype = ctypes.c_long
        result = {}
        for name, csidl in (('Documents', 5), ('Music', 13), ('Videos', 14)):
            buffer = ctypes.create_unicode_buffer(32768)
            if get_folder(None, csidl, None, 0, buffer) == 0 and buffer.value:
                result[name] = Path(buffer.value)
        return result
    except (OSError, AttributeError):
        return {}


def user_folder_locations(include_missing=False):
    native = _windows_user_folders()
    home = Path.home()
    locations = []
    for name, aliases in ALIASES.items():
        candidates = [home / alias for alias in aliases]
        if name in native:
            candidates.insert(0, native[name])
        seen = set()
        for candidate in candidates:
            try:
                path = candidate.resolve()
                if (include_missing or path.is_dir()) and path not in seen:
                    seen.add(path)
                    locations.append((name, path))
            except OSError:
                continue
    return locations
