import struct
from pathlib import Path

import pytest

from musiclib import anlz_path


def tag(typ: bytes, header_rest: bytes, body: bytes) -> bytes:
    len_header = 12 + len(header_rest)
    return typ + struct.pack(">II", len_header, len_header + len(body)) + header_rest + body


def ppth(path: str) -> bytes:
    payload = path.encode("utf-16-be") + b"\x00\x00"
    return tag(b"PPTH", struct.pack(">I", len(payload)), payload)


def make_anlz(file: Path, path: str) -> bytes:
    # Erweitertes Beatgrid wie von Rekordbox 7: u1 = 0x02000002 (pyrekordbox erwartet 0x01000002)
    pqt2 = tag(b"PQT2", b"\x00" * 4 + struct.pack(">I", 0x02000002) + b"\x00" * 36, b"\x01\x02" * 8)
    pcob = tag(b"PCOB", b"\x00" * 12, b"cue-daten")
    body = ppth(path) + pqt2 + pcob
    header = b"PMAI" + struct.pack(">II", 28, 28 + len(body)) + b"\x00" * 16
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(header + body)
    return pqt2 + pcob


def test_set_path_keeps_everything_else(tmp_path):
    f = tmp_path / "ANLZ0000.2EX"
    rest = make_anlz(f, "/Users/b/Music/Library/A - Song.mp3")
    assert anlz_path.read_path(f) == "/Users/b/Music/Library/A - Song.mp3"

    new = "/Users/b/Music/LibOrganized/Ä/2020 - Song [Label]/01 - Ä - Sehr langer Titel (Extended Mix).mp3"
    assert anlz_path.set_path(f, new)
    data = f.read_bytes()
    assert anlz_path.read_path(f) == new
    assert struct.unpack_from(">I", data, 8)[0] == len(data)   # Datei-Länge stimmt
    assert data.endswith(rest)                                   # Beatgrid + Cues unverändert
    assert not f.with_name(f.name + ".tmp").exists()


def test_pyrekordbox_cannot_read_it_but_we_can(tmp_path):
    pyrekordbox = pytest.importorskip("pyrekordbox")
    f = tmp_path / "ANLZ0000.2EX"
    make_anlz(f, "/old.mp3")
    with pytest.raises(Exception):
        pyrekordbox.AnlzFile.parse_file(f)
    assert anlz_path.set_path(f, "/new.mp3") and anlz_path.read_path(f) == "/new.mp3"


def test_invalid_file_is_left_untouched(tmp_path):
    f = tmp_path / "ANLZ0000.DAT"
    f.write_bytes(b"PMAI" + struct.pack(">II", 28, 999) + b"\x00" * 16 + b"PPTH\x00\x00\x00\x10\xff\xff\xff\xff")
    before = f.read_bytes()
    with pytest.raises(anlz_path.AnlzError):
        anlz_path.set_path(f, "/new.mp3")
    assert f.read_bytes() == before
