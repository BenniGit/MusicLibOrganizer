import shutil
from pathlib import Path

from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPUB, TRCK

from musiclib import audit
from musiclib.audit_cli import main
from tests.conftest import make_audio, needs_ffmpeg


def tagged(path: Path, base: Path, artist, title, album, albumartist, label, genre, year, track, cover=True,
           bitrate_src: Path | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(bitrate_src or base, path)
    t = ID3()
    for frame, value in ((TPE1, artist), (TIT2, title), (TALB, album), (TPE2, albumartist), (TPUB, label),
                         (TCON, genre), (TDRC, year), (TRCK, track)):
        if value:
            t.add(frame(encoding=3, text=[value]))
    if cover:
        t.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=b"\xff\xd8\xff\xe0x"))
    t.save(path)
    return path


@needs_ffmpeg
def test_report_finds_typical_problems(tmp_path):
    base = make_audio(tmp_path / "src" / "base.mp3")  # 128 kbit/s
    lib = tmp_path / "lib"
    ep = lib / "Fisher" / "2018 - Losing It [Catch & Release]"
    a = tagged(ep / "01 - Fisher - Losing It.mp3", base, "Fisher", "Losing It", "Losing It", "Fisher",
               "Catch & Release", "Tech House", "2018", "1/2")
    tagged(ep / "02 - Fisher - Ya Kidding.mp3", base, "Fisher", "Ya Kidding", "Losing It", "FISHER",
           "Catch & Release", "Tech-House", "2019", "1/2", cover=False)
    tagged(lib / "X" / "2020 - Y [Z]" / "01 - Fisher - Losing It.mp3", base, "FISHER", "Losing It", "Y", "X", "Z",
           "Tech House", "2020", "1/1")
    (lib / "Leer" / "Ordner").mkdir(parents=True)
    (lib / "X" / "notiz.txt").write_text("x")

    r = audit.build_report(lib, audit.collect(lib), rekordbox_paths=[str(a), "/alt/weg.mp3"])
    text = audit.render(r)
    assert "Cover: 1 Dateien ohne Cover" in text
    assert "Unter 320 kbit/s" in text
    assert "Fisher (" in text and "FISHER (" in text           # Schreibvariante Album-Artist/Artist
    assert "Tech House (" in text and "Tech-House (" in text    # Genre-Variante
    assert "mögliche Duplikate" in text and "↔" in text
    assert "Album-Artist uneinheitlich" in text and "Jahr uneinheitlich" in text
    assert "Tracknummer doppelt – 1" in text
    assert "Leere Ordner: 1" in text and "notiz.txt" in text
    assert "Datei fehlt" in text and "/alt/weg.mp3" in text
    assert "nicht in Rekordbox: 2" in text


@needs_ffmpeg
def test_cli_writes_report(tmp_path, capsys):
    base = make_audio(tmp_path / "src" / "base.mp3")
    lib = tmp_path / "lib"
    tagged(lib / "A" / "2020 - B [C]" / "01 - A - B.mp3", base, "A", "B", "B", "A", "C", "House", "2020", "1/1")
    out = tmp_path / "bericht.txt"
    assert main([str(lib), "--bericht", str(out)]) == 0
    assert "Kurzfassung" in out.read_text() and "Bericht gespeichert" in capsys.readouterr().out


@needs_ffmpeg
def test_streaming_sampler_unicode_and_old_library(tmp_path):
    import unicodedata

    base = make_audio(tmp_path / "src" / "base.mp3")
    lib, old = tmp_path / "lib", tmp_path / "old"
    nfc, nfd = "Felix Kröcher", unicodedata.normalize("NFD", "Felix Kröcher")
    a = tagged(lib / "F" / "1" / "01.mp3", base, nfc, "A", "A", nfc, "L", "Techno", "2020", "1/1")
    tagged(lib / "F" / "2" / "01.mp3", base, nfd, "B", "B", nfd, "L", "Techno", "2020", "1/1")
    done = make_audio(old / "done.mp3")
    make_audio(old / "vergessen.mp3")
    rb = [str(a), "soundcloud:tracks:123", "/Users/b/Music/rekordbox/Sampler/X/House1.wav"]
    text = audit.render(audit.build_report(lib, audit.collect(lib), rb, old, migrated={str(done)}))
    assert "unsichtbares Zeichen" in text
    assert "Datei fehlt" not in text and "außerhalb" not in text
    assert "1 Streaming-Einträge" in text and "1 mitgelieferte Sampler-Sounds" in text
    assert "nie in die neue Library übernommen: 1" in text and "vergessen.mp3" in text


def test_clean_text():
    from musiclib.tagger import clean_text

    assert clean_text("Demi ﻿Riquísimo ") == "Demi Riquísimo"
    assert clean_text("Kröcher") == "Kröcher"
