import shutil
import unicodedata
from pathlib import Path

import pytest
from mutagen.id3 import ID3

from musiclib import audit, unify
from musiclib.journal import Journal
from tests.conftest import make_audio, needs_ffmpeg
from tests.test_audit import tagged


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(unify, "data_dir", lambda: tmp_path / "data")
    base = make_audio(tmp_path / "src" / "base.mp3")
    root = tmp_path / "LibOrganized"

    def add(rel, artist, albumartist, label, genre="Techno"):
        return tagged(root / rel, base, artist, "T", "R", albumartist, label, genre, "2020", "1/1")

    files = {
        "omar1": add("Omar S/2020 - R [FXHE]/01 - Omar S - T.mp3", "Omar S", "Omar S", "FXHE"),
        "omar2": add("Omar S/2021 - Q [FXHE]/01 - Omar S - T.mp3", "Omar S", "Omar S", "FXHE"),
        "omar3": add("Omar-S/2019 - P [FXHE]/01 - Omar-S - T.mp3", "Omar-S", "Omar-S", "FXHE"),
        "k7a": add("A/2020 - R [!K7 Records]/01 - A - T.mp3", "A", "A", "!K7 Records"),
        "k7b": add("B/2020 - R [K7 Records]/01 - B, Omar-S - T.mp3", "B, Omar-S", "B", "K7 Records"),
        "k7c": add("C/2020 - R [!K7 Records]/01 - C - T.mp3", "C", "C", "!K7 Records"),
        "nol": add("D/2020 - R [Not On Label]/01 - D - T.mp3", "D", "D", "Not On Label (D Self-released)"),
        "xx1": add("The XX/2020 - R [L]/01 - The XX - T.mp3", "The XX", "The XX", "L"),
        "xx2": add("The XX/2021 - S [L]/01 - The xx - T.mp3", "The xx", "The xx", "L"),
        "xx3": add("The xx2/2021 - S [L]/01 - The xx - T.mp3", "The xx", "The xx", "L"),
        "pop": add("E/2020 - R [L]/01 - E - T.mp3", "E", "E", "L", genre="Dance-pop"),
        "pop2": add("F/2020 - R [L]/01 - F - T.mp3", "F", "F", "L", genre="Dance / Pop"),
        "pop3": add("G/2020 - R [L]/01 - G - T.mp3", "G", "G", "L", genre="Dance / Pop"),
    }
    return root, files


def choose(rules):
    for r in rules:
        if "Omar S" in r.spellings:
            r.target = "Omar S"
        if "The xx" in r.spellings:
            r.target = "The xx"
    return rules


@needs_ffmpeg
def test_find_rules_and_plan(lib):
    root, files = lib
    rules = {(r.field, r.target): r for r in choose(unify.find_rules(audit.collect(root)))}
    assert rules[("artist", "Omar S")].spellings == {"Omar S": 2, "Omar-S": 2}
    assert ("label", "!K7 Records") in rules
    assert rules[("label", "Self-Released")].spellings == {"Not On Label (D Self-released)": 1}
    assert ("genre", "Dance / Pop") in rules

    changes = {c.path: c for c in unify.plan(root, audit.collect(root), list(rules.values()))}
    c = changes[files["omar3"]]
    assert c.new_path == root / "Omar S/2019 - P [FXHE]/01 - Omar S - T.mp3"
    assert changes[files["k7b"]].new_path == root / "B/2020 - R [!K7 Records]/01 - B, Omar S - T.mp3"
    assert changes[files["nol"]].new_path == root / "D/2020 - R [Self-Released]/01 - D - T.mp3"
    assert not changes[files["pop"]].moves and changes[files["pop"]].tags == {"genre": ("Dance-pop", "Dance / Pop")}
    assert files["omar1"] not in changes


