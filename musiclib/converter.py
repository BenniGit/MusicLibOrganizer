"""Konvertiert verlustfreie Formate (FLAC/WAV/AIFF) per ffmpeg zu MP3 320 kbit/s."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class ConversionError(RuntimeError):
    pass


def ffmpeg_path() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise ConversionError("ffmpeg wurde nicht gefunden. Bitte installieren und in den PATH aufnehmen.")
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
