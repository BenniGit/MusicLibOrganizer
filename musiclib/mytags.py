"""Markierungen im Kommentar im Format der Rekordbox-„My Tags“: ``/* Bootleg / Peak Time */ Kommentar``.

So schreibt Rekordbox selbst My Tags in den Kommentar („My Tag zu Kommentaren hinzufügen“). Zurück in
echte My Tags liest Rekordbox den Kommentar nicht – er ist aber in der Spalte „Kommentare“ sichtbar,
durchsuchbar und für Intelligente Playlists nutzbar („Kommentare enthält Bootleg“).
"""
from __future__ import annotations

import re

_BLOCK_RE = re.compile(r"/\*(.*?)\*/", re.S)


def parse(comment: str) -> list[str]:
    """Die Tags aus dem ersten ``/* … */``-Block eines Kommentars."""
    m = _BLOCK_RE.search(comment or "")
    return [t.strip() for t in m.group(1).split("/") if t.strip()] if m else []


def add(comment: str, tags: list[str]) -> str:
    """Ergänzt Tags im Block (vorhandene bleiben, keine Duplikate); der übrige Kommentar bleibt erhalten."""
    current = parse(comment)
    known = {t.casefold() for t in current}
    current += [t for t in tags if t.strip() and t.casefold() not in known]
    rest = re.sub(r"\s+", " ", _BLOCK_RE.sub("", comment or "", count=1)).strip()
    block = f"/* {' / '.join(current)} */" if current else ""
    return " ".join(p for p in (block, rest) if p)
