"""Berechnet Zielpfade aus einer Vorlage wie '{genre}/{artist} - {title} ({mix})'."""
from __future__ import annotations

import re
import string
from pathlib import Path

from .models import LibraryItem
from .tagger import format_key

DEFAULT_TEMPLATE = "{genre}/{artist} - {title} ({mix})"
UNKNOWN_GENRE = "_Unbekannt"
PLACEHOLDERS = ("artist", "title", "mix", "genre", "label", "album", "year", "bpm", "key")

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EMPTY_BRACKETS = re.compile(r"\s*(\(\s*\)|\[\s*\])")
_MAX_COMPONENT = 150


def sanitize(component: str) -> str:
    s = _INVALID.sub("_", component)
    s = _EMPTY_BRACKETS.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
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


def fields_for(item: LibraryItem, key_format: str = "camelot") -> dict[str, str]:
    bp = item.selected
    loc = item.local
    if bp:
        return {
            "artist": bp.artist,
            "title": bp.name,
            "mix": bp.mix,
            "genre": bp.genre or UNKNOWN_GENRE,
            "label": bp.label,
            "album": bp.release,
            "year": bp.release_date[:4],
            "bpm": str(bp.bpm or ""),
            "key": format_key(bp, key_format),
        }
    return {
        "artist": loc.artist or "Unbekannt",
        "title": loc.title or loc.path.stem,
        "mix": loc.mix,
        "genre": UNKNOWN_GENRE,
        "label": "",
        "album": loc.album,
        "year": "",
        "bpm": "",
        "key": "",
    }


def target_path(item: LibraryItem, target_root: Path, template: str, key_format: str = "camelot") -> Path:
    fields = {k: re.sub(r"\s*/\s*", " - ", v) for k, v in fields_for(item, key_format).items()}
    rendered = template.format(**fields)
    parts = [sanitize(p) for p in rendered.split("/") if p.strip()] or ["_"]
    parts[-1] += ".mp3"
    return target_root.joinpath(*parts)


def assign_targets(items: list[LibraryItem], target_root: Path, template: str, key_format: str = "camelot") -> None:
    """Setzt item.target für alle aktiven Einträge und löst Namenskonflikte auf."""
    taken: set[Path] = set()
    for item in items:
        if not item.enabled:
            item.target = None
            continue
        base = target_path(item, target_root, template, key_format)
        candidate = base
        n = 2
        while candidate.as_posix().lower() in taken or (candidate.exists() and candidate.resolve() != item.local.path.resolve()):
            candidate = base.with_name(f"{base.stem} ({n}){base.suffix}")
            n += 1
        taken.add(candidate.as_posix().lower())
        item.target = candidate
