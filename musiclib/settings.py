"""App-Einstellungen, Ordner-Vorlagen und Pflichtfeld-Prüfung (unabhängig von der GUI)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, replace

from .models import TrackMeta

# Name -> Vorlage. "/" erzeugt Unterordner.
TEMPLATE_PRESETS: dict[str, str] = {
    "Album-Artist / Release (empfohlen)": "{albumartist}/{album} ({year})/{track} - {artist} - {title} ({mix})",
    "Genre / Album-Artist / Release": "{genre}/{albumartist}/{album} ({year})/{track} - {artist} - {title} ({mix})",
    "Label / Release": "{label}/[{catno}] {albumartist} - {album}/{track} - {artist} - {title} ({mix})",
    "Genre (ein Ordner pro Genre)": "{genre}/{artist} - {title} ({mix})",
    "Import-Monat / Genre": "{added}/{genre}/{artist} - {title} ({mix})",
    "Flach (alles in einem Ordner)": "{artist} - {title} ({mix})",
}
DEFAULT_TEMPLATE = TEMPLATE_PRESETS["Album-Artist / Release (empfohlen)"]

REQUIRED_FIELD_CHOICES: dict[str, str] = {
    "artist": "Artist",
    "title": "Titel",
    "albumartist": "Album-Artist",
    "track": "Tracknummer",
    "genre": "Genre",
    "label": "Label",
    "album": "Release / Album",
    "year": "Jahr",
    "bpm": "BPM",
    "key": "Key",
    "cover": "Cover",
}
DEFAULT_REQUIRED = ["artist", "title", "albumartist", "track", "album", "genre", "label", "year"]


@dataclass
class AppSettings:
    template: str = DEFAULT_TEMPLATE
    key_format: str = "camelot"  # "camelot" | "musical"
    mix_in_title: bool = True
    embed_cover: bool = True
    move: bool = False
    clean_tags: bool = True
    required_fields: list[str] = field(default_factory=lambda: list(DEFAULT_REQUIRED))
    label_fallback: str = "Self-Released"
    match_threshold: float = 0.85
    auto_threshold: float = 1.0
    use_discogs: bool = True
    use_bandcamp: bool = True
    discogs_token: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str | None) -> "AppSettings":
        try:
            data = json.loads(s or "{}")
        except ValueError:
            data = {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def effective_meta(meta: TrackMeta, settings: AppSettings) -> TrackMeta:
    """Wendet Ersatzwerte an (z. B. 'Self-Released', wenn kein Label bekannt ist)."""
    if not meta.label.strip() and settings.label_fallback.strip():
        return replace(meta, label=settings.label_fallback.strip())
    return meta


def field_value(meta: TrackMeta, name: str) -> str:
    return {
        "artist": meta.artist,
        "title": meta.name,
        "albumartist": meta.effective_album_artist,
        "track": str(meta.track_number or ""),
        "genre": meta.genre,
        "label": meta.label,
        "album": meta.release,
        "year": meta.year,
        "bpm": str(meta.bpm or ""),
        "key": meta.key_camelot or meta.key_name,
        "cover": meta.image_url,
    }.get(name, "")


def missing_fields(meta: TrackMeta | None, settings: AppSettings) -> list[str]:
    """Gibt die Anzeigenamen der fehlenden Pflichtfelder zurück."""
    if meta is None:
        return [REQUIRED_FIELD_CHOICES[f] for f in settings.required_fields if f in REQUIRED_FIELD_CHOICES]
    meta = effective_meta(meta, settings)
    return [REQUIRED_FIELD_CHOICES[f] for f in settings.required_fields
            if f in REQUIRED_FIELD_CHOICES and not field_value(meta, f).strip()]
