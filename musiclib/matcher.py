"""Ordnet lokale Tracks Beatport-Tracks zu und bewertet die Treffer."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import BeatportTrack, Candidate, LibraryItem, LocalTrack, MatchStatus

MATCH_THRESHOLD = 0.85
UNCERTAIN_THRESHOLD = 0.6

_FEAT_RE = re.compile(r"\b(feat\.?|ft\.?|featuring)\b.*$", re.I)


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _sim(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _artist_sim(local: str, remote: list[str]) -> float:
    local = _FEAT_RE.sub("", local)
    full = _sim(local, ", ".join(remote))
    # Lokal steht oft nur der Hauptartist oder die Reihenfolge ist anders
    tokens_local = set(normalize(local).split())
    tokens_remote = set(normalize(" ".join(remote)).split())
    overlap = len(tokens_local & tokens_remote) / len(tokens_local) if tokens_local else 0.0
    return max(full, overlap)


def _mix_sim(local: str, remote: str) -> float:
    # Kein Mix lokal == "Original Mix" bei Beatport
    if not local and normalize(remote) in ("original mix", ""):
        return 1.0
    if not local:
        return 0.7
    return _sim(local, remote)


def score(local: LocalTrack, remote: BeatportTrack) -> float:
    if local.isrc and remote.isrc and local.isrc.upper() == remote.isrc.upper():
        base = 0.95
        return min(1.0, base + 0.05 * _mix_sim(local.mix, remote.mix))
    s = 0.45 * _sim(local.title, remote.name) + 0.35 * _artist_sim(local.artist, remote.artists) + 0.2 * _mix_sim(local.mix, remote.mix)
    if local.duration_s and remote.length_ms:
        diff = abs(local.duration_s - remote.length_ms / 1000)
        if diff > 10:
            s -= min(0.2, diff / 300)
    return max(0.0, min(1.0, s))


def build_query(local: LocalTrack) -> str:
    artist = _FEAT_RE.sub("", local.artist)
    parts = [artist, local.title]
    if local.mix and normalize(local.mix) != "original mix":
        parts.append(local.mix)
    return " ".join(" ".join(parts).split())


def rank(local: LocalTrack, tracks: list[BeatportTrack]) -> list[Candidate]:
    seen = set()
    out = []
    for t in tracks:
        if t.id in seen:
            continue
        seen.add(t.id)
        out.append(Candidate(t, score(local, t)))
    # Bei gleicher Bewertung das früheste Release (meist das Original statt Compilation) bevorzugen
    out.sort(key=lambda c: (-round(c.score, 3), c.track.release_date or "9999"))
    return out


def match_item(item: LibraryItem, client) -> None:
    """Sucht bei Beatport und setzt Status/Kandidaten des Eintrags."""
    local = item.local
    try:
        found: list[BeatportTrack] = []
        if local.isrc:
            found += client.tracks_by_isrc(local.isrc)
        query = build_query(local)
        if query:
            found += client.search_tracks(query)
        item.candidates = rank(local, found)[:10]
    except Exception as e:  # Netzwerk-/API-Fehler pro Track abfangen
        item.status = MatchStatus.ERROR
        item.message = str(e)
        return

    if not item.candidates:
        item.status = MatchStatus.NOT_FOUND
        item.selected = None
        item.score = 0.0
        return
    best = item.candidates[0]
    item.score = best.score
    if best.score >= MATCH_THRESHOLD:
        item.status = MatchStatus.MATCHED
        item.selected = best.track
    elif best.score >= UNCERTAIN_THRESHOLD:
        item.status = MatchStatus.UNCERTAIN
        item.selected = best.track
    else:
        item.status = MatchStatus.NOT_FOUND
        item.selected = None
