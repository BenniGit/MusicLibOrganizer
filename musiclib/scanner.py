"""Findet Audiodateien und liest vorhandene Tags bzw. den Dateinamen aus."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterator

import mutagen
from mutagen.id3 import ID3

from . import hashtags
from .models import SUPPORTED_EXTENSIONS, LocalTrack

_MIX_RE = re.compile(r"^(?P<title>.*?)\s*[\(\[](?P<mix>[^\)\]]*(?:mix|edit|remix|dub|version|rework|bootleg|vip|original|extended|instrumental|club|radio)[^\)\]]*)[\)\]]\s*$", re.I)
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


# ID3-Frame -> Feldname im Editor
ID3_FIELDS = {
    "TPE1": "artist", "TIT2": "title", "TPE2": "albumartist", "TALB": "album", "TPUB": "label",
    "TCON": "genre", "TBPM": "bpm", "TKEY": "key", "TDRC": "date", "TYER": "date", "TSRC": "isrc",
    "TPE4": "remixers", "TRCK": "track", "TPOS": "disc", "TXXX:CATALOGNUMBER": "catno",
    "TXXX:MIX": "mix", "TXXX:SUBGENRE": "subgenre",
}
# Vorbis-Kommentar (FLAC) -> Feldname
VORBIS_FIELDS = {
    "artist": "artist", "title": "title", "albumartist": "albumartist", "album artist": "albumartist",
    "album": "album", "label": "label", "organization": "label", "publisher": "label", "genre": "genre",
    "bpm": "bpm", "initialkey": "key", "key": "key", "date": "date", "year": "date", "isrc": "isrc",
    "remixer": "remixers", "tracknumber": "track", "discnumber": "disc", "catalognumber": "catno",
}
# Lesbare Namen für die Anzeige
ID3_LABELS = {
    "TPE1": "Artist", "TIT2": "Titel", "TPE2": "Album-Artist", "TALB": "Album", "TPUB": "Label", "TCON": "Genre",
    "TBPM": "BPM", "TKEY": "Key", "TDRC": "Datum", "TYER": "Jahr", "TSRC": "ISRC", "TPE4": "Remixer",
    "TRCK": "Tracknummer", "TPOS": "Disc", "TCOM": "Komponist", "TOPE": "Original-Artist", "TIT1": "Grouping",
    "TIT3": "Untertitel", "TCOP": "Copyright", "TENC": "Encoder", "TSSE": "Encoder-Einstellungen",
    "TDOR": "Original-Datum", "TLEN": "Länge", "TMED": "Medium", "COMM": "Kommentar", "USLT": "Lyrics",
    "APIC": "Cover", "POPM": "Rating", "PCNT": "Playcount", "GEOB": "Eingebettete Daten (z. B. Serato)",
    "PRIV": "Private Daten (z. B. Traktor)", "WOAF": "URL", "WXXX": "URL", "UFID": "Datei-ID",
}


def _frame_text(frame) -> str:
    text = getattr(frame, "text", None)
    if text is not None:
        return " / ".join(str(t) for t in text)
    if hasattr(frame, "url"):
        return frame.url
    data = getattr(frame, "data", None)
    if data is not None:
        return f"<{len(data)} Bytes>"
    if hasattr(frame, "rating"):
        return str(frame.rating)
    return str(frame)


def _read_id3(tags: ID3) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    old: dict[str, str] = {}
    raw: list[tuple[str, str, str]] = []
    for key, frame in tags.items():
        value = _frame_text(frame).strip()
        if not value:
            continue
        frame_id = key.split(":", 1)[0]
        label = ID3_LABELS.get(frame_id, frame_id)
        if frame_id in ("TXXX", "COMM", "WXXX") and getattr(frame, "desc", ""):
            label = f"{label} ({frame.desc})"
        raw.append((key, label, value))
        name = ID3_FIELDS.get(key) or ID3_FIELDS.get(frame_id if frame_id != "TXXX" else key.upper())
        if name and name not in old:
            old[name] = value
    return old, raw


def _read_vorbis(tags) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    old: dict[str, str] = {}
    raw: list[tuple[str, str, str]] = []
    for key in sorted({k.lower() for k in tags.keys()}):
        value = " / ".join(tags[key]).strip()
        if not value:
            continue
        raw.append((key, key.title(), value))
        name = VORBIS_FIELDS.get(key)
        if name and name not in old:
            old[name] = value
    return old, raw


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
            track.old, track.raw_tags = _read_id3(tags)
        elif tags is not None:  # Vorbis-Kommentare (FLAC)
            track.old, track.raw_tags = _read_vorbis(tags)
        comments = [v for k, _label, v in track.raw_tags
                    if k.split(":", 1)[0] == "COMM" or k.lower() in ("comment", "description")]
        track.hashtags = hashtags.parse(" ".join(comments))
        track.artist = track.old.get("artist", "")
        track.title = track.old.get("title", "")
        track.album = track.old.get("album", "")
        track.isrc = track.old.get("isrc", "")
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
