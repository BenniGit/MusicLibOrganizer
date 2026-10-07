"""Minimaler Client für die Beatport-API v4.

Anmeldung läuft über Benutzername/Passwort (wie auf beatport.com) und den
OAuth-Authorization-Code-Flow mit der öffentlichen Client-ID der API-Docs.
"""
from __future__ import annotations

import json
from dataclasses import replace
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from . import http
from .models import LocalTrack, TrackMeta

API = "https://api.beatport.com/v4"
REDIRECT_URI = f"{API}/auth/o/post-message/"


def _cache_dir() -> Path:
    """Plattformüblicher Cache-Ordner (macOS: ~/Library/Caches, Windows: %LOCALAPPDATA%)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "musiclib"


DEFAULT_TOKEN_CACHE = _cache_dir() / "beatport_token.json"


VARIOUS_ARTISTS = "Various Artists"
VARIOUS_LIMIT = 3  # mehr Release-Artists -> Compilation


class BeatportError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, territory: bool = False):
        super().__init__(message)
        self.status = status
        self.territory = territory  # „Territory Restricted“: im Land des Nutzers nicht verkauft


class BeatportClient:
    name = "Beatport"

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        client_id: str | None = None,
        token_cache: Path | None = DEFAULT_TOKEN_CACHE,
        session: requests.Session | None = None,
        timeout: float = 30,
    ):
        self.username = username or os.environ.get("BEATPORT_USERNAME", "")
        self.password = password or os.environ.get("BEATPORT_PASSWORD", "")
        self.client_id = client_id or os.environ.get("BEATPORT_CLIENT_ID")
        self.token_cache = token_cache
        self.session = session or requests.Session()
        self.timeout = timeout
        self._token: dict | None = None
        self._release_cache: dict[str, dict] = {}
        self._release_tracks_cache: dict[str, list[dict]] = {}
        self._restricted: set[str] = set()  # Releases, die Beatport im Land des Nutzers sperrt

    # ------------------------------------------------------------------ auth
    def _discover_client_id(self) -> str:
        """Liest die öffentliche Client-ID aus den Skripten der API-Doku."""
        html = self.session.get(f"{API}/docs/", timeout=self.timeout).text
        for src in re.findall(r'src="([^"]+\.js)"', html):
            url = src if src.startswith("http") else "https://api.beatport.com" + src
            js = self.session.get(url, timeout=self.timeout).text
            m = re.search(r"API_CLIENT_ID:\s*'([^']+)'", js)
            if m:
                return m.group(1)
        raise BeatportError("Client-ID konnte nicht ermittelt werden (BEATPORT_CLIENT_ID setzen).")

    def _store_token(self, tok: dict) -> None:
        tok["expires_at"] = time.time() + tok.get("expires_in", 0) - 60
        tok["username"] = self.username
        self._token = tok
        if self.token_cache:
            # Der Cache ist nur eine Bequemlichkeit: schlägt das Speichern fehl,
            # bleibt das Token für diese Sitzung im Speicher.
            try:
                self.token_cache.parent.mkdir(parents=True, exist_ok=True)
                self.token_cache.write_text(json.dumps(tok))
                self.token_cache.chmod(0o600)
            except OSError:
                pass

    def _load_cached_token(self) -> dict | None:
        if not self.token_cache:
            return None
        try:
            tok = json.loads(self.token_cache.read_text())
        except (OSError, ValueError):
            return None
        if tok.get("username") != self.username:
            return None
        return tok

    def login(self) -> str:
        """Meldet sich an und holt ein Access-Token. Gibt den Benutzernamen zurück."""
        if not self.username or not self.password:
            raise BeatportError("Benutzername/Passwort fehlen (BEATPORT_USERNAME / BEATPORT_PASSWORD).")
        if not self.client_id:
            self.client_id = self._discover_client_id()

        r = self.session.post(
            f"{API}/auth/login/",
            json={"username": self.username, "password": self.password},
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise BeatportError(f"Login fehlgeschlagen ({r.status_code}): {r.text[:200]}")

        r = self.session.get(
            f"{API}/auth/o/authorize/",
            params={"client_id": self.client_id, "response_type": "code", "redirect_uri": REDIRECT_URI},
            allow_redirects=False,
            timeout=self.timeout,
        )
        code = parse_qs(urlparse(r.headers.get("Location", "")).query).get("code", [None])[0]
        if not code:
            raise BeatportError(f"Autorisierung fehlgeschlagen ({r.status_code}).")

        r = self.session.post(
            f"{API}/auth/o/token/",
            data={
                "client_id": self.client_id,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise BeatportError(f"Token-Abruf fehlgeschlagen ({r.status_code}): {r.text[:200]}")
        self._store_token(r.json())
        return self.username

    def _refresh(self) -> bool:
        tok = self._token or {}
        if not tok.get("refresh_token"):
            return False
        if not self.client_id:
            self.client_id = self._discover_client_id()
        r = self.session.post(
            f"{API}/auth/o/token/",
            data={
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": tok["refresh_token"],
            },
            timeout=self.timeout,
        )
        if r.status_code != 200:
            return False
        self._store_token(r.json())
        return True

    def ensure_token(self) -> str:
        if self._token is None:
            self._token = self._load_cached_token()
        if self._token and self._token.get("expires_at", 0) > time.time():
            return self._token["access_token"]
        if self._token and self._refresh():
            return self._token["access_token"]
        self.login()
        return self._token["access_token"]

    # ------------------------------------------------------------------ api
    def _get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(4):
            headers = {"Authorization": f"Bearer {self.ensure_token()}"}
            try:
                r = http.request(self.session, "GET", f"{API}{path}", params=params, headers=headers,
                                 timeout=self.timeout, retries=2)
            except requests.RequestException as e:
                raise BeatportError(f"nicht erreichbar ({type(e).__name__})") from e
            if r.status_code == 401 and attempt == 0:
                self._token = None
                if self.token_cache:
                    try:
                        self.token_cache.unlink(missing_ok=True)
                    except OSError:
                        pass
                continue
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if r.status_code != 200:
                raise BeatportError(http.describe(r.status_code, r.text), status=r.status_code,
                                    territory="territory restricted" in r.text.lower())
            return r.json()
        raise BeatportError(f"GET {path}: zu viele Wiederholungen")

    def search_tracks(self, query: str, per_page: int = 10) -> list[TrackMeta]:
        data = self._get("/catalog/search/", {"q": query, "type": "tracks", "per_page": per_page})
        return [TrackMeta.from_api(t) for t in data.get("tracks", [])]

    def tracks_by_isrc(self, isrc: str) -> list[TrackMeta]:
        data = self._get("/catalog/tracks/", {"isrc": isrc, "per_page": 25})
        return [TrackMeta.from_api(t) for t in data.get("results", [])]

    def search(self, local: LocalTrack) -> list[TrackMeta]:
        """Sucht passende Tracks: zuerst über die ISRC, dann über Artist/Titel/Mix."""
        from .matcher import build_query

        found = self.tracks_by_isrc(local.isrc) if local.isrc else []
        query = build_query(local)
        if query:
            found += self.search_tracks(query)
        return found

    def search_text(self, query: str) -> list[TrackMeta]:
        return self.search_tracks(query, per_page=25)

    def release(self, release_id: str, name: str = "") -> dict:
        if release_id not in self._release_cache:
            try:
                self._release_cache[release_id] = self._get(f"/catalog/releases/{release_id}/")
            except BeatportError as e:
                if not e.territory:
                    raise
                self._restricted.add(release_id)
                self._release_cache[release_id] = self._release_from_search(release_id, name)
        return self._release_cache[release_id]

    def _release_from_search(self, release_id: str, name: str) -> dict:
        """Release-Daten über die Suche – die liefert auch Releases, deren Detailseite gesperrt ist."""
        if name:
            data = self._get("/catalog/search/", {"q": name, "type": "releases", "per_page": 25})
            for rel in data.get("releases", []):
                if str(rel.get("id")) == release_id:
                    return rel
        return {}

    def release_track_ids(self, release_id: str) -> list[str]:
        """Track-IDs eines Releases in Tracklisten-Reihenfolge.

        Achtung: Das Feld ``tracks`` im Release-Objekt ist umgekehrt sortiert –
        die richtige Reihenfolge liefert nur dieser Endpunkt.
        """
        return [str(t["id"]) for t in self._release_track_objects(release_id)]

    def _release_track_objects(self, release_id: str) -> list[dict]:
        if release_id not in self._release_tracks_cache:
            try:
                tracks = self._paged(f"/catalog/releases/{release_id}/tracks/", {})
            except BeatportError as e:
                if not e.territory:
                    raise
                # Im Land des Nutzers gesperrt: Die Trackliste gibt es dann nur noch über /catalog/tracks/,
                # allerdings ohne Reihenfolge. Beatport vergibt die IDs fast immer in Tracklisten-Reihenfolge.
                self._restricted.add(release_id)
                tracks = sorted(self._paged("/catalog/tracks/", {"release_id": release_id}), key=lambda t: int(t["id"]))
            self._release_tracks_cache[release_id] = tracks
        return self._release_tracks_cache[release_id]

    def _paged(self, path: str, params: dict) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            data = self._get(path, {**params, "per_page": 100, "page": page})
            out += data.get("results", [])
            if not data.get("next") or page >= 10:
                return out
            page += 1

    def track(self, track_id: str) -> TrackMeta:
        """Ein Track per Beatport-ID (z. B. aus einer Track-URL), inklusive Release-Details."""
        try:
            data = self._get(f"/catalog/tracks/{track_id}/")
        except BeatportError as e:
            if not e.territory:
                raise
            found = self._get("/catalog/tracks/", {"id": track_id}).get("results") or []
            if not found:
                raise
            data = found[0]
        return self.enrich(TrackMeta.from_api(data))

    def release_tracks(self, release_id: str) -> list[TrackMeta]:
        """Alle Tracks eines Releases in Tracklisten-Reihenfolge (z. B. aus einer Release-URL)."""
        return [self.enrich(TrackMeta.from_api(t)) for t in self._release_track_objects(str(release_id))]

    def enrich(self, meta: TrackMeta) -> TrackMeta:
        """Ergänzt Album-Artist, Tracknummer und Trackanzahl aus dem Release."""
        if meta.enriched or not meta.release_id:
            return meta
        rel = self.release(meta.release_id, meta.release)
        tracks = self._release_track_objects(meta.release_id)
        ids = [str(t["id"]) for t in tracks]
        artists = [a["name"] for a in rel.get("artists") or []]
        if not artists:  # gesperrtes Release ohne Artist-Angabe: aus den Tracks zusammensetzen
            for t in tracks:
                artists += [a["name"] for a in t.get("artists") or [] if a["name"] not in artists]
        album_artist = VARIOUS_ARTISTS if len(artists) > VARIOUS_LIMIT else ", ".join(artists)
        restricted = meta.release_id in self._restricted
        if str(meta.id) not in ids:
            # Track fehlt in der Shop-Trackliste (aus dem Verkauf genommen): Seite lädt nicht,
            # Nummer aus der vollständigen, nach ID sortierten Liste schätzen
            full = sorted(self._paged("/catalog/tracks/", {"release_id": meta.release_id}), key=lambda t: int(t["id"]))
            if str(meta.id) in [str(t["id"]) for t in full]:
                ids, restricted = [str(t["id"]) for t in full], True
        number = ids.index(str(meta.id)) + 1 if str(meta.id) in ids else None
        return replace(
            meta,
            album_artist=album_artist,
            track_number=number,
            track_total=(len(ids) if restricted else rel.get("track_count")) or len(ids) or None,
            catalog_number=meta.catalog_number or rel.get("catalog_number") or "",
            restricted=restricted,
            enriched=True,
        )

    def download_image(self, dynamic_uri: str, size: int = 600) -> bytes | None:
        if not dynamic_uri:
            return None
        url = dynamic_uri.replace("{w}", str(size)).replace("{h}", str(size))
        try:
            r = self.session.get(url, timeout=self.timeout)
        except requests.RequestException:
            return None
        return r.content if r.status_code == 200 else None
