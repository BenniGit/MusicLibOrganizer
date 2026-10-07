"""Den ganzen Library-Ordner umbenennen/verschieben (z. B. „LibOrganized“ → „Library“).

Der Ordner wird umbenannt und jede Datei mit altem und neuem Pfad ins Umzugs-Journal eingetragen.
Danach stellt „Rekordbox umstellen“ alle Pfade um – Sterne, Cues und Playlists bleiben erhalten.
"""
from __future__ import annotations

import os
from pathlib import Path

from .journal import Journal
from .scanner import SUPPORTED_EXTENSIONS


def check(old_root: Path, new_root: Path) -> str | None:
    """Fehlermeldung oder None, wenn das Umbenennen möglich ist."""
    old_root, new_root = Path(old_root), Path(new_root)
    if not old_root.is_dir():
        return f"Ordner nicht gefunden: {old_root}"
    if new_root.exists():
        return (f"„{new_root}“ existiert schon. Bitte den alten Ordner zuerst löschen, archivieren "
                "oder umbenennen (und bei Nextcloud warten, bis der Abgleich fertig ist).")
    if old_root.resolve() in new_root.resolve().parents or new_root.resolve() in old_root.resolve().parents:
        return "Der neue Ordner darf nicht im alten liegen (und umgekehrt)."
    if not new_root.parent.is_dir():
        return f"Übergeordneter Ordner fehlt: {new_root.parent}"
    return None


def audio_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
            and not p.name.startswith("._")]


def rename_library(old_root: Path, new_root: Path, journal: Journal) -> int:
    """Benennt um und trägt alle Dateien ins Journal ein. Gibt die Anzahl der Dateien zurück."""
    err = check(old_root, new_root)
    if err:
        raise ValueError(err)
    os.rename(old_root, new_root)  # gleiche Festplatte: geht sofort, nichts wird kopiert
    files = audio_files(new_root)
    for f in files:
        journal.record(Path(old_root) / f.relative_to(new_root), f, commit=False)
    journal.commit()
    return len(files)
