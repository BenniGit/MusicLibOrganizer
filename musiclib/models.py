"""Datenmodelle, die zwischen Scanner, Matcher, Tagger und GUI geteilt werden."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

LOSSLESS_EXTENSIONS = {".flac", ".wav", ".aiff", ".aif"}
SUPPORTED_EXTENSIONS = {".mp3"} | LOSSLESS_EXTENSIONS


@dataclass
class LocalTrack:
    """Eine Audiodatei aus der lokalen Bibliothek mit ihren vorhandenen Tags."""

    path: Path
    artist: str = ""
    title: str = ""
    mix: str = ""
    album: str = ""
    isrc: str = ""
    duration_s: float | None = None
    # Vorhandene Tags der Datei: Feldname -> Wert (für "alten Wert übernehmen")
    old: dict[str, str] = field(default_factory=dict)
    # Alle vorhandenen Tags roh: (Schlüssel, Bezeichnung, Wert als Text)
    raw_tags: list[tuple[str, str, str]] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)  # #Tags aus dem bisherigen Kommentar

    @property
    def needs_conversion(self) -> bool:
        return self.path.suffix.lower() in LOSSLESS_EXTENSIONS

    @property
    def format(self) -> str:
        return self.path.suffix.lower().lstrip(".")


@dataclass
class TrackMeta:
    """Metadaten eines Tracks aus einer Quelle (Beatport, Discogs, Bandcamp oder manuell)."""

    id: str | int
    name: str
    mix: str
    artists: list[str]
    remixers: list[str] = field(default_factory=list)
    release: str = ""
    label: str = ""
    catalog_number: str = ""
    genre: str = ""
    sub_genre: str = ""
    bpm: int | None = None
    key_name: str = ""
    key_camelot: str = ""
    isrc: str = ""
    release_date: str = ""
    length_ms: int | None = None
    image_url: str = ""
    source: str = "Beatport"
    url: str = ""
    edited: bool = False
    album_artist: str = ""
    track_number: int | None = None
    track_total: int | None = None
    disc_number: int | None = None
    release_id: str = ""
    enriched: bool = False  # Release-Details (Tracknummer, Album-Artist) geladen

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, str(self.id))

    @property
    def year(self) -> str:
        return self.release_date[:4]

    @property
    def artist(self) -> str:
        return ", ".join(self.artists)

    @property
    def effective_album_artist(self) -> str:
        return self.album_artist or self.artist

    @property
    def display(self) -> str:
        mix = f" ({self.mix})" if self.mix else ""
        return f"{self.artist} - {self.name}{mix}"

    @classmethod
    def from_api(cls, d: dict) -> "TrackMeta":
        """Erzeugt die Metadaten aus einem Track-Objekt der Beatport-API v4."""
        release = d.get("release") or {}
        key = d.get("key") or {}
        camelot = ""
        if key.get("camelot_number") and key.get("camelot_letter"):
            camelot = f"{key['camelot_number']}{key['camelot_letter']}"
        image = (release.get("image") or {}).get("dynamic_uri") or ""
        return cls(
            id=d["id"],
            name=d.get("name") or "",
            mix=d.get("mix_name") or "",
            artists=[a["name"] for a in d.get("artists") or []],
            remixers=[a["name"] for a in d.get("remixers") or []],
            release=release.get("name") or "",
            label=(release.get("label") or {}).get("name") or "",
            catalog_number=d.get("catalog_number") or "",
            genre=(d.get("genre") or {}).get("name") or "",
            sub_genre=(d.get("sub_genre") or {}).get("name") or "",
            bpm=d.get("bpm"),
            key_name=key.get("name") or "",
            key_camelot=camelot,
            isrc=d.get("isrc") or "",
            release_date=d.get("new_release_date") or d.get("publish_date") or "",
            length_ms=d.get("length_ms"),
            image_url=image,
            source="Beatport",
            url=f"https://www.beatport.com/track/{d.get('slug') or '-'}/{d['id']}",
            release_id=str(release.get("id") or ""),
        )


BeatportTrack = TrackMeta  # Rückwärtskompatibler Name


class MatchStatus(str, Enum):
    PENDING = "offen"
    MATCHED = "gefunden"
    UNCERTAIN = "unsicher"
    NOT_FOUND = "nicht gefunden"
    ERROR = "Fehler"
    MANUAL = "manuell"
    DONE = "erledigt"


@dataclass
class Candidate:
    track: TrackMeta
    score: float


@dataclass
class LibraryItem:
    """Ein Eintrag in der Arbeitsliste: lokale Datei + Beatport-Ergebnis + Ziel."""

    local: LocalTrack
    status: MatchStatus = MatchStatus.PENDING
    candidates: list[Candidate] = field(default_factory=list)
    selected: TrackMeta | None = None
    score: float = 0.0
    target: Path | None = None
    enabled: bool = True
    message: str = ""
    keep_tags: set[str] = field(default_factory=set)  # vorhandene Tags, die erhalten bleiben sollen
    tags: list[str] | None = None  # eigene #Tags; None = unverändert aus der Datei übernehmen