@needs_ffmpeg
def test_apply_renames_tags_and_journals(lib, tmp_path):
    root, files = lib
    rules = choose(unify.find_rules(audit.collect(root)))
    j = Journal(tmp_path / "j.sqlite")
    ok, problems, log = unify.apply(root, unify.plan(root, audit.collect(root), rules), j)
    assert problems == [] and ok > 0 and log.exists()

    new = root / "Omar S/2019 - P [FXHE]/01 - Omar S - T.mp3"
    assert new.exists() and not (root / "Omar-S").exists()
    assert str(ID3(new)["TPE1"]) == "Omar S" and str(ID3(new)["TPE2"]) == "Omar S"
    assert str(ID3(root / "D/2020 - R [Self-Released]/01 - D - T.mp3")["TPUB"]) == "Self-Released"
    # Ordner nur in Groß-/Kleinschreibung anders: umbenannt, auch unveränderte Dateien darin im Journal
    assert (root / "The xx/2020 - R [L]/01 - The xx - T.mp3").exists() and not (root / "The XX").exists()
    targets = {m.src: m.dst for m in j.all()}
    assert targets[str(files["omar3"])] == str(new)
    assert targets[str(files["xx2"])] == str(root / "The xx/2021 - S [L]/01 - The xx - T.mp3")
    assert targets[str(files["xx1"])] == str(root / "The xx/2020 - R [L]/01 - The xx - T.mp3")
    assert files["omar1"].exists()  # unverändert


@needs_ffmpeg
def test_rekordbox_follows_renamed_files(lib, tmp_path, monkeypatch):
    pytest.importorskip("pyrekordbox")
    from musiclib import rekordbox_db as rbdb
    from tests.rb_fixture import make_db

    monkeypatch.setattr(rbdb, "rekordbox_running", lambda: False)
    root, files = lib
    db_path = make_db(tmp_path, [{"ID": "1", "FolderPath": str(files["omar3"]), "Title": "T", "Rating": 5},
                                 {"ID": "2", "FolderPath": str(files["xx1"]), "Title": "T", "Rating": 3}])
    j = Journal(tmp_path / "j.sqlite")
    j.record(Path("/old/Library/omar.mp3"), files["omar3"])  # war schon einmal umgezogen
    unify.apply(root, unify.plan(root, audit.collect(root), choose(unify.find_rules(audit.collect(root)))), j)
    db = rbdb.open_db(db_path)
    steps = rbdb.plan(db, j)
    switched = {s.content_id: s.new for s in steps if s.action == rbdb.SWITCH}
    assert switched["1"] == str(root / "Omar S/2019 - P [FXHE]/01 - Omar S - T.mp3")
    assert "2" in switched
    rbdb.apply(db, steps, j)
    assert db.get_content(ID="1").Rating == 5 and rbdb.verify(db, steps) == []
    db.close()


@needs_ffmpeg
def test_original_mix_is_removed_from_title_and_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(unify, "data_dir", lambda: tmp_path / "data")
    base = make_audio(tmp_path / "src" / "base.mp3")
    root = tmp_path / "Lib"
    orig = tagged(root / "A/2020 - R [L]/01 - A - Song (Original Mix).mp3", base, "A", "Song (Original Mix)",
                  "R", "A", "L", "Techno", "2020", "1/2")
    ext = tagged(root / "A/2020 - R [L]/02 - A - Other (Extended Mix).mp3", base, "A", "Other (Extended Mix)",
                 "R", "A", "L", "Techno", "2020", "2/2")
    rules = unify.find_rules(audit.collect(root))
    (rule,) = [r for r in rules if r.field == "mix"]
    assert rule.spellings == {"Original Mix": 1} and rule.target == unify.REMOVE
    changes = unify.plan(root, audit.collect(root), rules)
    assert [c.path for c in changes] == [orig]
    j = Journal(tmp_path / "j.sqlite")
    ok, problems, _ = unify.apply(root, changes, j)
    new = root / "A/2020 - R [L]/01 - A - Song.mp3"
    assert problems == [] and new.exists() and ext.exists()
    tags = ID3(new)
    assert str(tags["TIT2"]) == "Song" and str(tags["TXXX:MIX"]) == "Original Mix"
    assert {m.src: m.dst for m in j.all()}[str(orig)] == str(new)


def test_new_tracks_without_original_mix(tmp_path, bp_track):
    from musiclib.models import LibraryItem, LocalTrack
    from musiclib.organizer import target_path
    from musiclib.settings import DEFAULT_TEMPLATE
    from musiclib.tagger import format_title

    bp_track.mix = "Original Mix"
    bp_track.track_number = 1
    assert format_title(bp_track, True, hide_original_mix=True) == "One More Time"
    assert format_title(bp_track, True) == "One More Time (Original Mix)"
    item = LibraryItem(LocalTrack(tmp_path / "x.mp3"), selected=bp_track)
    assert target_path(item, tmp_path, DEFAULT_TEMPLATE, hide_original_mix=True).name == "01 - Daft Punk - One More Time.mp3"
    bp_track.mix = "Extended Mix"
    assert format_title(bp_track, True, hide_original_mix=True) == "One More Time (Extended Mix)"
