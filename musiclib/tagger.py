"""Schreibt Beatport-Metadaten als ID3v2.4-Tags in MP3-Dateien."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen.id3 import (
    APIC, ID3, ID3NoHeaderError, TALB, TBPM, TCON, TDRC, TIT2, TKEY, TPE1, TPE4, TPUB, TSRC, TXXX, WOAF,
)

from .models import TrackMeta


# Camelot-Code -> Tonart (Schreibweise wie bei Beatport)
CAMELOT_TO_KEY = {
    "1A": "Ab Minor", "1B": "B Major", "2A": "Eb Minor", "2B": "F# Major", "3A": "Bb Minor", "3B": "Db Major",
    "4A": "F Minor", "4B": "Ab Major", "5A": "C Minor", "5B": "Eb Major", "6A": "G Minor", "6B": "Bb Major",
    "7A": "D Minor", "7B": "F Major", "8A": "A Minor", "8B": "C Major", "9A": "E Minor", "9B": "G Major",
    "10A": "B Minor", "10B": "D Major", "11A": "F# Minor", "11B": "A Major", "12A": "Db Minor", "12B": "E Major",
}


@dataclass
class TagOptions:
    key_format: str = "camelot"  # "camelot" | "musical"
    mix_in_title: bool = True
    embed_cover: bool = True


def format_key(track: TrackMeta, key_format: str) -> str:
    if key_format == "camelot" and track.key_camelot:
        return track.key_camelot
    return track.key_name or track.key_camelot


def format_title(track: TrackMeta, mix_in_title: bool) -> str:
    if mix_in_title and track.mix:
        return f"{track.name} ({track.mix})"
    return track.name


def write_tags(path: Path, track: TrackMeta, opts: TagOptions, cover: bytes | None = None) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    def put(frame_cls, value, **kw):
        tags.delall(frame_cls.__name__ if not kw.get("desc") else f"{frame_cls.__name__}:{kw['desc']}")
        if value not in (None, ""):
            tags.add(frame_cls(encoding=3, text=[str(value)], **kw))

    put(TPE1, track.artist)
    put(TIT2, format_title(track, opts.mix_in_title))
    put(TALB, track.release)
    put(TPUB, track.label)
    put(TCON, track.genre)
    put(TBPM, track.bpm)
    put(TKEY, format_key(track, opts.key_format))
    put(TDRC, track.release_date)
    put(TSRC, track.isrc)
    put(TPE4, ", ".join(track.remixers))
    put(TXXX, track.mix, desc="MIX")
    put(TXXX, track.catalog_number, desc="CATALOGNUMBER")
    put(TXXX, track.sub_genre, desc="SUBGENRE")
    if track.source in ("Beatport", "Discogs", "Bandcamp"):
        put(TXXX, track.id, desc=f"{track.source.upper()}_ID" if track.source != "Beatport" else "BEATPORT_TRACK_ID")
    put(TXXX, track.source, desc="METADATA_SOURCE")
    tags.delall("WOAF")
    if track.url:
        tags.add(WOAF(url=track.url))

    if opts.embed_cover and cover:
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))

    tags.save(path, v2_version=4)
