from pathlib import Path

from musiclib.models import LibraryItem, LocalTrack
from musiclib.organizer import DEFAULT_TEMPLATE, assign_targets, sanitize, target_path, validate_template


def test_sanitize():
    assert sanitize('AC/DC: "Live"?') == "AC_DC_ _Live__"
    assert sanitize("Song ()") == "Song"
    assert sanitize("  .hidden. ") == "hidden"
    assert sanitize("") == "_"


def test_template_with_beatport(bp_track, tmp_path):
    item = LibraryItem(LocalTrack(tmp_path / "x.flac"), selected=bp_track)
    assert target_path(item, tmp_path, DEFAULT_TEMPLATE) == tmp_path / "House" / "Daft Punk - One More Time (Extended Mix).mp3"
    assert target_path(item, tmp_path, "{genre}/{key}/{bpm} - {title}") == tmp_path / "House" / "10B" / "123 - One More Time.mp3"
    assert target_path(item, tmp_path, "{key} {title}", key_format="musical").name == "D Major One More Time.mp3"


def test_slash_in_genre_becomes_dash(bp_track, tmp_path):
    bp_track.genre = "Techno (Peak Time / Driving)"
    item = LibraryItem(LocalTrack(tmp_path / "x.mp3"), selected=bp_track)
    assert target_path(item, tmp_path, "{genre}/{title}").parent.name == "Techno (Peak Time - Driving)"


def test_dots_in_name_are_kept(tmp_path):
    item = LibraryItem(LocalTrack(tmp_path / "x.mp3", artist="Fred again..", title="Marea"))
    assert target_path(item, tmp_path, "{artist} - {title}").name == "Fred again.. - Marea.mp3"


def test_template_without_match_and_without_mix(tmp_path):
    item = LibraryItem(LocalTrack(tmp_path / "x.mp3", artist="A", title="Song"))
    assert target_path(item, tmp_path, DEFAULT_TEMPLATE) == tmp_path / "_Unbekannt" / "A - Song.mp3"


def test_validate_template():
    assert validate_template(DEFAULT_TEMPLATE) is None
    assert "foo" in validate_template("{foo}")
    assert validate_template("{genre") is not None


def test_collisions_and_disabled(tmp_path):
    items = [LibraryItem(LocalTrack(tmp_path / f"{i}.mp3", artist="A", title="Song")) for i in range(3)]
    items[2].enabled = False
    (tmp_path / "_Unbekannt").mkdir()
    (tmp_path / "_Unbekannt" / "A - Song.mp3").write_text("existing")
    assign_targets(items, tmp_path, DEFAULT_TEMPLATE)
    assert [i.target.name if i.target else None for i in items] == ["A - Song (2).mp3", "A - Song (3).mp3", None]
