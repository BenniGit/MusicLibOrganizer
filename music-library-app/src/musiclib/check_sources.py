"""Prüft die Verbindung zu Discogs und Beatport, ohne Zugangsdaten auszugeben.

Zugangsdaten kommen aus Umgebungsvariablen oder dem macOS-Schlüsselbund
(siehe credentials.py): DISCOGS_TOKEN, BEATPORT_USERNAME, BEATPORT_PASSWORD

Beatport hat keinen offiziellen API-Zugang für Privatentwickler. Wie beets-beatport4
nutzen wir die Client-ID der API-Doku-Seite plus den eigenen Login (OAuth-Code-Flow).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import requests

from . import credentials

USER_AGENT = "MusicLibOrganizer/0.1 +https://github.com/BenniGit/MusicLibOrganizer"
TIMEOUT = 15

DISCOGS_API = "https://api.discogs.com"
BEATPORT_API = "https://api.beatport.com/v4"
BEATPORT_REDIRECT = f"{BEATPORT_API}/auth/o/post-message/"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _missing(*names: str) -> list[str]:
    return [n for n in names if not credentials.get(n)]


def check_discogs(session: requests.Session) -> list[Check]:
    if missing := _missing("DISCOGS_TOKEN"):
        return [Check("Discogs Token", False, f"Zugangsdaten fehlen: {', '.join(missing)}")]
    auth = {"Authorization": f"Discogs token={credentials.get('DISCOGS_TOKEN')}"}
    r = session.get(f"{DISCOGS_API}/oauth/identity", headers=auth, timeout=TIMEOUT)
    checks = [Check("Discogs Token", r.ok,
                    f"gültig, Limit {r.headers.get('X-Discogs-Ratelimit', '?')}/min" if r.ok
                    else f"HTTP {r.status_code}: {r.text[:120]}")]
    if r.ok:
        r = session.get(f"{DISCOGS_API}/database/search", headers=auth, timeout=TIMEOUT,
                        params={"artist": "Roman Flügel", "track": "Wilkie", "type": "release"})
        hits = r.json().get("results", []) if r.ok else []
        checks.append(Check("Discogs Suche", r.ok and bool(hits),
                            f"{len(hits)} Treffer, z. B. {hits[0]['title']}" if hits
                            else f"HTTP {r.status_code}"))
    return checks


def beatport_client_id(session: requests.Session) -> str | None:
    """Liest die öffentliche Client-ID aus den Skripten der Beatport-API-Doku."""
    html = session.get(f"{BEATPORT_API}/docs/", timeout=TIMEOUT).text
    for src in re.findall(r'src="(/static/btprt/[^"]+\.js)"', html):
        js = session.get(f"https://api.beatport.com{src}", timeout=TIMEOUT).text
        if m := re.search(r"API_CLIENT_ID:\s*'([^']+)'", js):
            return m.group(1)
    return None


def beatport_token(session: requests.Session, client_id: str) -> tuple[str | None, Check]:
    """Login + OAuth-Code-Flow. Gibt (access_token, Check) zurück."""
    r = session.post(f"{BEATPORT_API}/auth/login/", timeout=TIMEOUT, json={
        "username": credentials.get("BEATPORT_USERNAME"),
        "password": credentials.get("BEATPORT_PASSWORD"),
    })
    if not r.ok:
        return None, Check("Beatport Login", False, f"HTTP {r.status_code}: {r.text[:120]}")
    r = session.get(f"{BEATPORT_API}/auth/o/authorize/", allow_redirects=False, timeout=TIMEOUT,
                    params={"client_id": client_id, "response_type": "code",
                            "redirect_uri": BEATPORT_REDIRECT})
    code = parse_qs(urlparse(r.headers.get("Location", "")).query).get("code", [None])[0]
    if not code:
        return None, Check("Beatport Login", False, f"kein Autorisierungscode (HTTP {r.status_code})")
    r = session.post(f"{BEATPORT_API}/auth/o/token/", timeout=TIMEOUT, data={
        "code": code, "grant_type": "authorization_code",
        "redirect_uri": BEATPORT_REDIRECT, "client_id": client_id,
    })
    if not r.ok:
        return None, Check("Beatport Login", False, f"Token: HTTP {r.status_code}: {r.text[:120]}")
    return r.json()["access_token"], Check("Beatport Login", True, "Token erhalten")


def check_beatport(session: requests.Session) -> list[Check]:
    if missing := _missing("BEATPORT_USERNAME", "BEATPORT_PASSWORD"):
        return [Check("Beatport Login", False, f"Zugangsdaten fehlen: {', '.join(missing)}")]
    client_id = beatport_client_id(session)
    checks = [Check("Beatport Client-ID", bool(client_id),
                    "auf der Doku-Seite gefunden" if client_id else "nicht gefunden")]
    if not client_id:
        return checks
    token, login = beatport_token(session, client_id)
    checks.append(login)
    if token:
        r = session.get(f"{BEATPORT_API}/catalog/search/", timeout=TIMEOUT,
                        headers={"Authorization": f"Bearer {token}"},
                        params={"q": "Roman Flugel Wilkie", "type": "tracks", "per_page": 3})
        tracks = r.json().get("tracks", []) if r.ok else []
        if tracks:
            t = tracks[0]
            key = t.get("key") or {}
            detail = (f"{', '.join(a['name'] for a in t['artists'])} – {t['name']} ({t['mix_name']}), "
                      f"{(t.get('genre') or {}).get('name')}, {t.get('bpm')} BPM, "
                      f"{key.get('camelot_number')}{key.get('camelot_letter')}, ISRC {t.get('isrc')}")
        else:
            detail = f"HTTP {r.status_code}, keine Treffer"
        checks.append(Check("Beatport Suche", bool(tracks), detail))
    return checks


def run(only: str | None = None) -> list[Check]:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    checks: list[Check] = []
    for name, fn in (("discogs", check_discogs), ("beatport", check_beatport)):
        if only in (None, name):
            try:
                checks += fn(session)
            except requests.RequestException as e:
                checks.append(Check(name.capitalize(), False, f"Netzwerkfehler: {e}"))
    return checks
