import subprocess
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pytest

from musiclib import energy
from musiclib.energy_cli import main, stars_from_folder_name, stars_matching_distribution
from musiclib.rekordbox_xml import load, location_to_path, rating_to_stars
from tests.conftest import needs_ffmpeg


def make_loop(path: Path, level: int, seconds: int = 50) -> Path:
    """Synthetischer House-Loop: Level 1 = nur Kick/Bass, Level 5 = dichte 16tel-Hats + Clap, schneller."""
    bpm = 118 + 3 * level
    beat = 60 / bpm
    parts = [f"0.8*sin(2*PI*55*t)*exp(-mod(t,{beat})*18)", f"0.25*sin(2*PI*43*t)"]
    if level >= 2:
        div = 2 if level < 4 else 4
        parts.append(f"{0.07 * level}*(random(0)*2-1)*exp(-mod(t,{beat / div})*70)")
    if level >= 3:
        parts.append(f"{0.08 * level}*(random(1)*2-1)*exp(-mod(t+{beat / 2},{beat})*25)")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='{'+'.join(parts)}':s=22050:d={seconds}", "-ac", "1", str(path)], check=True)
    return path


def test_rating_and_location():
    assert [rating_to_stars(r) for r in (0, 51, 102, 153, 204, 255, None, "x")] == [0, 1, 2, 3, 4, 5, 0, 0]
    assert location_to_path("file://localhost/Users/ben/Music/a%20b%26c.mp3") == Path("/Users/ben/Music/a b&c.mp3")
    assert location_to_path("file://localhost/C:/Music/x.mp3").as_posix() == "C:/Music/x.mp3"
    # '#' und '?' im Dateinamen dürfen den Pfad nicht abschneiden
    assert location_to_path("file://localhost/Users/b/Library/#Sampler 1?.mp3") == Path("/Users/b/Library/#Sampler 1?.mp3")
    assert location_to_path("file://localhost/Users/b/Various%20Artists%20Sampler%20%231.mp3").name == "Various Artists Sampler #1.mp3"


def test_stars_from_folder_name():
    assert [stars_from_folder_name(n) for n in ("1", "★3", "Energie 4", "5 Sterne", "2024", "Mix")] == [1, 3, 4, 5, 0, 0]


def test_quantile_and_distribution_mapping():
    scores = np.arange(10, dtype=float)
    assert energy.to_stars_by_quantile(scores).tolist() == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    stars = np.array([1] * 6 + [5] * 4)
    assert stars_matching_distribution(scores, stars).tolist() == [1] * 6 + [5] * 4


def test_ridge_cross_validation_learns_linear_relation():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(60, len(energy.FEATURES)))
    y = np.clip(np.rint(3 + 1.2 * X[:, 0] - 0.8 * X[:, 3]), 1, 5)
    ev = energy.evaluate("x", y, energy.cross_val_predict(X, y))
    assert ev.within_one > 0.9 and ev.spearman > 0.8


def test_spearman():
    assert energy.spearman(np.array([1, 2, 3, 4]), np.array([10, 20, 30, 40])) == pytest.approx(1.0)
    assert energy.spearman(np.array([1, 2, 3, 4]), np.array([4, 3, 2, 1])) == pytest.approx(-1.0)


@needs_ffmpeg
def test_more_percussion_scores_higher(tmp_path):
    low = energy.analyze(str(make_loop(tmp_path / "low.wav", 1)), 50)
    high = energy.analyze(str(make_loop(tmp_path / "high.wav", 5)), 50)
    assert high.hf_flux > low.hf_flux and high.high_ratio > low.high_ratio
    assert 125 < high.bpm < 140 and 115 < low.bpm < 126  # aus dem Audio geschätzt
    X = np.vstack([low.vector(), high.vector()])
    s = energy.unsupervised_scores(X)
    assert s[1] > s[0]


