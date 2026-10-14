from mutagen.id3 import COMM, ID3

from musiclib import mytags
from musiclib.models import LibraryItem, LocalTrack, TrackMeta
from musiclib.organizer import assign_targets
from musiclib.pipeline import ApplyOptions, apply_item
from musiclib.scanner import read_track
from musiclib.settings import AppSettings, my_tags
from tests.conftest import make_audio, needs_ffmpeg


def test_add_block_like_rekordbox():
    assert mytags.add("", ["Bootleg"]) == "/* Bootleg */"
    assert mytags.add("gekauft 2018", ["Bootleg"]) == "/* Bootleg */ gekauft 2018"


def test_add_merges_into_existing_rekordbox_block():
    comment = "/* Peak Time / Vocal */ gekauft 2018"
    assert mytags.parse(comment) == ["Peak Time", "Vocal"]
    assert mytags.add(comment, ["Bootleg"]) == "/* Peak Time / Vocal / Bootleg */ gekauft 2018"
    assert mytags.add("/* bootleg */", ["Bootleg"]) == "/* bootleg */"  # keine Duplikate


def test_my_tags_only_for_unofficial_tracks(tmp_path):
    local = LocalTrack(tmp_path / "x.mp3")
    bootleg = TrackMeta(id=1, name="x", mix="", artists=["a"], label="Bootleg")
    official = TrackMeta(id=2, name="x", mix="", artists=["a"], label="Toolroom")
    s = AppSettings(unofficial_label="Bootleg")
    assert my_tags(LibraryItem(local, selected=bootleg), s) == ["Bootleg"]
    assert my_tags(LibraryItem(local, selected=official), s) == []
    assert my_tags(LibraryItem(local), s) == []
    assert my_tags(LibraryItem(local, selected=bootleg), AppSettings(auto_tag_unofficial=False)) == []


def test_old_settings_with_removed_tag_options_still_load():
    s = AppSettings.from_json('{"tag_groups": {"Situation": ["Peak Time"]}, "auto_tag_subgenre": true, '
                              '"auto_tag_unofficial": false}')
    assert s.auto_tag_unofficial is False


@needs_ffmpeg
def test_bootleg_written_to_comment(tmp_path, bp_track):
    item = LibraryItem(read_track(make_audio(tmp_path / "in" / "x.mp3")), selected=bp_track)
    assign_targets([item], tmp_path / "out", "{title}")
    apply_item(item, ApplyOptions(backup_dir=tmp_path / "bak"), my_tags=["Bootleg"])
    assert [str(c) for c in ID3(tmp_path / "out" / "One More Time.mp3").getall("COMM")] == ["/* Bootleg */"]


@needs_ffmpeg
def test_kept_comment_stays_next_to_bootleg(tmp_path, bp_track):
    src = make_audio(tmp_path / "in" / "x.mp3")
    t = ID3(src)
    t.add(COMM(encoding=3, lang="eng", desc="", text=["/* Peak Time */ gekauft 2018"]))
    t.save(src)
    item = LibraryItem(read_track(src), selected=bp_track, keep_tags={"COMM::eng"})
    assign_targets([item], tmp_path / "out", "{title}")
    apply_item(item, ApplyOptions(backup_dir=tmp_path / "bak"), my_tags=["Bootleg"])
    comments = [str(c) for c in ID3(tmp_path / "out" / "One More Time.mp3").getall("COMM")]
    assert comments == ["/* Peak Time / Bootleg */ gekauft 2018"]


@needs_ffmpeg
def test_official_track_gets_no_comment(tmp_path, bp_track):
    item = LibraryItem(read_track(make_audio(tmp_path / "in" / "x.mp3")), selected=bp_track)
    assign_targets([item], tmp_path / "out", "{title}")
    apply_item(item, ApplyOptions(backup_dir=tmp_path / "bak"), my_tags=[])
    assert ID3(tmp_path / "out" / "One More Time.mp3").getall("COMM") == []
