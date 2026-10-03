"""Eigene Tags als #Hashtags im Kommentar – in Rekordbox per Suche und Intelligenter Playlist nutzbar.

Rekordbox liest "My Tags" nicht aus Dateien; der Kommentar wird aber importiert und ist durchsuchbar
("Kommentare enthält #peaktime").
"""
from __future__ import annotations

import re
import unicodedata

_TAG_RE = re.compile(r"#([0-9A-Za-z_]+)")

DEFAULT_TAG_GROUPS: dict[str, list[str]] = {
    "Situation": ["Warm-up", "Build-up", "Peak Time", "Closing", "After Hour"],
    "Komponenten": ["Vocal", "Instrumental", "Piano", "Acid", "Synth", "Percussion"],
    "Stimmung": ["Dark", "Deep", "Groovy", "Euphoric", "Melodic"],
}


def token(name: str) -> str:
    """'Peak Time' -> 'peaktime', 'Düster' -> 'duster' (so wie es im Kommentar steht, ohne '#')."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9_]", "", s)


def parse(text: str) -> list[str]:
    """Alle #Tags aus einem Kommentar (als Token, ohne '#', ohne Duplikate)."""
    out: list[str] = []
    for t in _TAG_RE.findall(text or ""):
        t = token(t)
        if t and t not in out:
            out.append(t)
    return out


def strip(text: str) -> str:
    """Kommentar ohne #Tags (für den Fall, dass ein alter Kommentar behalten wird)."""
    return re.sub(r"\s+", " ", _TAG_RE.sub("", text or "")).strip()


def format_comment(tokens: list[str], keep_text: str = "") -> str:
    tags = " ".join(f"#{t}" for t in tokens)
    return " ".join(p for p in (strip(keep_text), tags) if p)


def order(tokens: list[str], groups: dict[str, list[str]]) -> list[str]:
    """Sortiert in der Reihenfolge der Einstellungen; unbekannte Tags hinten."""
    known = [token(n) for names in groups.values() for n in names]
    return sorted(dict.fromkeys(tokens), key=lambda t: (known.index(t) if t in known else len(known), t))


def display_names(groups: dict[str, list[str]]) -> dict[str, str]:
    """Token -> Anzeigename ('peaktime' -> 'Peak Time')."""
    return {token(n): n for names in groups.values() for n in names}


def parse_groups_text(text: str) -> dict[str, list[str]]:
    """'Situation: Warm-up, Peak Time' je Zeile -> {'Situation': ['Warm-up', 'Peak Time']}."""
    groups: dict[str, list[str]] = {}
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        name, _, rest = line.partition(":")
        if not rest:
            name, rest = "Tags", name
        tags = [t.strip() for t in rest.split(",") if token(t.strip())]
        if tags:
            groups.setdefault(name.strip() or "Tags", []).extend(tags)
    return groups


def groups_to_text(groups: dict[str, list[str]]) -> str:
    return "\n".join(f"{g}: {', '.join(names)}" for g, names in groups.items())
