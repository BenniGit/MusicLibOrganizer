"""Führt den geplanten Ablauf aus: konvertieren/kopieren/verschieben, dann taggen."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .converter import to_mp3
from .models import LibraryItem
from .tagger import TagOptions, write_tags


@dataclass
class ApplyOptions:
    move: bool = False  # False: Originale bleiben liegen, True: Originale werden entfernt
    tag: TagOptions = field(default_factory=TagOptions)


def apply_item(item: LibraryItem, opts: ApplyOptions, cover_loader: Callable[[str], bytes | None] | None = None) -> str:
    """Verarbeitet einen Eintrag und gibt eine kurze Beschreibung zurück."""
    src = item.local.path
    dst = item.target
    if dst is None:
        raise ValueError("Kein Ziel berechnet")
    dst.parent.mkdir(parents=True, exist_ok=True)
    same_file = dst.exists() and dst.resolve() == src.resolve()
    actions = []

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
        cover = None
        if opts.tag.embed_cover and cover_loader and item.selected.image_url:
            try:
                cover = cover_loader(item.selected.image_url)
            except Exception:
                cover = None
        write_tags(dst, item.selected, opts.tag, cover)
        actions.append("getaggt")

    if opts.move and item.local.needs_conversion and src.exists():
        src.unlink()
        actions.append("Original gelöscht")
    return ", ".join(actions) or "unverändert"


def make_cover_loader(client) -> Callable[[str], bytes | None]:
    cache: dict[str, bytes | None] = {}

    def load(url: str) -> bytes | None:
        if url not in cache:
            cache[url] = client.download_image(url)
        return cache[url]

    return load
