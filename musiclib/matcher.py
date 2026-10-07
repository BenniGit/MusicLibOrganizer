"""Ordnet lokale Tracks Beatport-Tracks zu und bewertet die Treffer."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import TrackMeta, Candidate, LibraryItem, LocalTrack, MatchStatus

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


def canonical_mix(mix: str) -> str:
    """'' / 'Original' / 'Original Mix' -> 'original'; 'Extended Mix' -> 'extended'."""
    m = normalize(mix)
    if m.endswith(" mix"):
        m = m[:-4]
    return m or "original"


def _mix_sim(local: str, remote: str) -> float:
    a, b = canonical_mix(local), canonical_mix(remote)
    if a == b:
        return 1.0
    if not local.strip():
        return 0.7  # lokal unbekannt: anderer Mix ist möglich, aber unwahrscheinlicher
    return SequenceMatcher(None, a, b).ratio()


def score(local: LocalTrack, remote: TrackMeta) -> float:
    if local.isrc and remote.isrc and local.isrc.upper() == remote.isrc.upper():
        base = 0.95
        return min(1.0, base + 0.05 * _mix_sim(local.mix, remote.mix))
    s = 0.45 * _sim(local.title, remote.name) + 0.35 * _artist_sim(local.artist, remote.artists) + 0.2 * _mix_sim(local.mix, remote.mix)
    # Andere Version (z. B. Extended vs. Radio Edit, oder lokal ohne Mix-Angabe vs. Remix) -> nie "sicher"
    if canonical_mix(local.mix) != canonical_mix(remote.mix):
        s = min(s, 0.8)
    if local.duration_s and remote.length_ms:
        diff = abs(local.duration_s - remote.length_ms / 1000)
        if diff > 10:
            s -= min(0.2, diff / 300)
    return max(0.0, min(1.0, s))


def build_query(local: LocalTrack) -> str:
    artist = _FEAT_RE.sub("", local.artist)
    parts = [artist, local.title]
    if local.mix and canonical_mix(local.mix) != "original":
        parts.append(local.mix)
    return " ".join(" ".join(parts).split())


PREFERRED_SOURCE = "Beatport"


def rank(local: LocalTrack, tracks: list[TrackMeta], match_threshold: float = MATCH_THRESHOLD) -> list[Candidate]:
    """Sortiert nach Bewertung. Sichere Beatport-Treffer stehen immer vor anderen Quellen."""
    seen = set()
    out = []
    for t in tracks:
        if t.key in seen:
            continue
        seen.add(t.key)
        out.append(Candidate(t, score(local, t)))
    # Bei gleicher Bewertung das früheste Release (meist das Original statt Compilation) bevorzugen
    out.sort(key=lambda c: (
        0 if c.track.source == PREFERRED_SOURCE and c.score >= match_threshold else 1,
        -round(c.score, 3),
        c.track.release_date or "9999",
    ))
    return out


def enrich(meta: TrackMeta, sources) -> TrackMeta:
    """Lädt Release-Details (Tracknummer, Album-Artist) über die passende Quelle nach."""
    if meta.enriched:
        return meta
    for src in sources if isinstance(sources, (list, tuple)) else [sources]:
        if getattr(src, "name", None) == meta.source and hasattr(src, "enrich"):
            try:
                return src.enrich(meta)
            except Exception:
                return meta
    return meta


def match_item(item: LibraryItem, sources, match_threshold: float = MATCH_THRESHOLD,
               uncertain_threshold: float = UNCERTAIN_THRESHOLD) -> None:
    """Fragt die Quellen der Reihe nach ab, bis ein sicherer Treffer gefunden ist.

    Jede Quelle braucht ein Attribut ``name`` und eine Methode ``search(local) -> list[TrackMeta]``.
    """
    if not isinstance(sources, (list, tuple)):
        sources = [sources]
    local = item.local
    found: list[TrackMeta] = []
    errors: list[str] = []
    for src in sources:
        try:
            found += src.search(local)
        except Exception as e:  # Netzwerk-/API-Fehler pro Quelle abfangen
            errors.append(f"{getattr(src, 'name', src)}: {e}")
            continue
        # Sicherer Treffer (bei Beatport als erster Quelle) -> weitere Quellen nicht nötig
        if found and rank(local, found, match_threshold)[0].score >= match_threshold:
            break

    item.candidates = rank(local, found, match_threshold)[:15]
    item.message = "; ".join(errors)
    if not item.candidates:
        item.status = MatchStatus.ERROR if errors else MatchStatus.NOT_FOUND
        item.selected = None
        item.score = 0.0
        return
    best = item.candidates[0]
    item.score = best.score
    if best.score >= match_threshold:
        item.status = MatchStatus.MATCHED
        item.selected = best.track
    elif best.score >= uncertain_threshold:
        item.status = MatchStatus.UNCERTAIN
        item.selected = best.track
    else:
        item.status = MatchStatus.NOT_FOUND
        item.selected = None
    if item.selected is not None:
        item.selected = enrich(item.selected, sources)
        if item.selected.restricted:
            note = "Beatport-Seite in deinem Land nicht verfügbar – Tracknummer geschätzt, bitte prüfen"
            item.message = "; ".join(m for m in (item.message, note) if m)
