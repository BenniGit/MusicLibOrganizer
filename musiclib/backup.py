"""Sichert die vorhandenen Tags, bevor sie ersetzt werden (eine JSON-Zeile pro Datei)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .models import LocalTrack


def data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MusicLibOrganizer"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "MusicLibOrganizer"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "musiclib"


def backup_dir() -> Path:
    return data_dir() / "tag-backups"


def backup_tags(local: LocalTrack, target: Path | None, directory: Path | None = None) -> Path | None:
    """Hängt die alten Tags an die Backup-Datei des Tages an. Fehler sind nicht fatal."""
    if not local.raw_tags:
        return None
    directory = directory or backup_dir()
    now = datetime.now()
    path = directory / f"{now:%Y-%m-%d}.jsonl"
    record = {
        "time": now.isoformat(timespec="seconds"),
        "source": str(local.path),
        "target": str(target) if target else None,
        "tags": [{"key": k, "label": label, "value": v} for k, label, v in local.raw_tags],
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return None
    return path
