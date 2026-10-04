"""Schreibt Beatport-Metadaten als ID3v2.4-Tags in MP3-Dateien."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mutagen
from mutagen.apev2 import delete as delete_ape
from mutagen.id3 import (
    APIC, COMM, ID3, ID3NoHeaderError, TALB, TBPM, TCON, TDRC, TIT2, TKEY, TPE1, TPE2, TPE4, TPOS, TPUB, TRCK, TSRC,
    TXXX, WOAF, Frame,
)
from mutagen.id3 import delete as delete_id3

from . import hashtags
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
    clean: bool = True  # alle vorhandenen Tags entfernen, bevor neue geschrieben werden


def format_key(track: TrackMeta, key_format: str) -> str:
    if key_format == "camelot" and track.key_camelot:
        return track.key_camelot
    return track.key_name or track.key_camelot


def format_title(track: TrackMeta, mix_in_title: bool) -> str:
    if mix_in_title and track.mix:
        return f"{track.name} ({track.mix})"
    return track.name


def kept_frames(src: Path, keys: set[str]) -> list[Frame]:
    """Liest die ausgewählten vorhandenen Tags aus der Originaldatei (ID3-Frames oder FLAC-Kommentare)."""
    if not keys:
        return []
    try:
        audio = mutagen.File(src)
    except Exception:
        return []
    tags = getattr(audio, "tags", None)
    if tags is None:
        return []
    if isinstance(tags, ID3):
        return [tags[k] for k in keys if k in tags]
    frames = []
    for k in sorted(keys):  # FLAC-Kommentare werden zu benutzerdefinierten ID3-Feldern
        values = tags.get(k)
        if values:
            frames.append(TXXX(encoding=3, desc=k.upper(), text=list(values)))
    return frames


def write_tags(path: Path, track: TrackMeta, opts: TagOptions, cover: bytes | None = None,
               keep: list[Frame] | None = None, comment_tags: list[str] | None = None) -> None:
    """Schreibt die Metadaten. ``comment_tags`` (ohne '#') landen als '#tag #tag' im Kommentar;
    None lässt Kommentare unverändert."""
    if opts.clean:
        delete_id3(path, delete_v1=True, delete_v2=True)
        try:
            delete_ape(path)
        except Exception:
            pass
        tags = ID3()
    else:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
    for frame in keep or []:
        tags.add(frame)

    def put(frame_cls, value, **kw):
        tags.delall(frame_cls.__name__ if not kw.get("desc") else f"{frame_cls.__name__}:{kw['desc']}")
        if value not in (None, ""):
            tags.add(frame_cls(encoding=3, text=[str(value)], **kw))

    put(TPE1, track.artist)
    put(TIT2, format_title(track, opts.mix_in_title))
    put(TPE2, track.effective_album_artist)
    put(TALB, track.release)
    if track.track_number:
        put(TRCK, f"{track.track_number}/{track.track_total}" if track.track_total else track.track_number)
    else:
        put(TRCK, "")
    put(TPOS, track.disc_number)
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

    if comment_tags is not None:
        # Behaltener Kommentartext bleibt erhalten, alte #Tags werden durch die aktuellen ersetzt
        keep_text = " ".join(" ".join(map(str, f.text)) for f in tags.getall("COMM") if not f.desc)
        for key in [k for k, f in tags.items() if k.startswith("COMM") and not f.desc]:
            del tags[key]
        text = hashtags.format_comment(comment_tags, keep_text)
        if text:
            tags.add(COMM(encoding=3, lang="eng", desc="", text=[text]))

    if opts.embed_cover and cover:
        tags.delall("APIC")
        mime = "image/png" if cover.startswith(b"\x89PNG") else "image/jpeg"
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover))

    tags.save(path, v2_version=4, v1=0)
