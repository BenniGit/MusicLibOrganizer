"""SoundCloud-Seiten auslesen (nur per URL – für Bootlegs, Edits und Free Downloads).

SoundCloud bettet die Track-Daten als JSON in die Seite ein (``window.__sc_hydration``).
Ein API-Schlüssel ist dafür nicht nötig.
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urlsplit, urlunsplit

import requests

from . import http
from .models import TrackMeta
from .scanner import split_mix

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}

_HYDRATION_RE = re.compile(r"window\.__sc_hydration\s*=\s*(\[.*?\])\s*;\s*</script>", re.S)
_META_RE = re.compile(r'<meta\s+(?:property|name)="([^"]+)"\s+content="([^"]*)"', re.I)


class SoundCloudError(RuntimeError):
    pass


def _strip_query(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _artwork(url: str | None) -> str:
    # "-large" ist nur 100x100 – die 500er-Variante gibt es immer
    return (url or "").replace("-large.", "-t500x500.")


def split_artist_title(title: str, uploader: str) -> tuple[str, str]:
    """SoundCloud-Titel sind oft 'Artist - Titel (Bootleg)'; sonst ist der Uploader der Artist."""
    parts = re.split(r"\s+[-–—]\s+", title.strip(), maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0].strip(), parts[1].strip()
    return uploader.strip(), title.strip()


def track_from_sound(sound: dict, default_label: str = "") -> TrackMeta:
    """Macht aus einem SoundCloud-'sound'-Objekt Track-Metadaten (als eigene Single)."""
    pub = sound.get("publisher_metadata") or {}
    user = sound.get("user") or {}
    uploader = user.get("username") or user.get("full_name") or ""
    artist, rest = split_artist_title(sound.get("title") or "", uploader)
    if pub.get("artist"):
        artist = pub["artist"]
    name, mix = split_mix(rest)
    single = f"{name} ({mix})" if mix else name
    date = (sound.get("release_date") or sound.get("display_date") or sound.get("created_at") or "")[:10]
    url = sound.get("permalink_url") or ""
    return TrackMeta(
        id=str(sound.get("id") or url), name=name, mix=mix,
        artists=[a.strip() for a in artist.split(",") if a.strip()] or [uploader],
        release=pub.get("album_title") or pub.get("release_title") or single,
        label=sound.get("label_name") or pub.get("publisher") or default_label,
        genre=(sound.get("genre") or "").strip(),
        isrc=pub.get("isrc") or "",
        release_date=date,
        length_ms=sound.get("duration") or sound.get("full_duration"),
        image_url=_artwork(sound.get("artwork_url") or user.get("avatar_url")),
        source="SoundCloud", url=url, album_artist=artist,
        track_number=1, track_total=1, enriched=True,
    )


def parse_page(page: str, url: str, default_label: str = "") -> list[TrackMeta]:
    """Liest Track oder Set (Playlist) aus einer SoundCloud-Seite."""
    m = _HYDRATION_RE.search(page)
    if m:
        try:
            hydration = json.loads(m.group(1))
        except ValueError:
            hydration = []
        for entry in hydration:
            data = entry.get("data") or {}
            if entry.get("hydratable") == "sound":
                return [track_from_sound(data, default_label)]
            if entry.get("hydratable") == "playlist":
                tracks = [t for t in data.get("tracks") or [] if t.get("title")]  # nicht geladene Tracks fehlen
                metas = [track_from_sound(t, default_label) for t in tracks]
                total = data.get("track_count") or len(metas)
                for i, meta in enumerate(metas, 1):
                    meta.release = data.get("title") or meta.release
                    meta.album_artist = (data.get("user") or {}).get("username") or meta.album_artist
                    meta.track_number, meta.track_total = i, total
                return metas
    # Rückfall: Open-Graph-Angaben (Titel, Bild)
    meta = {k.lower(): html.unescape(v) for k, v in _META_RE.findall(page)}
    title = meta.get("og:title") or meta.get("twitter:title")
    if not title:
        return []
    artist, rest = split_artist_title(title, meta.get("soundcloud:user", "").rsplit("/", 1)[-1])
    name, mix = split_mix(rest)
    return [TrackMeta(id=url, name=name, mix=mix, artists=[artist] if artist else [],
                      release=f"{name} ({mix})" if mix else name, label=default_label,
                      image_url=meta.get("og:image", ""), source="SoundCloud", url=url, album_artist=artist,
                      track_number=1, track_total=1, enriched=True)]


class SoundCloudClient:
    name = "SoundCloud"

    def __init__(self, session: requests.Session | None = None, timeout: float = 30, default_label: str = "",
                 backoff: float = 1.0):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.default_label = default_label
        self.backoff = backoff

    def from_url(self, url: str) -> list[TrackMeta]:
        try:
            r = http.request(self.session, "GET", _strip_query(url), headers=HEADERS, timeout=self.timeout,
                             backoff=self.backoff)
        except requests.RequestException as e:
            raise SoundCloudError(f"nicht erreichbar ({type(e).__name__})") from e
        if r.status_code != 200:
            raise SoundCloudError(http.describe(r.status_code, r.text))
        tracks = parse_page(r.text, getattr(r, "url", url) or url, self.default_label)
        if not tracks:
            raise SoundCloudError("auf der Seite wurden keine Track-Daten gefunden")
        return tracks

    def download_image(self, url: str) -> bytes | None:
        if not url:
            return None
        try:
            r = self.session.get(url, headers=HEADERS, timeout=self.timeout)
        except requests.RequestException:
            return None
        return r.content if r.status_code == 200 else None
