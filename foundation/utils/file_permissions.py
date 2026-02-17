"""
Helpers per permisos de fitxers — llegibles des del host quan Docker crea com root.

Quan el broker corre dins Docker (root), els fitxers queden amb permisos restrictius.
Aquest helper assegura 0o644 (fitxers) i 0o755 (directoris) perquè l'usuari del host pugui llegir.
"""

import os
from pathlib import Path

# Permisos: llegibles per tothom (incl. usuari host quan Docker=root)
FILE_MODE = 0o644
DIR_MODE = 0o755


def set_host_readable_permissions(path: Path | str) -> None:
    """
    Assegura que el fitxer/directori i els seus pares tinguin permisos llegibles des del host.

    - Fitxers: 0o644 (rw-r--r--)
    - Directoris: 0o755 (rwxr-xr-x)

    Silenciós si chmod falla (p.ex. sistema de fitxers no suportat).
    """
    path = Path(path)
    if not path.exists():
        return
    try:
        if path.is_file():
            os.chmod(path, FILE_MODE)
        else:
            os.chmod(path, DIR_MODE)
        # Assegurar que els pares permeten traversar
        p = path.parent
        while p and p != p.parent:
            try:
                if p.exists():
                    os.chmod(p, DIR_MODE)
            except OSError:
                pass
            p = p.parent
    except OSError:
        pass
