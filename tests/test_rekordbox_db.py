import shutil
import unicodedata
from pathlib import Path

import pytest

pytest.importorskip("pyrekordbox")

from musiclib import rekordbox_db as rbdb  # noqa: E402
from musiclib.journal import Journal  # noqa: E402
from musiclib.rekordbox_cli import main  # noqa: E402
from tests.rb_fixture import make_db  # noqa: E402


def touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"audio")
    return p


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(rbdb, "rekordbox_running", lambda: False)
    lib, new = tmp_path / "Library", tmp_path / "LibOrganized"
    umlaut_old = touch(lib / "Main" / unicodedata.normalize("NFD", "Künstler - Lied.mp3"))
    a_old, a_new = touch(lib / "Main" / "A - Song.mp3"), touch(new / "A" / "2020 - Song [L]" / "01 - A - Song.mp3")
    f_old, f_new = touch(lib / "Main" / "F - Flac.flac"), touch(new / "F" / "01 - F - Flac.mp3")
    gone_old = touch(lib / "Main" / "G - Gone.mp3")
    done_new = touch(new / "D" / "01 - D - Done.mp3")
    u_new = touch(new / "Künstler" / "01 - Künstler - Lied.mp3")
    db = make_db(tmp_path, [
        {"ID": "1", "FolderPath": str(a_old), "Title": "Song", "Rating": 4, "StockDate": "2023-01-20", "ColorID": "3"},
        {"ID": "2", "FolderPath": str(f_old), "Title": "Flac", "Rating": 2},
        {"ID": "3", "FolderPath": str(gone_old), "Title": "Gone", "Rating": 1},
        {"ID": "4", "FolderPath": str(done_new), "Title": "Done", "Rating": 5},
        {"ID": "5", "FolderPath": str(umlaut_old), "Title": "Lied", "Rating": 3},
    ])
    j = Journal(tmp_path / "umzug.sqlite")
    j.record(a_old, a_new)
    j.record(f_old, f_new)
    j.record(gone_old, new / "G" / "nicht-da.mp3")
    j.record(lib / "Main" / "D - Done.mp3", done_new)
    j.record(lib / "Main" / "Nicht in RB.mp3", touch(new / "X.mp3"))
    j.record(Path(unicodedata.normalize("NFC", str(umlaut_old))), u_new)
    j.close()
    return tmp_path, db, a_old, a_new, u_new


def test_plan(setup):
    tmp, db_path, *_ = setup
    db = rbdb.open_db(db_path)
    steps = {Path(s.old).name: s.action for s in rbdb.plan(db, Journal(tmp / "umzug.sqlite"))}
    db.close()
    assert steps == {"A - Song.mp3": rbdb.SWITCH, "F - Flac.flac": rbdb.TYPE_CHANGED, "G - Gone.mp3": rbdb.TARGET_MISSING,
                     "D - Done.mp3": rbdb.ALREADY, "Nicht in RB.mp3": rbdb.NOT_IN_RB,
                     unicodedata.normalize("NFC", "Künstler - Lied.mp3"): rbdb.SWITCH}


def test_switch_keeps_rating_and_can_be_restored(setup, capsys):
    tmp, db_path, a_old, a_new, u_new = setup
    args = ["--db", str(db_path), "--journal", str(tmp / "umzug.sqlite")]
    assert main(args + ["umstellen"]) == 0
    assert "Probelauf" in capsys.readouterr().out
    db = rbdb.open_db(db_path)
    assert db.get_content(ID="1").FolderPath == str(a_old)  # Probelauf ändert nichts
    db.close()

    assert main(args + ["umstellen", "--anwenden", "--sicherungen", str(tmp / "bak")]) == 0
    out = capsys.readouterr().out
    assert "2 Tracks umgestellt" in out and "Alles geprüft" in out
    db = rbdb.open_db(db_path)
    c = db.get_content(ID="1")
    assert (c.FolderPath, c.FileNameL, c.Rating, c.StockDate, c.ColorID) == (
        str(a_new), a_new.name, 4, "2023-01-20", "3")
    assert db.get_content(ID="5").FolderPath == str(u_new)
    assert db.get_content(ID="2").FolderPath.endswith(".flac")  # Formatwechsel bleibt unangetastet
    db.close()
    assert all(m.switched for m in Journal(tmp / "umzug.sqlite").all() if m.src.endswith(("A - Song.mp3", "D - Done.mp3")))

    # Zweiter Lauf: nichts mehr zu tun
    assert main(args + ["umstellen", "--anwenden", "--sicherungen", str(tmp / "bak")]) == 0
    assert "Nichts umzustellen" in capsys.readouterr().out

    # Zurück zur Sicherung
    assert main(args + ["zurueck", "--sicherungen", str(tmp / "bak")]) == 0
    db = rbdb.open_db(db_path)
    assert db.get_content(ID="1").FolderPath == str(a_old)
    db.close()


