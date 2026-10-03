"""Metadaten direkt von einer URL laden (Beatport, Discogs, Bandcamp) und Dateien zuordnen."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .matcher import UNCERTAIN_THRESHOLD, score
from .models import LibraryItem, TrackMeta

_BEATPORT_RE = re.compile(r"beatport\.com/(?:[a-z]{2}/)?(track|release)/[^/]*/(\d+)", re.I)
_DISCOGS_RE = re.compile(r"discogs\.com/(?:[a-z]{2}/)?(release|master)/(\d+)", re.I)


class UrlImportError(RuntimeError):
    pass


def looks_like_url(text: str) -> bool:
    return bool(re.match(r"^\s*https?://\S+\s*$", text or "", re.I))


def detect(url: str) -> tuple[str, str, str]:
    """-> (Quelle, Art, ID). Bandcamp wird an /track/ bzw. /album/ erkannt (auch bei eigener Domain)."""
    url = url.strip()
    if m := _BEATPORT_RE.search(url):
        return "Beatport", m.group(1).lower(), m.group(2)
    if m := _DISCOGS_RE.search(url):
        return "Discogs", m.group(1).lower(), m.group(2)
    parts = urlsplit(url)
    if parts.netloc.lower().endswith("soundcloud.com") or parts.netloc.lower() == "snd.sc":
        kind = "set" if "/sets/" in parts.path else "track"
        return "SoundCloud", kind, url
    path = parts.path
    if "/track/" in path:
        return "Bandcamp", "track", url
    if "/album/" in path:
        return "Bandcamp", "album", url
    raise UrlImportError("Unbekannte URL. Unterstützt: Beatport (Track/Release), Discogs (Release/Master), "
                         "Bandcamp (Track/Album), SoundCloud (Track/Set).")


def load_url(url: str, clients: dict) -> list[TrackMeta]:
    """Lädt alle Tracks hinter der URL. ``clients`` bildet Quellennamen auf Clients ab."""
    source, kind, ident = detect(url)
    client = clients.get(source)
    if client is None:
        hint = {"Beatport": "Beatport-Zugangsdaten", "Discogs": "ein Discogs-Token"}.get(source, source)
        raise UrlImportError(f"Für {source}-URLs wird {hint} benötigt (Einstellungen → Quellen).")
    if source == "Beatport":
        return [client.track(ident)] if kind == "track" else client.release_tracks(ident)
    if source == "Discogs":
        return client.master_tracks(ident) if kind == "master" else client.release_tracks(ident)
    return client.from_url(ident)  # Bandcamp, SoundCloud


def assign_release(items: list[LibraryItem], tracks: list[TrackMeta],
                   min_score: float = UNCERTAIN_THRESHOLD) -> list[tuple[LibraryItem, TrackMeta, float]]:
    """Ordnet jeder Datei den passendsten Track des Releases zu (jeder Track höchstens einmal).

    Gibt die vorgenommenen Zuordnungen zurück; Dateien ohne ausreichend passenden Track bleiben frei.
    """
    pairs = sorted(((score(it.local, t), i, j) for i, it in enumerate(items) for j, t in enumerate(tracks)),
                   reverse=True)
    used_items: set[int] = set()
    used_tracks: set[int] = set()
    result = []
    for s, i, j in pairs:
        if s < min_score or i in used_items or j in used_tracks:
            continue
        used_items.add(i)
        used_tracks.add(j)
        result.append((items[i], tracks[j], s))

    # Zweiter Durchgang: Dateien wie "01 track.flac" über die Tracknummer zuordnen
    by_number = {t.track_number: j for j, t in enumerate(tracks) if t.track_number and j not in used_tracks}
    for i, it in enumerate(items):
        if i in used_items:
            continue
        number = local_track_number(it)
        j = by_number.pop(number, None) if number else None
        if j is not None:
            used_items.add(i)
            used_tracks.add(j)
            result.append((it, tracks[j], score(it.local, tracks[j])))
    return result


def local_track_number(item: LibraryItem) -> int | None:
    """Tracknummer aus den alten Tags ('3/12') oder vom Anfang des Dateinamens ('03 - ...')."""
    old = item.local.old.get("track", "").split("/")[0].strip()
    if old.isdigit():
        return int(old)
    m = re.match(r"^\s*(\d{1,3})(?:\D|$)", item.local.path.stem)
    return int(m.group(1)) if m else None
