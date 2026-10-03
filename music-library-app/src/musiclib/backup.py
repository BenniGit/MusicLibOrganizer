"""Sicherung vor dem ersten Schreiben.

Jede Datei wird genau einmal gesichert: existiert die Sicherung schon, bleibt sie
unverändert, damit immer der Originalzustand wiederherstellbar ist.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def backup_path(path: Path, backup_dir: Path) -> Path:
    """Ziel der Sicherung: der absolute Pfad der Datei wird unter *backup_dir* gespiegelt.

    So findet restore die Sicherung unabhängig davon, ob ein Ordner oder eine
    einzelne Datei übergeben wurde.
    """
    path = Path(path).resolve()
    return Path(backup_dir) / path.relative_to(path.anchor)


def ensure_backup(path: Path, backup_dir: Path) -> Path:
    """Legt die Sicherung an, falls noch keine existiert, und gibt ihren Pfad zurück."""
    target = backup_path(path, backup_dir)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        shutil.copy2(path, tmp)  # copy2 behält das Änderungsdatum
        tmp.replace(target)
    return target


def restore(path: Path, backup_dir: Path) -> bool:
    """Stellt eine Datei aus der Sicherung wieder her. False, wenn keine Sicherung existiert."""
    source = backup_path(path, backup_dir)
    if not source.exists():
        return False
    shutil.copy2(source, path)
    return True
