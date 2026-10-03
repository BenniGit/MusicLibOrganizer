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

    result = apply_item(item, ApplyOptions(move=False, backup_dir=tmp_path / "bak"), cover_loader=lambda meta: COVER)
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
    opts = ApplyOptions(move=True, tag=TagOptions(key_format="musical", mix_in_title=False, embed_cover=False), backup_dir=tmp_path / "bak")
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


@needs_ffmpeg
def test_clean_removes_old_tags_keeps_selected_and_backs_up(tmp_path, bp_track):
    import json

    from mutagen.id3 import COMM, ID3 as _ID3, TCOM

    src = make_audio(tmp_path / "in" / "x.mp3", artist="Old Artist", title="Old Title")
    t = _ID3(src)
    t.add(COMM(encoding=3, lang="eng", desc="", text=["mein Kommentar"]))
    t.add(TCOM(encoding=3, text=["Komponist"]))
    t.save(src)

    bp_track.album_artist, bp_track.track_number, bp_track.track_total = "Daft Punk", 2, 3
    local = read_track(src)
    assert ("COMM::eng", "Kommentar", "mein Kommentar") in local.raw_tags
    assert local.old["artist"] == "Old Artist"

    item = LibraryItem(local, selected=bp_track, keep_tags={"TCOM"})
    assign_targets([item], tmp_path / "out", "{title}")
    apply_item(item, ApplyOptions(backup_dir=tmp_path / "bak"))

    tags = ID3(tmp_path / "out" / "One More Time.mp3")
    assert "COMM::eng" not in tags                      # alter Kommentar entfernt
    assert str(tags["TCOM"]) == "Komponist"             # ausdrücklich behalten
    assert "TSSE" not in tags                           # Encoder-Tag von ffmpeg entfernt
    assert str(tags["TPE2"]) == "Daft Punk"
    assert str(tags["TRCK"]) == "2/3"
    record = json.loads((next((tmp_path / "bak").glob("*.jsonl"))).read_text().splitlines()[0])
    assert record["source"] == str(src)
    assert {"key": "COMM::eng", "label": "Kommentar", "value": "mein Kommentar"} in record["tags"]


@needs_ffmpeg
def test_flac_tags_can_be_kept(tmp_path, bp_track):
    src = make_audio(tmp_path / "x.flac", artist="A", title="B", composer="Someone")
    item = LibraryItem(read_track(src), selected=bp_track, keep_tags={"composer"})
    assign_targets([item], tmp_path / "out", "{title}")
    apply_item(item, ApplyOptions(backup_dir=tmp_path / "bak"))
    tags = ID3(tmp_path / "out" / "One More Time.mp3")
    assert str(tags["TXXX:COMPOSER"]) == "Someone"
    assert "TPE1" in tags and str(tags["TPE1"]) == "Daft Punk"