def test_refuses_while_rekordbox_running(setup, monkeypatch, capsys):
    tmp, db_path, a_old, *_ = setup
    monkeypatch.setattr(rbdb, "rekordbox_running", lambda: True)
    assert main(["--db", str(db_path), "--journal", str(tmp / "umzug.sqlite"), "umstellen", "--anwenden",
                 "--sicherungen", str(tmp / "bak")]) == 1
    assert "Rekordbox läuft" in capsys.readouterr().out
    db = rbdb.open_db(db_path)
    assert db.get_content(ID="1").FolderPath == str(a_old)
    db.close()


def test_journal_roundtrip(tmp_path):
    j = Journal(tmp_path / "j.sqlite")
    j.record(Path("/a/x.mp3"), Path("/b/y.mp3"))
    j.record(Path("/a/x.mp3"), Path("/b/z.mp3"))  # erneut übernommen -> neuestes Ziel
    assert j.target_for(Path("/a/x.mp3")) == "/b/z.mp3" and len(j.all()) == 1
    j.forget(Path("/a/x.mp3"))
    assert j.target_for(Path("/a/x.mp3")) is None


def test_reprocessed_track_is_switched_again(setup, capsys):
    """Übernehmen → umstellen → erneut bearbeiten (neues Ziel) → nochmal umstellen."""
    tmp, db_path, a_old, a_new, _ = setup
    args = ["--db", str(db_path), "--journal", str(tmp / "umzug.sqlite")]
    assert main(args + ["umstellen", "--anwenden", "--sicherungen", str(tmp / "bak")]) == 0

    # Erneut bearbeitet: neues Ziel, alte Version entfernt
    a_newer = touch(tmp / "LibOrganized" / "A" / "2021 - Song [Label]" / "01 - A - Song.mp3")
    a_new.unlink()
    j = Journal(tmp / "umzug.sqlite")
    j.record(a_old, a_newer)
    j.close()
    capsys.readouterr()

    db = rbdb.open_db(db_path)
    step = next(s for s in rbdb.plan(db, Journal(tmp / "umzug.sqlite")) if s.content_id == "1")
    db.close()
    assert (step.action, step.old, step.new) == (rbdb.SWITCH, str(a_new), str(a_newer))

    assert main(args + ["umstellen", "--anwenden", "--sicherungen", str(tmp / "bak2")]) == 0
    assert "1 Tracks umgestellt" in capsys.readouterr().out
    db = rbdb.open_db(db_path)
    c = db.get_content(ID="1")
    assert (c.FolderPath, c.Rating, c.StockDate) == (str(a_newer), 4, "2023-01-20")
    db.close()
    assert next(m for m in Journal(tmp / "umzug.sqlite").all() if m.src == str(a_old)).switched


def test_journal_keeps_previous_targets(tmp_path):
    j = Journal(tmp_path / "j.sqlite")
    j.record(Path("/a/x.mp3"), Path("/b/y.mp3"))
    j.record(Path("/a/x.mp3"), Path("/b/z.mp3"))
    # Datei aus der neuen Library erneut bearbeitet -> ursprünglicher Eintrag wird fortgeschrieben
    assert j.is_target(Path("/b/z.mp3"))
    j.record(Path("/b/z.mp3"), Path("/b/w.mp3"))
    (m,) = j.all()
    assert (m.src, m.dst, m.prev) == ("/a/x.mp3", "/b/w.mp3", ["/b/y.mp3", "/b/z.mp3"])


