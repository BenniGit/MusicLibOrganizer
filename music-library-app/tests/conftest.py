"""Testdateien mit absichtlich „verschmutzten“ Tags, wie sie in der echten Sammlung vorkommen."""

from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from mutagen import apev2
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC, COMM, GEOB, ID3, PCNT, POPM, PRIV, TALB, TBPM, TCON, TIT2, TKEY, TPE1, TXXX, UFID, WXXX,
)

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg nicht installiert")

# Kleinstes gültiges PNG (1×1 px) als Cover.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def make_audio(path: Path) -> Path:
    """Eine Sekunde Sinus ohne jegliche Tags."""
    codec = ["-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "0", "-write_id3v1", "0"] \
        if path.suffix == ".mp3" else ["-c:a", "flac"]
    subprocess.run(
        [FFMPEG, "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-map_metadata", "-1", "-fflags", "+bitexact", *codec, str(path)],
        check=True,
    )
    return path


def audio_md5(path: Path) -> str:
    """Prüfsumme der dekodierten Audiodaten, unabhängig von Tags."""
    out = subprocess.run(
        [FFMPEG, "-loglevel", "error", "-i", str(path), "-map", "0:a", "-f", "md5", "-"],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def append_id3v1(path: Path) -> None:
    tag = b"TAG" + b"Old Title".ljust(30, b"\0") + b"Old Artist".ljust(30, b"\0") \
        + b"\0" * 30 + b"2019" + b"Purchased at Beatport.com".ljust(30, b"\0") + b"\xff"
    with open(path, "ab") as f:
        f.write(tag)


def dirty_mp3(path: Path) -> None:
    tags = ID3()
    tags.add(TIT2(encoding=3, text="Wilkie (Original Mix)"))
    tags.add(TPE1(encoding=3, text="Roman Flügel"))
    tags.add(TALB(encoding=3, text="Wilkie EP"))
    tags.add(TCON(encoding=3, text="Techno (Peak Time / Driving)"))
    tags.add(TBPM(encoding=3, text="124"))
    tags.add(TKEY(encoding=3, text="8A"))
    tags.add(COMM(encoding=3, lang="eng", desc="", text="Purchased at Beatport.com"))
    tags.add(COMM(encoding=3, lang="eng", desc="ID3v1 Comment", text="spacey and silly"))
    tags.add(TXXX(encoding=3, desc="TRAKTOR4", text="cue data"))
    tags.add(TXXX(encoding=3, desc="replaygain_track_gain", text="-8.2 dB"))
    tags.add(TXXX(encoding=3, desc="MusicBrainz Track Id", text="abc"))
    tags.add(WXXX(encoding=3, desc="SOURCE", url="https://example.com/track"))
    tags.add(UFID(owner="http://musicbrainz.org", data=b"1234"))
    tags.add(PRIV(owner="TRAKTOR4", data=b"\x00" * 64))
    tags.add(GEOB(encoding=0, mime="application/octet-stream", filename="", desc="Serato Markers2",
                  data=b"\x01\x01" + b"\x00" * 32))
    tags.add(PCNT(count=12))
    tags.add(POPM(email="traktor@native-instruments.de", rating=196, count=3))
    tags.add(APIC(encoding=3, mime="image/png", type=3, desc="Cover", data=PNG))
    tags.save(path, v2_version=3)
    ape = apev2.APEv2()
    ape["REPLAYGAIN_TRACK_GAIN"] = "-8.2 dB"
    ape["mp3gain_minmax"] = "100,200"
    ape.save(path)
    append_id3v1(path)


def dirty_flac(path: Path) -> None:
    flac = FLAC(path)
    flac["TITLE"] = "Wilkie (Original Mix)"
    flac["ARTIST"] = "Roman Flügel"
    flac["COMMENT"] = "tunnel stuff"
    flac["REPLAYGAIN_TRACK_GAIN"] = "-8.2 dB"
    flac["MUSICBRAINZ_TRACKID"] = "abc"
    pic = Picture()
    pic.type, pic.mime, pic.data = 3, "image/png", PNG
    flac.add_picture(pic)
    flac.save()
    # APPLICATION-Block (Typ 2) von Hand anhängen: ID "riff" + Nutzdaten.
    _insert_flac_application_block(path, b"riff" + b"\x00" * 12)
    # Fehlerhafte Programme schreiben ID3 auch in FLAC-Dateien.
    _prepend_id3v2(path)
    append_id3v1(path)


def _insert_flac_application_block(path: Path, payload: bytes) -> None:
    data = path.read_bytes()
    assert data[:4] == b"fLaC"
    pos = 4
    # erster Block ist STREAMINFO; neuen Block direkt dahinter einfügen
    header = data[pos]
    size = int.from_bytes(data[pos + 1:pos + 4], "big")
    end = pos + 4 + size
    if header & 0x80:  # STREAMINFO war letzter Block -> Flag verschieben
        data = data[:pos] + bytes([header & 0x7F]) + data[pos + 1:]
        block = bytes([0x80 | 2]) + len(payload).to_bytes(3, "big") + payload
    else:
        block = bytes([2]) + len(payload).to_bytes(3, "big") + payload
    path.write_bytes(data[:end] + block + data[end:])


def _prepend_id3v2(path: Path) -> None:
    frame_body = b"\x03" + "Old Title".encode()
    frame = b"TIT2" + struct.pack(">I", len(frame_body)) + b"\x00\x00" + frame_body
    size = len(frame)
    syncsafe = bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])
    path.write_bytes(b"ID3\x03\x00\x00" + syncsafe + frame + path.read_bytes())


@pytest.fixture
def dirty_files(tmp_path: Path) -> dict[str, Path]:
    """Gibt {"mp3": ..., "flac": ...} zurück."""
    lib = tmp_path / "LibOrganized" / "Main"
    lib.mkdir(parents=True)
    files = {}
    for ext, dirty in (("mp3", dirty_mp3), ("flac", dirty_flac)):
        p = make_audio(lib / f"Roman Flügel - Wilkie.{ext}")
        dirty(p)
        files[ext] = p
    return files
