"""Bandcamp als zusätzliche Metadatenquelle.

Bandcamp hat keine offizielle API. Wir nutzen die öffentliche Suchseite und lesen
die strukturierten Daten (JSON-LD) der Track-Seiten aus.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import replace
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
# Seitendaten, die Bandcamps eigenes Skript nutzt (HTML-escaptes JSON im Attribut data-tralbum)
_TRALBUM_RE = re.compile(r'data-tralbum="([^"]*)"')
# Sichtbarer Text unter der Trackliste: „released February 16, 2024“
_RELEASED_RE = re.compile(r"released\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})")


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
    s = (s or "").strip()
    for fmt in ("%d %b %Y %H:%M:%S %Z", "%d %b %Y %H:%M:%S", "%d %b %Y", "%Y-%m-%d", "%B %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})T", s)  # ISO mit Uhrzeit: 2024-02-16T00:00:00Z
    return m.group(1) if m else ""


def _tralbum(page: str) -> dict:
    m = _TRALBUM_RE.search(page)
    if not m:
        return {}
    try:
        data = json.loads(html.unescape(m.group(1)))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def page_date(page: str, *candidates: str) -> str:
    """Erscheinungsdatum: zuerst die übergebenen Felder, dann die Seitendaten, zuletzt der sichtbare Text."""
    tralbum = _tralbum(page)
    current = tralbum.get("current") or {}
    for value in (*candidates, tralbum.get("album_release_date"), current.get("release_date"),
                  current.get("publish_date")):
        date = parse_date(value or "")
        if date:
            return date
    m = _RELEASED_RE.search(page)
    return parse_date(m.group(1)) if m else ""


def _int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.isdigit() else None


def _track_number(data: dict, page: str) -> int | None:
    """Tracknummer aus JSON-LD (additionalProperty „tracknum“) oder den Seitendaten."""
    for prop in data.get("additionalProperty") or []:
        if isinstance(prop, dict) and prop.get("name") in ("tracknum", "track_num"):
            num = _int(prop.get("value"))
            if num:
                return num
    for info in _tralbum(page).get("trackinfo") or []:
        num = _int((info or {}).get("track_num"))
        if num:
            return num
    num = re.search(r'"track_num"\s*:\s*(\d+)', page) or re.search(r'&quot;track_num&quot;:(\d+)', page)
    return int(num.group(1)) if num else _int(data.get("position"))


def album_url_of(page: str, url: str) -> str:
    """URL des Albums, zu dem eine Track-Seite gehört ("" bei Singles ohne Album)."""
    for data in _ld_blocks(page):
        if data.get("@type") != "MusicRecording":
            continue
        album = data.get("inAlbum") or {}
        if isinstance(album, list):
            album = album[0] if album else {}
        if "/album/" in (album.get("@id") or ""):
            return _strip_query(album["@id"])
    rel = _tralbum(page).get("album_url") or ""
    if rel.startswith("/album/"):
        p = urlsplit(url)
        return urlunsplit((p.scheme, p.netloc, rel, "", ""))
    return _strip_query(rel) if "/album/" in rel else ""


def _name(obj) -> str:
    if isinstance(obj, list):
        obj = obj[0] if obj else {}
    return (obj or {}).get("name", "") if isinstance(obj, dict) else str(obj or "")


def _ld_blocks(page: str) -> list[dict]:
    out = []
    for block in _LDJSON_RE.findall(page):
        try:
            data = json.loads(html.unescape(block))
        except ValueError:
            continue
        out += data if isinstance(data, list) else [data]
    return out


def _label_for(artist: str, publisher: str) -> str:
    # Veröffentlicht der Artist selbst, gibt es kein Label
    return "" if not publisher or publisher.lower() == artist.lower() else publisher


def _keywords(data: dict) -> list[str]:
    keywords = data.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",")]
    return keywords


def parse_album_page(page: str, url: str) -> list[TrackMeta]:
    """Liest alle Tracks einer Bandcamp-Album-Seite (JSON-LD 'MusicAlbum')."""
    for data in _ld_blocks(page):
        if data.get("@type") != "MusicAlbum":
            continue
        album_artist = _name(data.get("byArtist"))
        label = _label_for(album_artist, _name(data.get("publisher")))
        keywords = _keywords(data)
        image = data.get("image") or ""
        if isinstance(image, list):
            image = image[0] if image else ""
        tracklist = (data.get("track") or {}).get("itemListElement") or []
        total = data.get("numTracks") if isinstance(data.get("numTracks"), int) else len(tracklist)
        out = []
        for i, entry in enumerate(tracklist, 1):
            item = entry.get("item") or {}
            name, mix = split_mix(item.get("name") or "")
            artist = _name(item.get("byArtist")) or album_artist
            track_url = item.get("@id") or url
            out.append(TrackMeta(
                id=track_url, name=name, mix=mix, artists=[artist] if artist else [],
                release=data.get("name") or "", label=label,
                genre=keywords[0].title() if keywords else "", sub_genre=", ".join(keywords[1:4]),
                isrc=item.get("isrcCode") or "",
                release_date=page_date(page, data.get("datePublished") or ""),
                length_ms=parse_duration(item.get("duration") or ""), image_url=image,
                source="Bandcamp", url=track_url, album_artist=album_artist,
                track_number=_int(entry.get("position")) or _track_number(item, "") or i,
                track_total=total, enriched=True,
            ))
        return out
    return []


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
        single = not album or album.get("albumReleaseType") == "SingleRelease" or album.get("numTracks") == 1
        number = _track_number(data, page) or (1 if single else None)
        total = _int(album.get("numTracks")) or (1 if single else None)
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
            release_date=page_date(page, data.get("datePublished") or "", album.get("datePublished") or ""),
            length_ms=parse_duration(data.get("duration") or ""),
            image_url=image,
            source="Bandcamp",
            url=url,
            album_artist=album_artist,
            track_number=number,
            track_total=total,
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
        self._albums: dict[str, list[TrackMeta]] = {}

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

    def _album(self, album_url: str) -> list[TrackMeta]:
        """Album-Seite laden (pro Sitzung nur einmal je Album)."""
        if album_url not in self._albums:
            try:
                self._albums[album_url] = parse_album_page(self._request("GET", album_url).text, album_url)
            except BandcampError:
                return []  # nicht cachen – beim nächsten Track erneut versuchen
        return self._albums[album_url]

    def _track(self, url: str, page: str | None = None) -> TrackMeta | None:
        """Track-Seite lesen und, wenn der Track zu einem Album gehört, mit der Album-Seite abgleichen.

        Die Album-Seite ist für alles, was das Release betrifft, die verlässlichere Quelle: Tracknummer,
        Trackanzahl, Datum, Album-Artist, Label und Cover – und damit für alle Tracks eines Albums einheitlich.
        """
        page = self._request("GET", url).text if page is None else page
        meta = parse_track_page(page, url)
        album_url = album_url_of(page, url) if meta else ""
        if not album_url:
            return meta
        tracks = self._album(album_url)
        path = urlsplit(url).path.rstrip("/")
        match = next((t for t in tracks if urlsplit(t.url).path.rstrip("/") == path), None) or next(
            (t for t in tracks if (t.name, t.mix) == (meta.name, meta.mix)), None)
        if match is None:
            return meta
        return replace(
            meta,
            track_number=match.track_number or meta.track_number,
            track_total=match.track_total or meta.track_total,
            release_date=match.release_date or meta.release_date,
            release=match.release or meta.release,
            label=match.label or meta.label,
            album_artist=match.album_artist or meta.album_artist,
            image_url=match.image_url or meta.image_url,
        )

    def search_text(self, query: str) -> list[TrackMeta]:
        out = []
        for hit in self._find(query):
            try:
                meta = self._track(hit["url"])
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

    def from_url(self, url: str) -> list[TrackMeta]:
        """Track- oder Album-Seite laden (funktioniert auch mit eigenen Domains der Künstler)."""
        url = _strip_query(url)
        page = self._request("GET", url).text
        album = parse_album_page(page, url)
        if album:
            return album
        meta = self._track(url, page)
        if meta is None:
            raise BandcampError("auf der Seite wurden keine Track-Daten gefunden")
        return [meta]

    def download_image(self, url: str) -> bytes | None:
        if not url:
            return None
        try:
            r = self.session.get(url, headers=HEADERS, timeout=self.timeout)
        except requests.RequestException:
            return None
        return r.content if r.status_code == 200 else None
