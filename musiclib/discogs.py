"""Discogs als zusätzliche Metadatenquelle (benötigt ein persönliches Access-Token)."""
from __future__ import annotations

import os
import re

import requests

from . import http
from .models import LocalTrack, TrackMeta
from .scanner import split_mix

API = "https://api.discogs.com"
USER_AGENT = "MusicLibOrganizer/0.2 +https://github.com/BenniGit/MusicLibOrganizer"

_NUMBER_SUFFIX = re.compile(r"\s*\(\d+\)$")


class DiscogsError(RuntimeError):
    pass


def clean_name(name: str) -> str:
    """'Fisher (16)' -> 'Fisher', 'Artist*' -> 'Artist' (Discogs-Eigenheiten)."""
    return _NUMBER_SUFFIX.sub("", name.strip()).rstrip("*").strip()


def clean_label(name: str) -> str:
    """'Not On Label (… Self-released)' bedeutet: kein Label."""
    name = clean_name(name)
    return "" if name.lower().startswith("not on label") else name


def parse_duration(s: str) -> int | None:
    parts = [p for p in (s or "").split(":") if p.strip().isdigit()]
    if not parts:
        return None
    secs = 0
    for p in parts:
        secs = secs * 60 + int(p)
    return secs * 1000


def parse_disc(position: str) -> int | None:
    """'2-3' oder 'CD2-3' -> 2 (Mehr-Disc-Release); 'A1'/'3' -> None."""
    m = re.match(r"^(?:CD|DVD)?(\d+)[-.]\d+$", position.strip(), re.I)
    return int(m.group(1)) if m else None


def _artist_names(artists: list[dict]) -> list[str]:
    return [clean_name(a.get("anv") or a["name"]) for a in artists or []]


def tracks_from_release(rel: dict) -> list[TrackMeta]:
    """Macht aus einem Discogs-Release eine Liste von Track-Metadaten."""
    labels = rel.get("labels") or []
    label = clean_label(labels[0]["name"]) if labels else ""
    catno = labels[0].get("catno", "") if labels else ""
    if catno.lower() == "none":
        catno = ""
    styles = rel.get("styles") or []
    genres = rel.get("genres") or []
    images = rel.get("images") or []
    release_artists = _artist_names(rel.get("artists"))
    released = rel.get("released") or str(rel.get("year") or "")
    if released.endswith("-00"):
        released = released[:-3]
    album_artist = ", ".join(release_artists)
    if album_artist.lower() in ("various", "various artists") or len(release_artists) > 3:
        album_artist = "Various Artists"
    tracklist = [t for t in rel.get("tracklist") or [] if t.get("type_", "track") == "track"]
    out = []
    for number, t in enumerate(tracklist, 1):
        name, mix = split_mix(t.get("title") or "")
        extra = t.get("extraartists") or []
        out.append(TrackMeta(
            id=f"{rel['id']}-{t.get('position') or len(out) + 1}",
            name=name,
            mix=mix,
            artists=_artist_names(t.get("artists")) or release_artists,
            remixers=[clean_name(a["name"]) for a in extra if "remix" in (a.get("role") or "").lower()],
            release=rel.get("title") or "",
            label=label,
            catalog_number=catno,
            genre=styles[0] if styles else (genres[0] if genres else ""),
            sub_genre=", ".join(styles[1:]),
            release_date=released,
            length_ms=parse_duration(t.get("duration") or ""),
            image_url=images[0]["uri"] if images else "",
            source="Discogs",
            url=rel.get("uri") or f"https://www.discogs.com/release/{rel['id']}",
            album_artist=album_artist,
            track_number=number,
            track_total=len(tracklist),
            disc_number=parse_disc(t.get("position") or ""),
            release_id=str(rel["id"]),
            enriched=True,
        ))
    return out


class DiscogsClient:
    name = "Discogs"

    def __init__(self, token: str | None = None, session: requests.Session | None = None,
                 timeout: float = 30, max_releases: int = 3, backoff: float = 1.0):
        self.token = token or os.environ.get("DISCOGS_TOKEN", "")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_releases = max_releases
        self.backoff = backoff
        self.breaker = http.CircuitBreaker("Discogs")
        self._release_cache: dict[int, dict] = {}

    def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.token:
            raise DiscogsError("Kein Discogs-Token hinterlegt (Einstellungen → Quellen).")
        headers = {"User-Agent": USER_AGENT, "Authorization": f"Discogs token={self.token}"}
        try:
            self.breaker.check()
        except http.SourceDown as e:
            raise DiscogsError(str(e)) from e
        try:
            r = http.request(self.session, "GET", f"{API}{path}", params=params, headers=headers,
                             timeout=self.timeout, backoff=self.backoff)
        except requests.RequestException as e:
            self.breaker.failure()
            raise DiscogsError(f"nicht erreichbar ({type(e).__name__})") from e
        if r.status_code in http.RETRY_STATUS:
            self.breaker.failure()
        else:
            self.breaker.success()
        if r.status_code == 401:
            raise DiscogsError("Token ungültig – bitte in den Einstellungen prüfen.")
        if r.status_code != 200:
            raise DiscogsError(http.describe(r.status_code, r.text))
        return r.json()

    def release(self, release_id: int) -> dict:
        if release_id not in self._release_cache:
            self._release_cache[release_id] = self._get(f"/releases/{release_id}")
        return self._release_cache[release_id]

    def _tracks_for_results(self, results: list[dict]) -> list[TrackMeta]:
        out: list[TrackMeta] = []
        error: Exception | None = None
        for res in results[: self.max_releases]:
            try:
                out += tracks_from_release(self.release(res["id"]))
            except DiscogsError as e:  # ein kaputtes Release soll die anderen nicht verhindern
                error = e
        if not out and error:
            raise error
        return out

    def search(self, local: LocalTrack) -> list[TrackMeta]:
        params = {"type": "release", "per_page": 10}
        if local.artist and local.title:
            params.update(artist=re.sub(r"\b(feat\.?|ft\.?|featuring)\b.*$", "", local.artist, flags=re.I).strip(),
                          track=local.title)
        else:
            params["q"] = f"{local.artist} {local.title}".strip()
        results = self._get("/database/search", params).get("results", [])
        # Digitale Releases zuerst – die passen bei DJ-Files meist am besten
        results.sort(key=lambda r: 0 if "File" in (r.get("format") or []) else 1)
        return self._tracks_for_results(results)

    def search_text(self, query: str) -> list[TrackMeta]:
        results = self._get("/database/search", {"type": "release", "q": query, "per_page": 10}).get("results", [])
        return self._tracks_for_results(results)

    def download_image(self, url: str) -> bytes | None:
        if not url:
            return None
        try:
            r = self.session.get(url, headers={"User-Agent": USER_AGENT}, timeout=self.timeout)
        except requests.RequestException:
            return None
        return r.content if r.status_code == 200 else None