def _xml(tracks, playlists):
    rows = "".join(
        f'<TRACK TrackID="{i}" Name="T{i}" Artist="A" AverageBpm="{bpm}" Rating="{rating}" '
        f'Location="file://localhost{quote(str(p))}"/>' for i, p, rating, bpm in tracks)
    pls = "".join(f'<NODE Type="1" Name="{name}" Entries="{len(ids)}">' + "".join(f'<TRACK Key="{k}"/>' for k in ids)
                  + "</NODE>" for name, ids in playlists.items())
    return (f'<?xml version="1.0" encoding="UTF-8"?><DJ_PLAYLISTS Version="1.0.0"><COLLECTION Entries="{len(tracks)}">'
            f'{rows}</COLLECTION><PLAYLISTS><NODE Type="0" Name="ROOT"><NODE Type="0" Name="Ordner">{pls}</NODE>'
            f'</NODE></PLAYLISTS></DJ_PLAYLISTS>')


def test_load_rekordbox_xml(tmp_path):
    xml = tmp_path / "rb.xml"
    xml.write_text(_xml([(1, Path("/m/a b.mp3"), 204, 126), (2, Path("/m/c.mp3"), 0, 0)], {"Energie": [1]}))
    tracks, pls = load(xml)
    assert pls == {"Ordner/Energie": ["1"]}
    assert tracks["1"].stars == 4 and tracks["1"].bpm == 126 and tracks["1"].path == Path("/m/a b.mp3")
    assert tracks["1"].playlists == ["Ordner/Energie"] and tracks["2"].stars == 0


@needs_ffmpeg
def test_cli_with_rekordbox_xml(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("musiclib.energy_cli.data_dir", lambda: tmp_path / "data")
    rows = []
    for i in range(12):
        level = 1 + i % 5
        p = make_loop(tmp_path / "lib" / f"track {i}.wav", level, 45)
        rows.append((i, p, level * 51, 0))
    xml = tmp_path / "rb.xml"
    xml.write_text(_xml(rows, {"Energie Sets": [r[0] for r in rows]}))
    out = tmp_path / "res.csv"
    assert main(["--xml", str(xml), "--list-playlists"]) == 0
    assert "Ordner/Energie Sets" in capsys.readouterr().out
    assert main(["--xml", str(xml), "--playlist", "energie", "--workers", "2", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "12 Tracks analysiert, davon 12 mit deinen Sternen" in text and "Ansatz 3" in text
    assert len(out.read_text(encoding="utf-8").splitlines()) == 13
    # zweiter Lauf kommt komplett aus dem Cache
    assert main(["--xml", str(xml), "--out", str(out), "--workers", "1"]) == 0
    assert "Analysiere" not in capsys.readouterr().out


def test_tuned_cross_validation_handles_many_features():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(80, 300))           # mehr Merkmale als sinnvoll lernbar
    y = np.clip(np.rint(3 + X[:, 0]), 1, 5)  # nur ein Merkmal zählt
    ev = energy.evaluate("x", y, energy.cross_val_predict_tuned(X, y))
    assert ev.within_one > 0.8


@needs_ffmpeg
def test_cli_ki_report_with_fake_ai(tmp_path, monkeypatch, capsys):
    """Auswertung mit --ki, ohne echtes Modell (die KI-Merkmale werden simuliert)."""
    from musiclib import energy_cli

    monkeypatch.setattr(energy_cli, "data_dir", lambda: tmp_path / "data")
    rng = np.random.default_rng(0)
    for i in range(15):
        make_loop(tmp_path / str(1 + i % 5) / f"t{i}.wav", 1 + i % 5, 45)

    def fake_ai(entries, workers, cache):
        out = {}
        for i, e in enumerate(entries):
            out[i] = {"embedding": list(rng.normal(size=16) + e.stars), "engagement": e.stars / 5, "danceability": .9,
                      "aggressive": e.stars / 6, "party": .5, "vocal": 0.8 if i % 3 == 0 else 0.1}
        return out, []

    monkeypatch.setattr(energy_cli, "analyze_ai", fake_ai)
    out = tmp_path / "ki.csv"
    assert main(["--folder", str(tmp_path), "--ki", "--out", str(out), "--workers", "2"]) == 0
    text = capsys.readouterr().out
    assert "Ansatz 5: KI-Fingerabdruck" in text and "KI: Aggressiv" in text and "5 von 15 Tracks" in text
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert "KI vocal" in header and "Bester gelernter Ansatz" in header
