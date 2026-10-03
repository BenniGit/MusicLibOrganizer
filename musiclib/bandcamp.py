"""Bandcamp als zusätzliche Metadatenquelle.

Bandcamp hat keine offizielle API. Wir nutzen die öffentliche Suchseite und lesen
die strukturierten Daten (JSON-LD) der Track-Seiten aus.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

import requests

from .matcher import build_query
from .models import LocalTrack, TrackMeta
from .scanner import split_mix

SEARCH_URL = "https://bandcamp.com/search"
USER_AGENT = "Mozilla/5.0 (compatible; MusicLibOrganizer/0.2)"

_ITEMURL_RE = re.compile(r'<div class="itemurl">\s*<a href="([^"]+)"', re.I)
_HEADING_RE = re.compile(r'<div class="heading">\s*<a href="([^"]+)"', re.I)
_LDJSON_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_DURATION_RE = re.compile(r"P(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?")


class BandcampError(RuntimeError):
    pass


def _strip_query(url: str) -> str:
    p = urlsplit(html.unescape(url))
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def parse_search(page: str, limit: int = 5) -> list[str]:
    """Liefert die Track-URLs aus einer Bandcamp-Suchergebnisseite."""
    urls = []
    for u in _ITEMURL_RE.findall(page) + _HEADING_RE.findall(page):
        u = _strip_query(u)
        if "/track/" in u and u not in urls:
            urls.append(u)
    return urls[:limit]


def parse_duration(s: str) -> int | None:
    m = _DURATION_RE.fullmatch(s or "")
    if not m or not any(m.groups()):
        return None
    h, mi, sec = (float(g) if g else 0 for g in m.groups())
    return int((h * 3600 + mi * 60 + sec) * 1000)


def parse_date(s: str) -> str:
    for fmt in ("%d %b %Y %H:%M:%S %Z", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime((s or "").strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _name(obj) -> str:
    if isinstance(obj, list):
        obj = obj[0] if obj else {}
    return (obj or {}).get("name", "") if isinstance(obj, dict) else str(obj or "")


def parse_track_page(page: str, url: str) -> TrackMeta | None:
    """Liest die Track-Metadaten aus dem JSON-LD-Block einer Track-Seite."""
    for block in _LDJSON_RE.findall(page):
        try:
            data = json.loads(html.unescape(block))
        except ValueError:
            continue
        if data.get("@type") != "MusicRecording":
            continue
        artist = _name(data.get("byArtist"))
        publisher = _name(data.get("publisher"))
        # Veröffentlicht der Artist selbst, gibt es kein Label
        label = "" if not publisher or publisher.lower() == artist.lower() else publisher
        keywords = data.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",")]
        image = data.get("image") or ""
        if isinstance(image, list):
            image = image[0] if image else ""
        name, mix = split_mix(data.get("name") or "")
        album = data.get("inAlbum") or {}
        return TrackMeta(
            id=url,
            name=name,
            mix=mix,
            artists=[artist] if artist else [],
            release=_name(album) if album else "",
            label=label,
            genre=keywords[0].title() if keywords else "",
            sub_genre=", ".join(keywords[1:4]),
            isrc=data.get("isrcCode") or "",
            release_date=parse_date(data.get("datePublished") or ""),
            length_ms=parse_duration(data.get("duration") or ""),
            image_url=image,
            source="Bandcamp",
            url=url,
        )
    return None


class BandcampClient:
    name = "Bandcamp"

    def __init__(self, session: requests.Session | None = None, timeout: float = 30, max_results: int = 3):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_results = max_results

    def _fetch(self, url: str, params: dict | None = None) -> str:
        try:
            r = self.session.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=self.timeout)
        except requests.RequestException as e:
            raise BandcampError(f"nicht erreichbar ({type(e).__name__})") from e
        if r.status_code != 200:
            raise BandcampError(f"Bandcamp {url} -> {r.status_code}")
        return r.text

    def search_text(self, query: str) -> list[TrackMeta]:
        page = self._fetch(SEARCH_URL, {"q": query, "item_type": "t"})
        out = []
        for url in parse_search(page, self.max_results):
            meta = parse_track_page(self._fetch(url), url)
            if meta:
                out.append(meta)
        return out

    def search(self, local: LocalTrack) -> list[TrackMeta]:
        query = build_query(local)
        return self.search_text(query) if query else []

    def download_image(self, url: str) -> bytes | None:
        if not url:
            return None
        try:
            r = self.session.get(url, headers={"User-Agent": USER_AGENT}, timeout=self.timeout)
        except requests.RequestException:
            return None
        return r.content if r.status_code == 200 else None
