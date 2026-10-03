from __future__ import annotations

import os

import pytest
from mutagen.flac import FLAC
from mutagen.mp3 import MP3

from conftest import append_id3v1, audio_md5, requires_ffmpeg
from musiclib.backup import backup_path, restore
from musiclib.cli import main
from musiclib.reset import inspect, reset

pytestmark = requires_ffmpeg


@pytest.mark.parametrize("ext", ["mp3", "flac"])
def test_dirty_fixture_is_detected(dirty_files, ext):
    inv = inspect(dirty_files[ext])
    assert not inv.is_clean
    assert inv.id3v1
    assert inv.id3v2


def test_inspect_mp3_lists_foreign_frames(dirty_files):
    inv = inspect(dirty_files["mp3"])
    frames = set(inv.id3v2)
    for key in ("TXXX:TRAKTOR4", "PRIV:TRAKTOR4", "GEOB:Serato Markers2", "PCNT",
                "APIC:Cover", "COMM::eng", "UFID:http://musicbrainz.org"):
        assert any(f.startswith(key) for f in frames), key
    assert "REPLAYGAIN_TRACK_GAIN" in inv.ape


def test_inspect_flac_lists_blocks(dirty_files):
    inv = inspect(dirty_files["flac"])
    assert {"TITLE", "COMMENT", "REPLAYGAIN_TRACK_GAIN"} <= set(inv.vorbis)
    assert {"PICTURE", "APPLICATION", "VORBIS_COMMENT"} <= set(inv.flac_blocks)


@pytest.mark.parametrize("ext", ["mp3", "flac"])
def test_reset_removes_everything_and_keeps_audio(dirty_files, ext):
    path = dirty_files[ext]
    md5_before = audio_md5(path)
    os.utime(path, (1_600_000_000, 1_600_000_000))

    reset(path)

    inv = inspect(path)
    assert inv.is_clean, inv.summary()
    assert audio_md5(path) == md5_before
    assert os.stat(path).st_mtime == 1_600_000_000
    assert path.read_bytes()[-128:-125] != b"TAG"


def test_reset_mp3_with_stacked_trailing_tags(dirty_files):
    # ID3v1 / APE / ID3v1 / ID3v1 am Dateiende, wie nach mehreren Tag-Programmen
    path = dirty_files["mp3"]
    append_id3v1(path)
    md5_before = audio_md5(path)
    reset(path)
    assert inspect(path).is_clean
    assert audio_md5(path) == md5_before


def test_reset_flac_stays_valid(dirty_files):
    path = dirty_files["flac"]
    reset(path)
    data = path.read_bytes()
    assert data[:4] == b"fLaC"
    flac = FLAC(path)
    assert flac.tags is None or len(flac.tags) == 0
    assert flac.pictures == []
    assert flac.info.length == pytest.approx(1.0, abs=0.05)


def test_reset_mp3_stays_valid(dirty_files):
    path = dirty_files["mp3"]
    reset(path)
    mp3 = MP3(path)
    assert mp3.tags is None
    assert mp3.info.length == pytest.approx(1.0, abs=0.1)
    assert mp3.info.bitrate >= 300_000


def test_reset_is_idempotent(dirty_files):
    path = dirty_files["mp3"]
    reset(path)
    data = path.read_bytes()
    reset(path)
    assert path.read_bytes() == data


def test_cli_preview_changes_nothing(dirty_files, tmp_path, capsys):
    before = {p: p.read_bytes() for p in dirty_files.values()}
    lib = dirty_files["mp3"].parent.parent
    assert main(["reset", str(lib)]) == 0
    assert {p: p.read_bytes() for p in dirty_files.values()} == before
    out = capsys.readouterr().out
    assert "2 würden zurückgesetzt" in out
    assert "TXXX:TRAKTOR4" in out


def test_cli_apply_requires_backup_dir(dirty_files):
    assert main(["reset", str(dirty_files["mp3"]), "--apply"]) == 2


def test_cli_apply_backs_up_then_resets_and_restores(dirty_files, tmp_path):
    lib = dirty_files["mp3"].parent.parent
    backups = tmp_path / "backup"
    originals = {p: p.read_bytes() for p in dirty_files.values()}

    assert main(["reset", str(lib), "--backup-dir", str(backups), "--apply"]) == 0

    for p, original in originals.items():
        assert inspect(p).is_clean
        assert backup_path(p, backups).read_bytes() == original

    # zweiter Lauf überschreibt die Sicherung nicht mit der bereinigten Datei
    assert main(["reset", str(lib), "--backup-dir", str(backups), "--apply"]) == 0
    assert backup_path(dirty_files["mp3"], backups).read_bytes() == originals[dirty_files["mp3"]]

    # Restore funktioniert auch für eine einzeln übergebene Datei
    assert restore(dirty_files["flac"], backups)
    assert dirty_files["flac"].read_bytes() == originals[dirty_files["flac"]]
