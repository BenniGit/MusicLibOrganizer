from pathlib import Path

import pytest
from mutagen.id3 import APIC, ID3

from musiclib import covers
from musiclib.models import LibraryItem, LocalTrack, MatchStatus, TrackMeta
from musiclib.organizer import assign_targets
from musiclib.pipeline import ApplyOptions, apply_item
from musiclib.release_edit import apply_release_edit, common_values, parse_changes, track_order
from musiclib.scanner import read_track
from musiclib.tagger import TagOptions
from tests.conftest import make_audio, needs_ffmpeg

JPEG = b"\xff\xd8\xff\xe0" + b"jpegdata"
PNG = b"\x89PNG\r\n\x1a\n" + b"pngdata"


def meta(name, n=None, label="L", genre="Tech House"):
    return TrackMeta(id=name, name=name, mix="", artists=["A"], release="EP", label=label, genre=genre,
                     track_number=n, track_total=3, source="Beatport", image_url="https://img/{w}x{h}.jpg")


def test_common_values_and_parsing():
    c = common_values([meta("a", label="X"), meta("b", label="Y")])
    assert c["release"] == "EP" and c["label"] is None and c["track_total"] == "3"
    assert parse_changes({"label": " New ", "track_total": "4", "disc_number": ""}) == {
        "label": "New", "track_total": 4, "disc_number": None}
    with pytest.raises(ValueError):
        parse_changes({"track_total": "vier"})


def test_apply_release_edit_changes_only_given_fields_and_renumbers():
    items = [LibraryItem(LocalTrack(Path(f"/x/{n}.mp3")), selected=meta(n, i), status=MatchStatus.MATCHED)
             for n, i in (("b", 2), ("a", 1), ("c", None))]
    apply_release_edit(items, {"label": "Neues Label", "release_date": "2021"}, renumber=True)
    assert [it.selected.label for it in items] == ["Neues Label"] * 3
    assert [it.selected.genre for it in items] == ["Tech House"] * 3      # unverändert
    assert [(it.selected.track_number, it.selected.track_total) for it in items] == [(2, 3), (1, 3), (3, 3)]
    assert all(it.status == MatchStatus.MANUAL and it.selected.edited for it in items)
    assert [it.selected.name for it in track_order(items)] == ["a", "b", "c"]


def test_unmatched_tracks_start_from_their_old_tags():
    local = LocalTrack(Path("/x/01 - A - Song.mp3"), artist="A", title="Song", old={"genre": "House"})
    it = LibraryItem(local)
    apply_release_edit([it], {"release": "Mein Release"})
    assert (it.selected.release, it.selected.genre, it.selected.name, it.selected.source) == (
        "Mein Release", "House", "Song", "Manuell")


def test_cover_checks(tmp_path):
    assert covers.image_mime(JPEG) == "image/jpeg" and covers.image_mime(PNG) == "image/png"
    (tmp_path / "x.gif").write_bytes(b"GIF89a")
    with pytest.raises(covers.CoverError):
        covers.load_file(tmp_path / "x.gif")


@needs_ffmpeg
def test_cover_priority_own_then_source_then_existing(tmp_path, bp_track):
    src = make_audio(tmp_path / "in" / "x.mp3")
    t = ID3(src)
    t.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=JPEG + b"old"))
    t.save(src)
    local = read_track(src)
    assert local.has_cover

    def run(item, name, loader=None):
        assign_targets([item], tmp_path / name, "{title}")
        apply_item(item, ApplyOptions(tag=TagOptions(), backup_dir=tmp_path / "bak"), cover_loader=loader)
        return ID3(item.target).getall("APIC")

    # Quelle ohne Cover -> bisheriges Cover bleibt
    bp_track.image_url = ""
    (apic,) = run(LibraryItem(local, selected=bp_track), "o1")
    assert apic.data == JPEG + b"old"
    # Quelle mit Cover -> Cover der Quelle
    bp_track.image_url = "https://img/{w}x{h}.jpg"
    (apic,) = run(LibraryItem(local, selected=bp_track), "o2", loader=lambda m: JPEG + b"source")
    assert apic.data == JPEG + b"source"
    # Eigenes Cover gewinnt, auch wenn Cover-Einbetten aus ist; PNG wird als PNG markiert
    item = LibraryItem(local, selected=bp_track, cover=PNG)
    assign_targets([item], tmp_path / "o3", "{title}")
    apply_item(item, ApplyOptions(tag=TagOptions(embed_cover=False), backup_dir=tmp_path / "bak"),
               cover_loader=lambda m: JPEG + b"source")
    (apic,) = ID3(item.target).getall("APIC")
    assert (apic.data, apic.mime) == (PNG, "image/png")
