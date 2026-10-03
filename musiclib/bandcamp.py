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

from . import http
from .matcher import build_query
from .models import LocalTrack, TrackMeta
from .scanner import split_mix

SEARCH_URL = "https://bandcamp.com/search"
# Dieselbe Schnittstelle, die die Suchleiste auf bandcamp.com benutzt
AUTOCOMPLETE_URL = "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic"
# Bandcamp blockt Anfragen, die nicht wie ein Browser aussehen
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}

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
        if isinstance(album, list):
            album = album[0] if album else {}
        album_artist = _name(album.get("byArtist")) or artist
        num = re.search(r'"track_num"\s*:\s*(\d+)', page) or re.search(r'&quot;track_num&quot;:(\d+)', page)
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
            album_artist=album_artist,
            track_number=int(num.group(1)) if num else (data.get("position") if isinstance(data.get("position"), int) else None),
            track_total=album.get("numTracks") if isinstance(album.get("numTracks"), int) else None,
            enriched=True,
        )
    return None


def parse_autocomplete(data: dict, limit: int = 5) -> list[dict]:
    """Track-Treffer aus der JSON-Antwort der Bandcamp-Suche: [{url, name, artist, album, image}]."""
    out = []
    for r in ((data or {}).get("auto") or {}).get("results") or []:
        if r.get("type") != "t":
            continue
        url = r.get("item_url_path") or r.get("url") or ""
        if url.startswith("/"):
            url = (r.get("item_url_root") or "").rstrip("/") + url
        if "/track/" not in url:
            continue
        out.append({"url": _strip_query(url), "name": r.get("name") or "", "artist": r.get("band_name") or "",
                    "album": r.get("album_name") or "", "image": r.get("img") or ""})
    return out[:limit]


class BandcampClient:
    name = "Bandcamp"

    def __init__(self, session: requests.Session | None = None, timeout: float = 30, max_results: int = 3,
                 backoff: float = 1.0):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_results = max_results
        self.backoff = backoff
        self.breaker = http.CircuitBreaker("Bandcamp")

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        try:
            self.breaker.check()
        except http.SourceDown as e:
            raise BandcampError(str(e)) from e
        try:
            r = http.request(self.session, method, url, headers=HEADERS, timeout=self.timeout,
                             backoff=self.backoff, **kwargs)
        except requests.RequestException as e:
            self.breaker.failure()
            raise BandcampError(f"nicht erreichbar ({type(e).__name__})") from e
        if r.status_code in http.RETRY_STATUS:
            self.breaker.failure()
        else:
            self.breaker.success()
        if r.status_code != 200:
            raise BandcampError(http.describe(r.status_code, r.text))
        return r

    def _find(self, query: str) -> list[dict]:
        """Sucht Tracks – zuerst über die JSON-Schnittstelle, sonst über die Suchseite."""
        try:
            r = self._request("POST", AUTOCOMPLETE_URL, json={
                "search_text": query, "search_filter": "t", "full_page": False, "fan_id": None})
            hits = parse_autocomplete(r.json(), self.max_results)
            if hits:
                return hits
        except (BandcampError, ValueError):
            pass
        page = self._request("GET", SEARCH_URL, params={"q": query, "item_type": "t"}).text
        return [{"url": u} for u in parse_search(page, self.max_results)]

    def search_text(self, query: str) -> list[TrackMeta]:
        out = []
        for hit in self._find(query):
            try:
                meta = parse_track_page(self._request("GET", hit["url"]).text, hit["url"])
            except BandcampError:
                meta = None
            if meta is None and hit.get("name"):
                # Track-Seite nicht lesbar: wenigstens die Daten aus der Suche verwenden
                name, mix = split_mix(hit["name"])
                meta = TrackMeta(id=hit["url"], name=name, mix=mix, artists=[hit["artist"]] if hit.get("artist") else [],
                                 release=hit.get("album", ""), image_url=hit.get("image", ""), source="Bandcamp",
                                 url=hit["url"], album_artist=hit.get("artist", ""), enriched=True)
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
            r = self.session.get(url, headers=HEADERS, timeout=self.timeout)
        except requests.RequestException:
            return None
        return r.content if r.status_code == 200 else None
