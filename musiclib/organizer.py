"""Berechnet Zielpfade aus einer Vorlage wie '{genre}/{artist} - {title} ({mix})'."""
from __future__ import annotations

import os
import re
import string
from datetime import date
from pathlib import Path

from .models import LibraryItem
from .tagger import format_key

from .settings import DEFAULT_TEMPLATE  # noqa: F401  (Re-Export)

UNKNOWN_GENRE = "_Unbekannt"
PLACEHOLDERS = ("artist", "albumartist", "title", "mix", "track", "disc", "album", "genre", "label", "catno",
                "year", "bpm", "key", "added")

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EMPTY_BRACKETS = re.compile(r"\s*(\(\s*\)|\[\s*\])")
_DOUBLE_SEP = re.compile(r"(\s+-\s+)(?:-\s+)+")
_EDGE_SEP = re.compile(r"^[\s\-–]+|[\s\-–]+$")
_MAX_COMPONENT = 150
# Rekordbox importiert keine Dateien, deren vollständiger Pfad länger als 255 Zeichen ist.
MAX_PATH_LEN = 255
_COLLISION_RESERVE = 4  # Platz für " (2)" bei gleichen Namen
_MIN_STEM, _MIN_DIR = 40, 20  # so weit wird höchstens gekürzt


def sanitize(component: str) -> str:
    s = _INVALID.sub("_", component)
    s = _EMPTY_BRACKETS.sub("", s)
    s = re.sub(r"\s+", " ", s)
    s = _DOUBLE_SEP.sub(" - ", s)  # leere Platzhalter zwischen " - " entfernen
    s = _EDGE_SEP.sub("", s).strip(" .")
    if len(s) > _MAX_COMPONENT:
        s = s[:_MAX_COMPONENT].rstrip(" .")
    return s or "_"


def template_fields(template: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def validate_template(template: str) -> str | None:
    """Gibt eine Fehlermeldung zurück oder None, wenn die Vorlage gültig ist."""
    try:
        unknown = template_fields(template) - set(PLACEHOLDERS)
    except ValueError as e:
        return f"Ungültige Vorlage: {e}"
    if unknown:
        return "Unbekannte Platzhalter: " + ", ".join(sorted(unknown))
    if not template.strip(" /"):
        return "Vorlage ist leer."
    return None


def fields_for(item: LibraryItem, key_format: str = "camelot", label_fallback: str = "") -> dict[str, str]:
    bp = item.selected
    loc = item.local
    added = date.today().strftime("%Y-%m")
    if bp:
        return {
            "artist": bp.artist,
            "albumartist": bp.effective_album_artist,
            "track": f"{bp.track_number:02d}" if bp.track_number else "",
            "disc": str(bp.disc_number or ""),
            "catno": bp.catalog_number,
            "title": bp.name,
            "mix": bp.mix,
            "genre": bp.genre or UNKNOWN_GENRE,
            "label": bp.label or label_fallback,
            "album": bp.release,
            "year": bp.release_date[:4],
            "bpm": str(bp.bpm or ""),
            "key": format_key(bp, key_format),
            "added": added,
        }
    old_track = loc.old.get("track", "").split("/")[0].strip()
    return {
        "artist": loc.artist or "Unbekannt",
        "albumartist": loc.old.get("albumartist") or loc.artist or "Unbekannt",
        "track": f"{int(old_track):02d}" if old_track.isdigit() else "",
        "disc": loc.old.get("disc", "").split("/")[0].strip(),
        "catno": loc.old.get("catno", ""),
        "title": loc.title or loc.path.stem,
        "mix": loc.mix,
        "genre": UNKNOWN_GENRE,
        "label": label_fallback,
        "album": loc.album,
        "year": loc.old.get("date", "")[:4],
        "bpm": "",
        "key": "",
        "added": added,
    }


def target_path(item: LibraryItem, target_root: Path, template: str, key_format: str = "camelot",
                label_fallback: str = "") -> Path:
    fields = {k: re.sub(r"\s*/\s*", " - ", v) for k, v in fields_for(item, key_format, label_fallback).items()}
    rendered = template.format(**fields)
    raw = rendered.split("/")
    # Leere Ordnerebenen (z. B. unbekanntes Album) fallen weg, der Dateiname nie
    parts = [s for s in (sanitize(p) for p in raw[:-1]) if s != "_"] + [sanitize(raw[-1])]
    parts = fit_path_length(target_root, parts)
    parts[-1] += ".mp3"
    return target_root.joinpath(*parts)


def _trim(s: str, n: int) -> str:
    return s[: max(n, 1)].rstrip(" .-–_([") or "_"


def fit_path_length(target_root: Path, parts: list[str], limit: int = MAX_PATH_LEN) -> list[str]:
    """Kürzt Dateiname (zuerst) und die längsten Ordnernamen, bis der Pfad inkl. '.mp3' passt."""
    parts = list(parts)
    root_len = len(os.path.abspath(target_root))
    budget = limit - _COLLISION_RESERVE - len(".mp3")

    def total() -> int:
        return root_len + sum(len(p) + 1 for p in parts)  # +1 je Trennzeichen "/"

    while total() > budget:
        excess = total() - budget
        stem_room = len(parts[-1]) - _MIN_STEM
        if stem_room > 0:
            parts[-1] = _trim(parts[-1], len(parts[-1]) - min(excess, stem_room))
            continue
        dirs = [(len(p), i) for i, p in enumerate(parts[:-1]) if len(p) > _MIN_DIR]
        if not dirs:  # Zielordner selbst ist schon fast zu lang – bestmöglich kürzen
            parts[-1] = _trim(parts[-1], len(parts[-1]) - excess)
            break
        length, i = max(dirs)
        parts[i] = _trim(parts[i], length - min(excess, length - _MIN_DIR))
    return parts


def assign_targets(items: list[LibraryItem], target_root: Path, template: str, key_format: str = "camelot",
                   label_fallback: str = "") -> None:
    """Setzt item.target für alle aktiven Einträge und löst Namenskonflikte auf."""
    taken: set[Path] = set()
    for item in items:
        if not item.enabled:
            item.target = None
            continue
        base = target_path(item, target_root, template, key_format, label_fallback)
        candidate = base
        n = 2
        while candidate.as_posix().lower() in taken or (candidate.exists() and candidate.resolve() != item.local.path.resolve()):
            candidate = base.with_name(f"{base.stem} ({n}){base.suffix}")
            n += 1
        taken.add(candidate.as_posix().lower())
        item.target = candidate
