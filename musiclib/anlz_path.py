"""Dateipfad in Rekordbox-Analyse-Dateien (ANLZ0000.DAT/.EXT/.2EX) ändern.

Wir fassen nur den Pfad-Abschnitt (PPTH) an und kopieren alle anderen Abschnitte (Beatgrid, Cues,
Wellenform …) Byte für Byte. So stören uns neuere Abschnittsformate nicht, die pyrekordbox noch
nicht lesen kann (z. B. das erweiterte Beatgrid PQT2 von Rekordbox 7).

Aufbau: Datei-Header „PMAI“ (Typ, Header-Länge, Datei-Länge, …), danach Abschnitte mit
Typ (4 Bytes), Header-Länge, Abschnitts-Länge; PPTH-Header enthält zusätzlich die Pfadlänge,
der Pfad selbst ist UTF-16-BE mit zwei Null-Bytes am Ende.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

ANLZ_SUFFIXES = (".DAT", ".EXT", ".2EX")


class AnlzError(ValueError):
    pass


def _u32(data: bytes, pos: int) -> int:
    return struct.unpack_from(">I", data, pos)[0]


def _tags(data: bytes):
    """(Typ, Start, Header-Länge, Abschnitts-Länge) für jeden Abschnitt."""
    if data[:4] != b"PMAI" or len(data) < 12:
        raise AnlzError("keine Rekordbox-Analyse-Datei")
    pos = _u32(data, 4)
    while pos < len(data):
        if pos + 12 > len(data):
            raise AnlzError("Abschnitt abgeschnitten")
        len_header, len_tag = _u32(data, pos + 4), _u32(data, pos + 8)
        if len_tag < 12 or len_header > len_tag or pos + len_tag > len(data):
            raise AnlzError("ungültige Abschnittslänge")
        yield data[pos:pos + 4], pos, len_header, len_tag
        pos += len_tag


def read_path(file: Path) -> str | None:
    data = Path(file).read_bytes()
    for typ, pos, len_header, len_tag in _tags(data):
        if typ == b"PPTH":
            raw = data[pos + len_header:pos + len_tag]
            return raw.decode("utf-16-be").rstrip("\x00")
    return None


def set_path(file: Path, new_path: str) -> bool:
    """Schreibt den neuen Pfad. False, wenn die Datei keinen Pfad-Abschnitt hat."""
    file = Path(file)
    data = file.read_bytes()
    for typ, pos, len_header, len_tag in _tags(data):
        if typ != b"PPTH":
            continue
        if len_header < 16:
            raise AnlzError("unbekannter Pfad-Abschnitt")
        payload = new_path.replace("\\", "/").encode("utf-16-be") + b"\x00\x00"
        header = bytearray(data[pos:pos + len_header])
        struct.pack_into(">I", header, 8, len_header + len(payload))   # Abschnitts-Länge
        struct.pack_into(">I", header, len_header - 4, len(payload))   # Pfadlänge
        new = bytearray(data[:pos] + bytes(header) + payload + data[pos + len_tag:])
        struct.pack_into(">I", new, 8, len(new))                        # Datei-Länge im PMAI-Header
        list(_tags(bytes(new)))  # Gegenprobe: Aufbau noch gültig?
        tmp = file.with_name(file.name + ".tmp")
        tmp.write_bytes(bytes(new))
        os.replace(tmp, file)
        return True
    return False


def files_for(anlz_dir: Path, analysis_data_path: str | None) -> list[Path]:
    """Die Analyse-Dateien eines Tracks (ANLZ0000.DAT, .EXT, .2EX)."""
    stem = Path(analysis_data_path).stem if analysis_data_path else "ANLZ0000"
    return sorted(f for f in Path(anlz_dir).glob(stem + ".*") if f.suffix.upper() in ANLZ_SUFFIXES)
