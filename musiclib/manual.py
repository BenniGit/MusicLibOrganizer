"""Manuelle und inoffizielle Erfassung (Bootlegs, Edits, SoundCloud-Uploads)."""
from __future__ import annotations

from dataclasses import replace
from datetime import date

from .models import LocalTrack, TrackMeta
from .tagger import CAMELOT_TO_KEY, format_title


def split_number(value: str) -> tuple[int, int]:
    """'7/12' -> (7, 12); '7' -> (7, 0)."""
    parts = [p.strip() for p in value.split("/")]
    num = int(parts[0]) if parts and parts[0].isdigit() else 0
    total = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return num, total


def meta_from_local(local: LocalTrack) -> TrackMeta:
    """Startpunkt für manuelle Erfassung: alle bisherigen Tags der Datei vorausgefüllt."""
    old = local.old
    num, total = split_number(old.get("track", ""))
    disc, _ = split_number(old.get("disc", ""))
    try:
        bpm = round(float(old.get("bpm", "").replace(",", "."))) or None
    except ValueError:
        bpm = None
    key = old.get("key", "").upper().replace(" ", "")
    return TrackMeta(
        id=str(local.path), name=local.title, mix=local.mix,
        artists=[a.strip() for a in local.artist.split(",") if a.strip()] if local.artist else [],
        remixers=[r.strip() for r in old.get("remixers", "").split(",") if r.strip()],
        album_artist=old.get("albumartist", ""), release=local.album,
        track_number=num or None, track_total=total or None, disc_number=disc or None,
        label=old.get("label", ""), catalog_number=old.get("catno", ""), genre=old.get("genre", ""),
        sub_genre=old.get("subgenre", ""), release_date=old.get("date", ""), isrc=local.isrc, bpm=bpm,
        key_camelot=key if key in CAMELOT_TO_KEY else "", key_name=CAMELOT_TO_KEY.get(key, old.get("key", "")),
        source="Manuell", enriched=True,
    )


def _file_date(local: LocalTrack) -> str:
    try:
        return date.fromtimestamp(local.path.stat().st_mtime).isoformat()
    except OSError:
        return ""


def as_unofficial(local: LocalTrack, base: TrackMeta | None, label: str) -> TrackMeta:
    """Füllt die Pflichtfelder für inoffizielle Tracks sinnvoll vor.

    Der Track gilt als eigene Single: Album = Titel (inkl. Mix), Tracknummer 1/1,
    Album-Artist = Artist, Label = der feste Text aus den Einstellungen,
    Jahr = Veröffentlichungsdatum oder sonst das Dateidatum. Vorhandene Werte bleiben erhalten.
    """
    meta = base or meta_from_local(local)
    return replace(
        meta,
        release=meta.release or format_title(meta, True),
        album_artist=meta.album_artist or meta.artist,
        track_number=meta.track_number or 1,
        track_total=meta.track_total or (1 if not meta.track_number else None),
        label=meta.label or label,
        release_date=meta.release_date or _file_date(local),
        edited=True,
        enriched=True,
    )
