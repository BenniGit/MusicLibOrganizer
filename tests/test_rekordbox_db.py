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
