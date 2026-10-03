"""Konvertiert verlustfreie Formate (FLAC/WAV/AIFF) per ffmpeg zu MP3 320 kbit/s."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class ConversionError(RuntimeError):
    pass


# Eine aus dem Finder gestartete Mac-App kennt den PATH der Shell nicht – typische Orte zusätzlich prüfen
_EXTRA_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "/usr/bin")


def find_ffmpeg() -> str | None:
    candidates = [os.environ.get("MUSICLIB_FFMPEG")]
    if getattr(sys, "frozen", False):  # mitgelieferte Kopie neben der App
        candidates.append(str(Path(sys.executable).parent / "ffmpeg"))
    candidates.append(shutil.which("ffmpeg"))
    candidates += [str(Path(d) / "ffmpeg") for d in _EXTRA_DIRS]
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def ffmpeg_path() -> str:
    exe = find_ffmpeg()
    if not exe:
        raise ConversionError("ffmpeg wurde nicht gefunden. Installation am Mac:  brew install ffmpeg  "
                              "(oder den Pfad in der Umgebungsvariable MUSICLIB_FFMPEG angeben).")
    return exe


def to_mp3(src: Path, dst: Path, bitrate: str = "320k") -> Path:
    """Schreibt src als MP3 (CBR) nach dst. Bestehende Tags werden mitgenommen."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    cmd = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src),
        "-map", "0:a:0",
        "-map_metadata", "0",
        "-codec:a", "libmp3lame", "-b:a", bitrate,
        "-id3v2_version", "4",
        "-f", "mp3", str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise ConversionError(f"ffmpeg-Fehler bei {src.name}: {proc.stderr.strip()[:300]}")
    tmp.replace(dst)
    return dst
