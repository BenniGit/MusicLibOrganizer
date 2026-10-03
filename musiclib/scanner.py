"""Findet Audiodateien und liest vorhandene Tags bzw. den Dateinamen aus."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterator

import mutagen
from mutagen.id3 import ID3

from .models import SUPPORTED_EXTENSIONS, LocalTrack

_MIX_RE = re.compile(r"^(?P<title>.*?)\s*[\(\[](?P<mix>[^\)\]]*(?:mix|edit|remix|dub|version|rework|bootleg|vip)[^\)\]]*)[\)\]]\s*$", re.I)
_TRACKNO_RE = re.compile(r"^\s*\d{1,3}\s*[-._)]?\s+")


def iter_audio_files(root: Path) -> Iterator[Path]:
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS and not p.name.startswith("._"):
            yield p


def split_mix(title: str) -> tuple[str, str]:
    """'Song (Extended Mix)' -> ('Song', 'Extended Mix')."""
    m = _MIX_RE.match(title.strip())
    if m:
        return m.group("title").strip(), m.group("mix").strip()
    return title.strip(), ""


def parse_filename(stem: str) -> tuple[str, str, str]:
    """Ermittelt (Artist, Titel, Mix) aus einem Dateinamen wie '01 - Artist - Titel (Mix)'."""
    stem = _TRACKNO_RE.sub("", stem.replace("_", " ")).strip()
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", stem, maxsplit=1)]
    if len(parts) == 2:
        artist, rest = parts
    else:
        artist, rest = "", stem
    title, mix = split_mix(rest)
    return artist, title, mix


def _first(tags, *keys: str) -> str:
    for k in keys:
        v = tags.get(k) if tags is not None else None
        if v:
            if isinstance(v, list):
                v = v[0]
            v = getattr(v, "text", v)
            if isinstance(v, list):
                v = v[0] if v else ""
            if str(v).strip():
                return str(v).strip()
    return ""


def read_track(path: Path) -> LocalTrack:
    track = LocalTrack(path=path)
    try:
        audio = mutagen.File(path)
    except Exception:
        audio = None

    if audio is not None:
        if audio.info is not None:
            track.duration_s = getattr(audio.info, "length", None)
        tags = audio.tags
        if isinstance(tags, ID3):
            track.artist = _first(tags, "TPE1")
            track.title = _first(tags, "TIT2")
            track.album = _first(tags, "TALB")
            track.isrc = _first(tags, "TSRC", "TXXX:ISRC")
        elif tags is not None:  # Vorbis-Kommentare (FLAC)
            track.artist = _first(tags, "artist", "ARTIST")
            track.title = _first(tags, "title", "TITLE")
            track.album = _first(tags, "album", "ALBUM")
            track.isrc = _first(tags, "isrc", "ISRC")

    if track.title:
        track.title, track.mix = split_mix(track.title)

    if not track.artist or not track.title:
        fa, ft, fm = parse_filename(path.stem)
        track.artist = track.artist or fa
        if not track.title:
            track.title, track.mix = ft, fm
    return track


def scan(root: Path, progress: Callable[[int, int, Path], None] | None = None) -> list[LocalTrack]:
    files = list(iter_audio_files(root))
    tracks = []
    for i, p in enumerate(files, 1):
        tracks.append(read_track(p))
        if progress:
            progress(i, len(files), p)
    return tracks
