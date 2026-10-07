"""Cover: vorhandenes Cover einer Datei lesen, eigenes Bild laden, Bildformat erkennen."""
from __future__ import annotations

from pathlib import Path

import mutagen
import requests
from mutagen.id3 import ID3

MAX_BYTES = 15 * 1024 * 1024
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


class CoverError(ValueError):
    pass


def image_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def existing_cover(path: Path) -> bytes | None:
    """Das in der Datei eingebettete Cover (MP3: APIC, FLAC: Picture), sonst None."""
    try:
        audio = mutagen.File(path)
    except Exception:
        return None
    if audio is None:
        return None
    pictures = getattr(audio, "pictures", None)  # FLAC
    if pictures:
        front = [p for p in pictures if p.type == 3] or list(pictures)
        return bytes(front[0].data) or None
    tags = audio.tags
    if isinstance(tags, ID3):
        frames = tags.getall("APIC")
        front = [f for f in frames if f.type == 3] or frames
        if front and image_mime(front[0].data):
            return bytes(front[0].data)
    return None


def _check(data: bytes) -> bytes:
    if not data:
        raise CoverError("Leere Datei")
    if len(data) > MAX_BYTES:
        raise CoverError("Bild ist größer als 15 MB")
    if image_mime(data) is None:
        raise CoverError("Nur JPEG- oder PNG-Bilder werden unterstützt")
    return data


def load_file(path: Path) -> bytes:
    return _check(Path(path).read_bytes())


def load_url(url: str, timeout: float = 20) -> bytes:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": BROWSER_UA})
    except requests.RequestException as e:
        raise CoverError(f"Bild konnte nicht geladen werden: {e}") from e
    if r.status_code != 200:
        raise CoverError(f"Bild konnte nicht geladen werden (HTTP {r.status_code})")
    return _check(r.content)
