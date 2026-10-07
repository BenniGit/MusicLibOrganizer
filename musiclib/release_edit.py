"""Mehrere Tracks gemeinsam bearbeiten: Felder, die für ein ganzes Release gelten."""
from __future__ import annotations

from dataclasses import replace

from .manual import meta_from_local
from .models import LibraryItem, MatchStatus, TrackMeta
from .urlimport import local_track_number

# (Feld in TrackMeta, Bezeichnung, Zahl?)
RELEASE_FIELDS = [
    ("release", "Release / Album", False),
    ("album_artist", "Album-Artist", False),
    ("label", "Label", False),
    ("catalog_number", "Katalognummer", False),
    ("release_date", "Datum (JJJJ oder JJJJ-MM-TT)", False),
    ("genre", "Genre", False),
    ("sub_genre", "Sub-Genre", False),
    ("track_total", "Trackanzahl", True),
    ("disc_number", "Disc", True),
]


def base_meta(item: LibraryItem) -> TrackMeta:
    return item.selected or meta_from_local(item.local)


def common_values(metas: list[TrackMeta]) -> dict[str, str | None]:
    """Feld -> gemeinsamer Wert als Text, oder None, wenn die Tracks sich unterscheiden."""
    out: dict[str, str | None] = {}
    for name, _label, _num in RELEASE_FIELDS:
        values = {str(getattr(m, name) or "") for m in metas}
        out[name] = values.pop() if len(values) == 1 else None
    return out


def parse_changes(texts: dict[str, str]) -> dict[str, object]:
    """Text aus dem Dialog -> Werte für TrackMeta (leere Zahl = kein Wert)."""
    numeric = {name for name, _l, num in RELEASE_FIELDS if num}
    out: dict[str, object] = {}
    for name, text in texts.items():
        text = text.strip()
        if name in numeric:
            if text and not text.isdigit():
                raise ValueError(f"„{text}“ ist keine Zahl")
            out[name] = int(text) if text else None
        else:
            out[name] = text
    return out


def track_order(items: list[LibraryItem]) -> list[LibraryItem]:
    """Reihenfolge fürs Durchnummerieren: bisherige Tracknummer, sonst Reihenfolge in der Liste."""
    def key(pair):
        pos, it = pair
        number = (it.selected.track_number if it.selected else None) or local_track_number(it)
        return (number or 10_000, pos)

    return [it for _pos, it in sorted(enumerate(items), key=key)]


def apply_release_edit(items: list[LibraryItem], changes: dict[str, object], renumber: bool = False) -> int:
    """Setzt die gemeinsamen Felder für alle Tracks; gibt die Anzahl geänderter Tracks zurück."""
    if not changes and not renumber:
        return 0
    numbers = {id(it): n for n, it in enumerate(track_order(items), 1)} if renumber else {}
    for it in items:
        meta = replace(base_meta(it), **changes, edited=True, enriched=True)
        if renumber:
            meta = replace(meta, track_number=numbers[id(it)], track_total=len(items))
        it.selected = meta
        it.status = MatchStatus.MANUAL
        it.message = "Release gemeinsam bearbeitet"
    return len(items)
