from mutagen.id3 import ID3
from mutagen.mp3 import MP3

from musiclib.models import LibraryItem
from musiclib.organizer import assign_targets
from musiclib.pipeline import ApplyOptions, apply_item
from musiclib.scanner import read_track
from musiclib.tagger import TagOptions
from tests.conftest import make_audio, needs_ffmpeg

COVER = b"\xff\xd8\xff\xe0fakejpeg"


@needs_ffmpeg
def test_flac_is_converted_to_320_and_tagged(tmp_path, bp_track):
    bp_track.image_url = "https://example/{w}x{h}.jpg"
    src = make_audio(tmp_path / "in" / "x.flac", seconds=2, artist="Old", title="Old")
    item = LibraryItem(read_track(src), selected=bp_track)
    assign_targets([item], tmp_path / "out", "{genre}/{artist} - {title} ({mix})")

    result = apply_item(item, ApplyOptions(move=False), cover_loader=lambda url: COVER)
    assert "konvertiert" in result and "getaggt" in result
    assert src.exists()  # Kopiermodus: Original bleibt

    out = tmp_path / "out" / "House" / "Daft Punk - One More Time (Extended Mix).mp3"
    mp3 = MP3(out)
    assert mp3.info.bitrate // 1000 == 320
    tags = ID3(out)
    assert str(tags["TIT2"]) == "One More Time (Extended Mix)"
    assert str(tags["TPE1"]) == "Daft Punk"
    assert str(tags["TKEY"]) == "10B"
    assert str(tags["TBPM"]) == "123"
    assert str(tags["TCON"]) == "House"
    assert str(tags["TPUB"]) == "Daft Life"
    assert str(tags["TSRC"]) == "GBDUW0000051"
    assert str(tags["TXXX:BEATPORT_TRACK_ID"]) == "123"
    assert tags.getall("APIC")[0].data == COVER


@needs_ffmpeg
def test_mp3_move_mode_and_musical_key(tmp_path, bp_track):
    src = make_audio(tmp_path / "in" / "x.mp3")
    item = LibraryItem(read_track(src), selected=bp_track)
    assign_targets([item], tmp_path / "out", "{title}")
    opts = ApplyOptions(move=True, tag=TagOptions(key_format="musical", mix_in_title=False, embed_cover=False))
    assert apply_item(item, opts) == "verschoben, getaggt"
    assert not src.exists()
    tags = ID3(tmp_path / "out" / "One More Time.mp3")
    assert str(tags["TKEY"]) == "D Major"
    assert str(tags["TIT2"]) == "One More Time"
    assert MP3(tmp_path / "out" / "One More Time.mp3").info.bitrate // 1000 == 127  # MP3 wird nicht neu kodiert


@needs_ffmpeg
def test_wav_move_mode_deletes_original_and_unmatched_keeps_tags(tmp_path):
    src = make_audio(tmp_path / "in" / "A - Song.wav")
    item = LibraryItem(read_track(src))
    assign_targets([item], tmp_path / "out", "{genre}/{artist} - {title}")
    assert apply_item(item, ApplyOptions(move=True)) == "konvertiert, Original gelöscht"
    assert not src.exists()
    assert MP3(tmp_path / "out" / "_Unbekannt" / "A - Song.mp3").info.bitrate // 1000 == 320
