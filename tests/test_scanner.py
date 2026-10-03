import pytest

from musiclib.scanner import parse_filename, read_track, scan, split_mix
from tests.conftest import make_audio, needs_ffmpeg


@pytest.mark.parametrize("stem,expected", [
    ("Daft Punk - One More Time", ("Daft Punk", "One More Time", "")),
    ("01 - Daft Punk - One More Time (Extended Mix)", ("Daft Punk", "One More Time", "Extended Mix")),
    ("03. Artist_A - Song [Dub]", ("Artist A", "Song", "Dub")),
    ("Artist - Song (Remastered 2020)", ("Artist", "Song (Remastered 2020)", "")),
    ("NurTitel", ("", "NurTitel", "")),
])
def test_parse_filename(stem, expected):
    assert parse_filename(stem) == expected


def test_split_mix():
    assert split_mix("Song (Someone Remix)") == ("Song", "Someone Remix")
    assert split_mix("Song") == ("Song", "")


@needs_ffmpeg
def test_read_tags_mp3_and_flac(tmp_path):
    make_audio(tmp_path / "a.mp3", artist="Artist A", title="Song (Original Mix)", TSRC="DEXX12345678")
    make_audio(tmp_path / "sub" / "b.flac", artist="Artist B", title="Other")
    make_audio(tmp_path / "Artist C - Third (Club Mix).wav")
    (tmp_path / "notes.txt").write_text("x")

    tracks = {t.path.name: t for t in scan(tmp_path)}
    assert set(tracks) == {"a.mp3", "b.flac", "Artist C - Third (Club Mix).wav"}

    a = tracks["a.mp3"]
    assert (a.artist, a.title, a.mix, a.isrc) == ("Artist A", "Song", "Original Mix", "DEXX12345678")
    assert not a.needs_conversion
    b = tracks["b.flac"]
    assert (b.artist, b.title) == ("Artist B", "Other") and b.needs_conversion
    c = tracks["Artist C - Third (Club Mix).wav"]
    assert (c.artist, c.title, c.mix) == ("Artist C", "Third", "Club Mix")
    assert c.duration_s == pytest.approx(1.0, abs=0.1)
