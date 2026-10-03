"""Vollständiger Tag-Reset für MP3 und FLAC.

MP3: ID3v1, ID3v2 (inkl. eingebetteter Cover, Kommentare, Fremd-Frames) und APEv2.
FLAC: alle Vorbis-Comments, Bild-Blöcke, APPLICATION- und CUESHEET-Blöcke sowie
ID3/APE-Tags, die manche Programme fälschlich in FLAC-Dateien schreiben.

Die Audiodaten bleiben unverändert, ebenso das Änderungsdatum der Datei.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from mutagen import apev2
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.id3 import delete as id3_delete

SUPPORTED_SUFFIXES = {".mp3", ".flac"}

# FLAC-Blöcke, die zur Audiostruktur gehören und erhalten bleiben.
_FLAC_KEEP = {0: "STREAMINFO", 1: "PADDING", 3: "SEEKTABLE"}
_FLAC_BLOCK_NAMES = {2: "APPLICATION", 4: "VORBIS_COMMENT", 5: "CUESHEET", 6: "PICTURE"}


class ResetError(Exception):
    """Der Reset konnte nicht vollständig durchgeführt werden."""


@dataclass
class TagInventory:
    """Was in einer Datei an Metadaten steckt (nur zur Anzeige und Prüfung)."""

    path: Path
    id3v1: bool = False
    id3v2: list[str] = field(default_factory=list)  # Frame-IDs, z. B. "TIT2", "TXXX:TRAKTOR4"
    ape: list[str] = field(default_factory=list)
    vorbis: list[str] = field(default_factory=list)  # Feldnamen, Großbuchstaben
    flac_blocks: list[str] = field(default_factory=list)  # entfernbare Blöcke, z. B. "PICTURE"

    @property
    def is_clean(self) -> bool:
        return not (self.id3v1 or self.id3v2 or self.ape or self.vorbis or self.flac_blocks)

    def summary(self) -> list[str]:
        parts = []
        if self.id3v1:
            parts.append("ID3v1")
        if self.id3v2:
            parts.append(f"ID3v2: {len(self.id3v2)} Frames ({', '.join(sorted(set(self.id3v2)))})")
        if self.ape:
            parts.append(f"APEv2: {', '.join(sorted(self.ape))}")
        if self.vorbis:
            parts.append(f"Vorbis: {', '.join(sorted(set(self.vorbis)))}")
        if self.flac_blocks:
            parts.append(f"FLAC-Blöcke: {', '.join(self.flac_blocks)}")
        return parts


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def _has_id3v1(path: Path) -> bool:
    with open(path, "rb") as f:
        try:
            f.seek(-128, os.SEEK_END)
        except OSError:
            return False
        return f.read(3) == b"TAG"


def _id3v2_frames(path: Path) -> list[str]:
    try:
        # translate=False: Frames so zeigen, wie sie in der Datei stehen.
        tags = ID3(path, translate=False, load_v1=False)
    except ID3NoHeaderError:
        return []
    return [_printable(frame.HashKey) for frame in tags.values()]


def _printable(key: str, limit: int = 60) -> str:
    """Frame-Schlüssel wie PRIV enthalten Binärdaten; für die Anzeige kürzen."""
    key = "".join(ch for ch in key if ch.isprintable()).rstrip(": ")
    return key if len(key) <= limit else key[: limit - 1] + "…"


def _ape_keys(path: Path) -> list[str]:
    try:
        return list(apev2.APEv2(path).keys())
    except apev2.APENoHeaderError:
        return []


def inspect(path: Path) -> TagInventory:
    """Liest alle vorhandenen Tags einer Datei, ohne etwas zu ändern."""
    path = Path(path)
    inv = TagInventory(path=path)
    inv.id3v1 = _has_id3v1(path)
    inv.ape = _ape_keys(path)
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        inv.id3v2 = _id3v2_frames(path)
    elif suffix == ".flac":
        flac = FLAC(path)
        if flac.tags is not None:
            inv.vorbis = [key.upper() for key, _ in flac.tags]
        inv.flac_blocks = [
            _FLAC_BLOCK_NAMES.get(b.code, f"TYP{b.code}")
            for b in flac.metadata_blocks
            if b.code not in _FLAC_KEEP and not (b.code == 4 and not flac.tags)
        ]
        # ID3v2 vor dem fLaC-Header
        with open(path, "rb") as f:
            if f.read(3) == b"ID3":
                inv.id3v2 = _id3v2_frames(path) or ["(ID3v2-Header)"]
    else:
        raise ResetError(f"Nicht unterstütztes Format: {path.suffix}")
    return inv


def _reset_mp3(path: Path) -> None:
    # ID3v2 steht am Anfang, ID3v1 und APEv2 am Ende, oft verschachtelt
    # (ID3v1 hinter APE, mehrere ID3v1). Begrenzt wiederholen; was dann noch übrig
    # ist, meldet die Prüfung in reset().
    id3_delete(path, delete_v1=True, delete_v2=True)
    for _ in range(4):
        apev2.delete(path)
        if not _has_id3v1(path):
            break
        id3_delete(path, delete_v1=True, delete_v2=False)


def _reset_flac(path: Path) -> None:
    apev2.delete(path)
    flac = FLAC(path)
    flac.metadata_blocks = [b for b in flac.metadata_blocks if b.code in _FLAC_KEEP]
    flac.tags = None
    flac.cuesheet = None
    flac.save(deleteid3=True)


def reset(path: Path) -> TagInventory:
    """Entfernt alle Tags und prüft das Ergebnis.

    Gibt das Inventar *vor* dem Reset zurück. Das Änderungsdatum der Datei
    bleibt erhalten. Wirft ResetError, wenn danach noch Tags gefunden werden.
    """
    path = Path(path)
    before = inspect(path)
    if before.is_clean:
        return before

    st = os.stat(path)
    try:
        if path.suffix.lower() == ".mp3":
            _reset_mp3(path)
        else:
            _reset_flac(path)
    finally:
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))

    after = inspect(path)
    if not after.is_clean:
        raise ResetError(f"{path}: nach dem Reset noch vorhanden: {'; '.join(after.summary())}")
    return before
