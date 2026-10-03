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

    @property
    def needs_conversion(self) -> bool:
        return self.path.suffix.lower() in LOSSLESS_EXTENSIONS

    @property
    def format(self) -> str:
        return self.path.suffix.lower().lstrip(".")


@dataclass
class BeatportTrack:
    """Die für uns relevanten Felder eines Beatport-Tracks."""

    id: int
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

    @property
    def artist(self) -> str:
        return ", ".join(self.artists)

    @property
    def display(self) -> str:
        mix = f" ({self.mix})" if self.mix else ""
        return f"{self.artist} - {self.name}{mix}"

    @classmethod
    def from_api(cls, d: dict) -> "BeatportTrack":
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
        )


class MatchStatus(str, Enum):
    PENDING = "offen"
    MATCHED = "gefunden"
    UNCERTAIN = "unsicher"
    NOT_FOUND = "nicht gefunden"
    ERROR = "Fehler"
    DONE = "erledigt"


@dataclass
class Candidate:
    track: BeatportTrack
    score: float


@dataclass
class LibraryItem:
    """Ein Eintrag in der Arbeitsliste: lokale Datei + Beatport-Ergebnis + Ziel."""

    local: LocalTrack
    status: MatchStatus = MatchStatus.PENDING
    candidates: list[Candidate] = field(default_factory=list)
    selected: BeatportTrack | None = None
    score: float = 0.0
    target: Path | None = None
    enabled: bool = True
    message: str = ""
