"""Führt den geplanten Ablauf aus: konvertieren/kopieren/verschieben, dann taggen."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from .converter import to_mp3
from .models import LibraryItem, TrackMeta
from .backup import backup_tags
from .tagger import TagOptions, kept_frames, write_tags


def move_to_trash(path: Path) -> None:
    """In den Papierkorb (wiederherstellbar); ohne Papierkorb wird gelöscht."""
    try:
        from PySide6.QtCore import QFile

        if QFile.moveToTrash(str(path)):
            return
    except Exception:
        pass
    path.unlink()


def remove_empty_dirs(directory: Path, levels: int = 2) -> None:
    """Leer gewordene Release-/Artist-Ordner entfernen (.DS_Store zählt nicht als Inhalt)."""
    for _ in range(levels):
        try:
            entries = list(directory.iterdir())
        except OSError:
            return
        if any(e.name != ".DS_Store" for e in entries):
            return
        for e in entries:
            e.unlink()
        directory.rmdir()
        directory = directory.parent


def replace_previous(item: LibraryItem) -> str:
    """Nach erneutem Bearbeiten: die frühere Version in der neuen Library entfernen."""
    prev, dst = item.previous, item.target
    item.previous = None
    if prev is None or dst is None or not prev.exists() or not dst.exists():
        return ""
    if prev.resolve() == dst.resolve():
        return ""  # gleiche Datei wurde überschrieben
    move_to_trash(prev)
    remove_empty_dirs(prev.parent)
    return "alte Version in den Papierkorb"


@dataclass
class ApplyOptions:
    move: bool = False  # False: Originale bleiben liegen, True: Originale werden entfernt
    tag: TagOptions = field(default_factory=TagOptions)
    label_fallback: str = ""
    backup_dir: Path | None = None  # None = Standardordner, siehe backup.py


def apply_item(item: LibraryItem, opts: ApplyOptions, cover_loader: Callable[[TrackMeta], bytes | None] | None = None,
               tags: list[str] | None = None) -> str:
    """Verarbeitet einen Eintrag und gibt eine kurze Beschreibung zurück.

    ``tags``: eigene #Tags für den Kommentar (None = Kommentar nicht anfassen).
    """
    src = item.local.path
    dst = item.target
    if dst is None:
        raise ValueError("Kein Ziel berechnet")
    dst.parent.mkdir(parents=True, exist_ok=True)
    same_file = dst.exists() and dst.resolve() == src.resolve()
    actions = []
    # Vor dem Verschieben/Überschreiben: zu behaltende Tags lesen und alte Tags sichern
    keep = kept_frames(src, item.keep_tags) if item.selected else []
    if item.selected and opts.tag.clean:
        backup_tags(item.local, dst, opts.backup_dir)

    if item.local.needs_conversion:
        to_mp3(src, dst)
        actions.append("konvertiert")
    elif not same_file:
        if opts.move:
            shutil.move(str(src), str(dst))
            actions.append("verschoben")
        else:
            shutil.copy2(src, dst)
            actions.append("kopiert")

    if item.selected:
        meta = item.selected
        if not meta.label.strip() and opts.label_fallback.strip():
            meta = replace(meta, label=opts.label_fallback.strip())
        cover = None
        if opts.tag.embed_cover and cover_loader and meta.image_url:
            try:
                cover = cover_loader(meta)
            except Exception:
                cover = None
        write_tags(dst, meta, opts.tag, cover, keep, tags)
        actions.append("getaggt")

    if opts.move and item.local.needs_conversion and src.exists():
        src.unlink()
        actions.append("Original gelöscht")
    replaced = replace_previous(item)
    if replaced:
        actions.append(replaced)
    return ", ".join(actions) or "unverändert"


def make_cover_loader(sources) -> Callable[[TrackMeta], bytes | None]:
    """Lädt Cover über die Quelle, aus der die Metadaten stammen (mit Cache pro URL)."""
    if not isinstance(sources, (list, tuple)):
        sources = [sources]
    by_name = {getattr(s, "name", ""): s for s in sources}
    cache: dict[str, bytes | None] = {}

    def load(meta: TrackMeta) -> bytes | None:
        src = by_name.get(meta.source)
        if src is None or not meta.image_url:
            return None
        if meta.image_url not in cache:
            cache[meta.image_url] = src.download_image(meta.image_url)
        return cache[meta.image_url]

    return load