def test_old_duplicate_with_counter_is_found(tmp_path):
    """Ältere Version legte erneut Bearbeitetes als „… (2).mp3“ ab, Rekordbox zeigt noch auf das erste."""
    first = touch(tmp_path / "new" / "01 - A - Song.mp3")
    second = touch(tmp_path / "new" / "01 - A - Song (2).mp3")
    db_path = make_db(tmp_path, [{"ID": "1", "FolderPath": str(first), "Title": "Song", "Rating": 4}])
    j = Journal(tmp_path / "umzug.sqlite")
    j.record(tmp_path / "old" / "A - Song.mp3", second)
    db = rbdb.open_db(db_path)
    (step,) = rbdb.plan(db, j)
    db.close()
    assert (step.action, step.old, step.new) == (rbdb.SWITCH, str(first), str(second))


def test_switch_rewrites_rekordbox7_analysis_files(setup, capsys):
    """Rekordbox-7-Analysen mit neuem Beatgrid-Format (pyrekordbox kann sie nicht lesen)."""
    from tests.test_anlz_path import make_anlz

    tmp, db_path, a_old, a_new, _ = setup
    db = rbdb.open_db(db_path)
    anlz_dir = db.get_anlz_dir(db.get_content(ID="1"))
    db.close()
    rest = {}
    for suffix in ("DAT", "EXT", "2EX"):
        rest[suffix] = make_anlz(anlz_dir / f"ANLZ0000.{suffix}", str(a_old))
    args = ["--db", str(db_path), "--journal", str(tmp / "umzug.sqlite")]
    assert main(args + ["umstellen", "--anwenden", "--sicherungen", str(tmp / "bak")]) == 0
    assert "Alles geprüft" in capsys.readouterr().out
    from musiclib import anlz_path
    for suffix in ("DAT", "EXT", "2EX"):
        f = anlz_dir / f"ANLZ0000.{suffix}"
        assert anlz_path.read_path(f) == str(a_new) and f.read_bytes().endswith(rest[suffix])

    # Sicherung enthält die alten Analyse-Dateien und spielt sie zurück
    assert main(args + ["zurueck", "--sicherungen", str(tmp / "bak")]) == 0
    assert anlz_path.read_path(anlz_dir / "ANLZ0000.2EX") == str(a_old)


def test_rename_whole_library(setup, capsys):
    """Erst umziehen und umstellen, dann LibOrganized → Library umbenennen."""
    tmp, db_path, a_old, a_new, u_new = setup
    args = ["--db", str(db_path), "--journal", str(tmp / "umzug.sqlite")]
    assert main(args + ["umstellen", "--anwenden", "--sicherungen", str(tmp / "bak")]) == 0
    old_lib = tmp / "Library"
    shutil.rmtree(old_lib)  # alter Ordner gelöscht
    new_root = tmp / "LibOrganized"
    assert main(args + ["umbenennen", str(new_root), str(old_lib), "--sicherungen", str(tmp / "bak2")]) == 0
    out = capsys.readouterr().out
    assert "Alles geprüft" in out
    db = rbdb.open_db(db_path)
    c = db.get_content(ID="1")
    assert c.FolderPath == str(old_lib / a_new.relative_to(new_root)) and c.Rating == 4
    assert db.get_content(ID="5").FolderPath == str(old_lib / u_new.relative_to(new_root))
    db.close()
    assert not new_root.exists()


def test_rename_refuses_when_target_exists(setup, capsys):
    tmp, db_path, *_ = setup
    args = ["--db", str(db_path), "--journal", str(tmp / "umzug.sqlite")]
    assert main(args + ["umbenennen", str(tmp / "LibOrganized"), str(tmp / "Library")]) == 1
    assert "existiert schon" in capsys.readouterr().out
    assert (tmp / "LibOrganized").exists()
