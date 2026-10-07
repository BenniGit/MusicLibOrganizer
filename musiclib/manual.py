"""Manuelle und inoffizielle Erfassung (Bootlegs, Edits, SoundCloud-Uploads)."""
from __future__ import annotations

import re
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


_EDIT_WORDS = r"(bootleg|edit|re-?edit|rework|flip|refix|remix|mashup|vip|dub|version)"
_REMIXER_RE = re.compile(rf"^(.+?)\s+(?:'?s\s+)?{_EDIT_WORDS}\b", re.I)


def remixer_from_mix(mix: str) -> str:
    """'Someone Bootleg' -> 'Someone'; 'Extended Mix' -> ''."""
    m = _REMIXER_RE.match(mix.strip())
    if not m or m.group(1).lower() in ("original", "extended", "radio", "club", "dub", "vip"):
        return ""
    return m.group(1).strip()


def is_original_release(local: LocalTrack, base: TrackMeta) -> bool:
    """Ist ``base`` das offizielle Original (und nicht die Seite des Bootlegs selbst)?"""
    from .matcher import canonical_mix

    if base.source in ("Beatport", "Discogs"):
        return True
    return base.source == "Bandcamp" and bool(local.mix) and canonical_mix(local.mix) != canonical_mix(base.mix)


def from_original(local: LocalTrack, base: TrackMeta) -> TrackMeta:
    """Vom Original nur Artist, Titel, Genre, BPM und Key – alles, was zum Release gehört, gehört
    nicht zum Bootleg (sonst landet er im Ordner der Original-EP, mit fremdem Label und fremder ISRC)."""
    mix = local.mix.strip()
    remixer = remixer_from_mix(mix)
    return replace(
        base,
        id=str(local.path), source="Manuell", url="", image_url="", release_id="",
        mix=mix, remixers=[remixer] if remixer else [],
        release="", album_artist="", label="", catalog_number="", isrc="",
        track_number=None, track_total=None, disc_number=None, release_date="",
    )


def as_unofficial(local: LocalTrack, base: TrackMeta | None, label: str) -> TrackMeta:
    """Füllt die Pflichtfelder für inoffizielle Tracks sinnvoll vor.

    Der Track gilt als eigene Single: Album = Titel (inkl. Mix), Tracknummer 1/1,
    Album-Artist = Artist, Label = der feste Text aus den Einstellungen,
    Jahr = Veröffentlichungsdatum oder sonst das Dateidatum. Vorhandene Werte bleiben erhalten.
    Ist ``base`` ein Treffer des offiziellen Originals, werden nur Artist, Titel, Genre, BPM und Key
    übernommen; der Mix (z. B. „Someone Bootleg“) kommt aus der Datei, der Bootlegger wird Remixer.
    """
    if base is not None and is_original_release(local, base):
        base = from_original(local, base)
    meta = base or meta_from_local(local)
    if not meta.remixers and remixer_from_mix(meta.mix):
        meta = replace(meta, remixers=[remixer_from_mix(meta.mix)])
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
