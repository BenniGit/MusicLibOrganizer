"""Minimaler Client für die Beatport-API v4.

Anmeldung läuft über Benutzername/Passwort (wie auf beatport.com) und den
OAuth-Authorization-Code-Flow mit der öffentlichen Client-ID der API-Docs.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from .models import BeatportTrack

API = "https://api.beatport.com/v4"
REDIRECT_URI = f"{API}/auth/o/post-message/"
DEFAULT_TOKEN_CACHE = Path.home() / ".cache" / "musiclib" / "beatport_token.json"


class BeatportError(RuntimeError):
    pass


class BeatportClient:
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
            self.token_cache.parent.mkdir(parents=True, exist_ok=True)
            self.token_cache.write_text(json.dumps(tok))
            try:
                self.token_cache.chmod(0o600)
            except OSError:
                pass

    def _load_cached_token(self) -> dict | None:
        if not self.token_cache or not self.token_cache.exists():
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
            r = self.session.get(f"{API}{path}", params=params, headers=headers, timeout=self.timeout)
            if r.status_code == 401 and attempt == 0:
                self._token = None
                if self.token_cache and self.token_cache.exists():
                    self.token_cache.unlink()
                continue
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if r.status_code != 200:
                raise BeatportError(f"GET {path} -> {r.status_code}: {r.text[:200]}")
            return r.json()
        raise BeatportError(f"GET {path}: zu viele Wiederholungen")

    def search_tracks(self, query: str, per_page: int = 10) -> list[BeatportTrack]:
        data = self._get("/catalog/search/", {"q": query, "type": "tracks", "per_page": per_page})
        return [BeatportTrack.from_api(t) for t in data.get("tracks", [])]

    def tracks_by_isrc(self, isrc: str) -> list[BeatportTrack]:
        data = self._get("/catalog/tracks/", {"isrc": isrc, "per_page": 25})
        return [BeatportTrack.from_api(t) for t in data.get("results", [])]

    def download_image(self, dynamic_uri: str, size: int = 600) -> bytes | None:
        if not dynamic_uri:
            return None
        url = dynamic_uri.replace("{w}", str(size)).replace("{h}", str(size))
        try:
            r = self.session.get(url, timeout=self.timeout)
        except requests.RequestException:
            return None
        return r.content if r.status_code == 200 else None
