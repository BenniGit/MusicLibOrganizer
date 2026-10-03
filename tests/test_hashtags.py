from pathlib import Path

from mutagen.id3 import COMM, ID3

from musiclib import hashtags
from musiclib.models import LibraryItem, LocalTrack, TrackMeta
from musiclib.organizer import assign_targets
from musiclib.pipeline import ApplyOptions, apply_item
from musiclib.scanner import read_track
from musiclib.settings import AppSettings, effective_tags
from tests.conftest import make_audio, needs_ffmpeg


def test_token_and_parse():
    assert hashtags.token("Peak Time") == "peaktime"
    assert hashtags.token("Düster") == "duster"
    assert hashtags.token("Warm-up") == "warmup"
    assert hashtags.parse("gekauft 2018 #PeakTime #vocal, #vocal") == ["peaktime", "vocal"]


def test_format_and_strip():
    assert hashtags.format_comment(["peaktime", "vocal"]) == "#peaktime #vocal"
    assert hashtags.format_comment(["dark"], keep_text="gekauft 2018 #old") == "gekauft 2018 #dark"
    assert hashtags.format_comment([]) == ""


def test_groups_text_roundtrip_and_order():
    groups = hashtags.parse_groups_text("Situation: Warm-up, Peak Time\n\nStimmung: Dark\nLoose")
    assert groups == {"Situation": ["Warm-up", "Peak Time"], "Stimmung": ["Dark"], "Tags": ["Loose"]}
    assert hashtags.parse_groups_text(hashtags.groups_to_text(groups)) == groups
    assert hashtags.order(["zzz", "dark", "warmup"], groups) == ["warmup", "dark", "zzz"]


def test_effective_tags_with_auto_tags(tmp_path):
    s = AppSettings(unofficial_label="Bootleg", auto_tag_subgenre=True)
    meta = TrackMeta(id=1, name="x", mix="", artists=["a"], label="Bootleg", sub_genre="Tech Trance")
    item = LibraryItem(LocalTrack(tmp_path / "x.mp3", hashtags=["vocal"]), selected=meta)
    assert effective_tags(item, s) == ["vocal", "bootleg", "techtrance"]
    item.tags = ["peaktime"]  # vom Nutzer gesetzt -> ersetzt die Tags aus der Datei
    assert effective_tags(item, AppSettings(auto_tag_unofficial=False)) == ["peaktime"]


@needs_ffmpeg
def test_tags_written_to_comment_and_read_back(tmp_path, bp_track):
    src = make_audio(tmp_path / "in" / "x.mp3")
    t = ID3(src)
    t.add(COMM(encoding=3, lang="eng", desc="", text=["alter Kommentar #vocal"]))
    t.save(src)
    local = read_track(src)
    assert local.hashtags == ["vocal"]

    item = LibraryItem(local, selected=bp_track)
    assign_targets([item], tmp_path / "out", "{title}")
    apply_item(item, ApplyOptions(backup_dir=tmp_path / "bak"), tags=["peaktime", "vocal"])
    out = tmp_path / "out" / "One More Time.mp3"
    comments = ID3(out).getall("COMM")
    assert [str(c) for c in comments] == ["#peaktime #vocal"]  # alter Kommentartext entfernt (nicht behalten)
    assert read_track(out).hashtags == ["peaktime", "vocal"]


@needs_ffmpeg
def test_kept_comment_text_is_combined_with_tags(tmp_path, bp_track):
    src = make_audio(tmp_path / "in" / "x.mp3")
    t = ID3(src)
    t.add(COMM(encoding=3, lang="eng", desc="", text=["gekauft 2018 #old"]))
    t.save(src)
    item = LibraryItem(read_track(src), selected=bp_track, keep_tags={"COMM::eng"})
    assign_targets([item], tmp_path / "out", "{title}")
    apply_item(item, ApplyOptions(backup_dir=tmp_path / "bak"), tags=["dark"])
    assert [str(c) for c in ID3(tmp_path / "out" / "One More Time.mp3").getall("COMM")] == ["gekauft 2018 #dark"]


@needs_ffmpeg
def test_no_tags_means_no_comment(tmp_path, bp_track):
    item = LibraryItem(read_track(make_audio(tmp_path / "in" / "x.mp3")), selected=bp_track)
    assign_targets([item], tmp_path / "out", "{title}")
    apply_item(item, ApplyOptions(backup_dir=tmp_path / "bak"), tags=[])
    assert ID3(tmp_path / "out" / "One More Time.mp3").getall("COMM") == []
