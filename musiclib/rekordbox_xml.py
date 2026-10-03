"""Liest die Rekordbox-Bibliothek aus einem XML-Export (Datei → Bibliothek exportieren → XML-Format)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit


@dataclass
class RbTrack:
    track_id: str
    path: Path
    name: str = ""
    artist: str = ""
    genre: str = ""
    bpm: float | None = None
    stars: int = 0  # 0–5
    playlists: list[str] = field(default_factory=list)


def location_to_path(location: str) -> Path:
    """'file://localhost/Users/ben/Music/a%20b.mp3' -> /Users/ben/Music/a b.mp3 (Windows: C:/…)."""
    path = unquote(urlsplit(location).path)
    if re.match(r"^/[A-Za-z]:/", path):  # Windows-Laufwerk
        path = path[1:]
    return Path(path)


def rating_to_stars(rating: str | int | None) -> int:
    """Rekordbox speichert 0, 51, 102, 153, 204, 255 für 0–5 Sterne."""
    try:
        return max(0, min(5, round(int(rating or 0) / 51)))
    except ValueError:
        return 0


def _walk_playlists(node: ET.Element, prefix: str, out: dict[str, list[str]]) -> None:
    for child in node.findall("NODE"):
        name = child.get("Name", "")
        full = f"{prefix}/{name}" if prefix else name
        if child.get("Type") == "1":  # Playlist
            out[full] = [t.get("Key", "") for t in child.findall("TRACK")]
        else:  # Ordner
            _walk_playlists(child, full, out)


def load(xml_path: Path) -> tuple[dict[str, RbTrack], dict[str, list[str]]]:
    """-> (Tracks nach TrackID, Playlists: Pfad 'Ordner/Playlist' -> TrackIDs)."""
    root = ET.parse(xml_path).getroot()
    tracks: dict[str, RbTrack] = {}
    for t in root.iter("TRACK"):
        if t.get("Location") is None:  # Einträge in Playlists haben nur 'Key'
            continue
        try:
            bpm = float(t.get("AverageBpm") or 0) or None
        except ValueError:
            bpm = None
        tid = t.get("TrackID", "")
        tracks[tid] = RbTrack(
            track_id=tid, path=location_to_path(t.get("Location", "")), name=t.get("Name", ""),
            artist=t.get("Artist", ""), genre=t.get("Genre", ""), bpm=bpm, stars=rating_to_stars(t.get("Rating")),
        )
    playlists: dict[str, list[str]] = {}
    pl_root = root.find("PLAYLISTS")
    if pl_root is not None:
        for top in pl_root.findall("NODE"):  # Wurzelknoten "ROOT"
            _walk_playlists(top, "", playlists)
    for name, ids in playlists.items():
        for tid in ids:
            if tid in tracks:
                tracks[tid].playlists.append(name)
    return tracks, playlists
