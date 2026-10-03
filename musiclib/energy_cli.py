"""Test-Werkzeug: Wie gut lässt sich die Energie (★1–5) deiner Tracks automatisch schätzen?

Beispiele:
    musiclib-energie --xml ~/Desktop/rekordbox.xml --list-playlists
    musiclib-energie --xml ~/Desktop/rekordbox.xml --playlist "Energie"
    musiclib-energie --folder ~/Music/Energie-Test        (Unterordner "1" … "5" = Sterne)
"""
from __future__ import annotations

import argparse
import csv
import json
import multiprocessing
import os
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import energy
from .backup import data_dir
from .models import SUPPORTED_EXTENSIONS

AUDIO_EXT = SUPPORTED_EXTENSIONS | {".m4a", ".aac", ".ogg", ".opus"}


@dataclass
class Entry:
    path: Path
    stars: int = 0
    bpm: float | None = None
    label: str = ""


# ---------------------------------------------------------------------------- Eingaben
def entries_from_xml(xml: Path, playlists: list[str], path_map: list[tuple[str, str]]) -> list[Entry]:
    from .rekordbox_xml import load

    tracks, pls = load(xml)
    if playlists:
        wanted = {name for name in pls if any(p.lower() in name.lower() for p in playlists)}
        if not wanted:
            sys.exit(f"Keine Playlist passt zu {playlists}. Mit --list-playlists anzeigen lassen.")
        print("Playlists:", ", ".join(sorted(wanted)))
        ids = {tid for name in wanted for tid in pls[name]}
        tracks = {tid: t for tid, t in tracks.items() if tid in ids}
    out = []
    for t in tracks.values():
        p = str(t.path)
        for old, new in path_map:
            if p.startswith(old):
                p = new + p[len(old):]
        out.append(Entry(Path(p), t.stars, t.bpm, f"{t.artist} - {t.name}".strip(" -")))
    return out


def stars_from_folder_name(name: str) -> int:
    m = re.search(r"([1-5])", name)
    return int(m.group(1)) if m and len(re.findall(r"\d", name)) == 1 else 0


def entries_from_folder(root: Path) -> list[Entry]:
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in AUDIO_EXT and not p.name.startswith("._"):
            rel = p.relative_to(root).parts[:-1]
            stars = next((s for s in (stars_from_folder_name(d) for d in rel) if s), 0)
            out.append(Entry(p, stars, None, p.stem))
    return out


# ---------------------------------------------------------------------------- Analyse
def _duration_and_bpm(path: Path) -> tuple[float | None, float | None]:
    try:
        import mutagen

        audio = mutagen.File(path)
        dur = getattr(audio.info, "length", None) if audio is not None else None
        bpm = None
        tags = getattr(audio, "tags", None)
        if tags is not None:
            raw = tags.get("TBPM") or tags.get("bpm") or tags.get("BPM")
            raw = getattr(raw, "text", raw)
            if isinstance(raw, list):
                raw = raw[0] if raw else None
            bpm = float(str(raw).replace(",", ".")) if raw else None
        return dur, bpm
    except Exception:
        return None, None


def _analyze_one(path: str, known_bpm: float | None) -> dict:
    dur, tag_bpm = _duration_and_bpm(Path(path))
    return energy.analyze(path, dur, known_bpm or tag_bpm).to_dict()


def _cache_key(p: Path) -> str:
    st = p.stat()
    return f"{p}|{st.st_size}|{int(st.st_mtime)}"


def analyze_all(entries: list[Entry], workers: int, cache_path: Path) -> tuple[list[Entry], np.ndarray, list[str]]:
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}
    results: dict[int, dict] = {}
    errors: list[str] = []
    todo = []
    for i, e in enumerate(entries):
        if not e.path.is_file():
            errors.append(f"nicht gefunden: {e.path}")
            continue
        key = _cache_key(e.path)
        if key in cache:
            results[i] = cache[key]
            if e.bpm:
                results[i] = dict(results[i], bpm=e.bpm)
        else:
            todo.append((i, key))
    if todo:
        print(f"Analysiere {len(todo)} Tracks ({len(results)} aus dem Cache) mit {workers} Prozessen …")
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_analyze_one, str(entries[i].path), entries[i].bpm): (i, key) for i, key in todo}
            for n, fut in enumerate(as_completed(futures), 1):
                i, key = futures[fut]
                try:
                    results[i] = cache[key] = fut.result()
                except Exception as e:  # defekte Datei o. Ä.
                    errors.append(f"{entries[i].path.name}: {e}")
                if n % 10 == 0 or n == len(todo):
                    print(f"  {n}/{len(todo)}", end="\r", flush=True)
        print()
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache))
        except OSError:
            pass
    ok = sorted(results)
    X = np.array([[results[i][f] for f in energy.FEATURES] for i in ok]) if ok else np.zeros((0, len(energy.FEATURES)))
    return [entries[i] for i in ok], X, errors


# ---------------------------------------------------------------------------- Auswertung
def stars_matching_distribution(scores: np.ndarray, stars: np.ndarray) -> np.ndarray:
    """Ordnet die Punktzahlen so auf ★1–5 zu, dass die Verteilung deiner eigenen Sterne entspricht."""
    counts = np.array([(stars == s).sum() for s in range(1, 6)], float)
    cum = np.cumsum(counts)[:-1] / counts.sum()
    edges = np.quantile(scores, cum)
    return 1 + np.searchsorted(edges, scores, side="right")


def print_eval(ev: energy.Evaluation) -> None:
    sp = "–" if np.isnan(ev.spearman) else f"{ev.spearman:+.2f}"
    print(f"  {ev.name:<34} exakt {ev.exact:6.0%}   ±1 Stern {ev.within_one:6.0%}   "
          f"Ø Abweichung {ev.mae:4.2f}   Rangkorrelation {sp}")


def confusion(stars: np.ndarray, pred: np.ndarray) -> None:
    pred = np.clip(np.rint(pred), 1, 5).astype(int)
    print("      geschätzt →  ★1   ★2   ★3   ★4   ★5")
    for s in range(1, 6):
        row = [(pred[stars == s] == p).sum() for p in range(1, 6)]
        if sum(row):
            print(f"  deine ★{s} ({sum(row):3d})   " + "".join(f"{n:4d} " for n in row))


def _analyze_ai_one(path: str) -> dict:
    from . import ai_energy

    dur, _ = _duration_and_bpm(Path(path))
    return ai_energy.analyze(path, dur)


def analyze_ai(entries: list[Entry], workers: int, cache_path: Path) -> tuple[dict[int, dict], list[str]]:
    """KI-Merkmale (Fingerabdruck + Einschätzungen) für alle Einträge, mit eigenem Cache."""
    from . import ai_energy

    ai_energy.check_available()
    ai_energy.ensure_models()
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")  # wird an die Arbeitsprozesse vererbt
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}
    results: dict[int, dict] = {}
    errors: list[str] = []
    todo = []
    for i, e in enumerate(entries):
        key = _cache_key(e.path)
        if key in cache:
            results[i] = cache[key]
        else:
            todo.append((i, key))
    if todo:
        print(f"KI-Analyse von {len(todo)} Tracks ({len(results)} aus dem Cache) mit {workers} Prozessen …")
        # "spawn": frische Prozesse, damit TensorFlow nicht in einem geforkten Prozess hängen bleibt
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as ex:
            futures = {ex.submit(_analyze_ai_one, str(entries[i].path)): (i, key) for i, key in todo}
            for n, fut in enumerate(as_completed(futures), 1):
                i, key = futures[fut]
                try:
                    results[i] = cache[key] = fut.result()
                except Exception as e:
                    errors.append(f"KI {entries[i].path.name}: {e}")
                if n % 5 == 0 or n == len(todo):
                    print(f"  {n}/{len(todo)}", end="\r", flush=True)
                if n % 50 == 0:  # Zwischenstand sichern
                    _save_json(cache_path, cache)
        print()
        _save_json(cache_path, cache)
    return results, errors


def _save_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="musiclib-energie", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--xml", type=Path, help="Rekordbox-Export (Datei → Bibliothek exportieren → XML)")
    src.add_argument("--folder", type=Path, help="Ordner mit Unterordnern 1–5 (= Sterne) oder ohne Sterne")
    ap.add_argument("--playlist", action="append", default=[], help="nur Tracks aus Playlists, deren Name dies enthält (mehrfach möglich)")
    ap.add_argument("--list-playlists", action="store_true", help="Playlists im XML anzeigen und beenden")
    ap.add_argument("--path-map", action="append", default=[], metavar="ALT=NEU",
                    help="Pfade umschreiben, z. B. /Volumes/USB=/Users/ich/Music")
    ap.add_argument("--ki", action="store_true",
                    help="zusätzlich KI-Analyse (Essentia/Discogs-EffNet, benötigt: pip install essentia-tensorflow)")
    ap.add_argument("--ki-workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) - 1)),
                    help="parallele Prozesse für die KI-Analyse (jeder lädt das Modell)")
    ap.add_argument("--limit", type=int, default=0, help="nur die ersten N Tracks (zum schnellen Ausprobieren)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--out", type=Path, default=Path("energie-test.csv"), help="CSV mit allen Messwerten")
    args = ap.parse_args(argv)

    if args.xml:
        if args.list_playlists:
            from .rekordbox_xml import load

            tracks, pls = load(args.xml)
            for name, ids in sorted(pls.items()):
                rated = sum(1 for i in ids if i in tracks and tracks[i].stars)
                print(f"{len(ids):5d} Tracks ({rated:4d} mit Sternen)  {name}")
            return 0
        mapping = [tuple(m.split("=", 1)) for m in args.path_map if "=" in m]
        entries = entries_from_xml(args.xml, args.playlist, mapping)
    else:
        entries = entries_from_folder(args.folder)
    if args.limit:
        entries = entries[: args.limit]
    if not entries:
        print("Keine Tracks gefunden.")
        return 1

    entries, X, errors = analyze_all(entries, args.workers, data_dir() / "energy-cache.json")
    ai: dict[int, dict] = {}
    if args.ki:
        try:
            ai, ai_errors = analyze_ai(entries, args.ki_workers, data_dir() / "energy-ai-cache.json")
        except Exception as e:  # Essentia fehlt, Modelle nicht ladbar …
            print(f"⚠ KI-Analyse nicht möglich: {e}")
            return 1
        errors += ai_errors
        keep = sorted(ai)
        entries, X = [entries[i] for i in keep], X[keep]
        ai = {n: ai[i] for n, i in enumerate(keep)}
    for e in errors[:10]:
        print("⚠", e)
    if len(errors) > 10:
        print(f"⚠ … und {len(errors) - 10} weitere Fehler")
    if len(entries) < 5:
        print("Zu wenige Tracks analysiert.")
        return 1

    from .ai_energy import HEAD_LABELS, HEADS

    heads = list(HEADS)
    H = np.array([[ai[i][h] for h in heads] for i in range(len(entries))]) if ai else None
    E = np.array([ai[i]["embedding"] for i in range(len(entries))]) if ai else None
    bpm_col = X[:, energy.FEATURES.index("bpm")][:, None]

    stars = np.array([e.stars for e in entries])
    rated = stars > 0
    unsup = energy.unsupervised_scores(X)
    print(f"\n{len(entries)} Tracks analysiert, davon {rated.sum()} mit deinen Sternen.")

    unsup_stars = energy.to_stars_by_quantile(unsup)
    best_name, best_pred = "", np.full(len(entries), np.nan)
    if rated.sum() >= 10 and len(set(stars[rated])) >= 2:
        ys = stars[rated].astype(float)
        dist = Counter(stars[rated].tolist())
        print("Deine Verteilung: " + "  ".join(f"★{s}: {dist.get(s, 0)}" for s in range(1, 6)))
        unsup_stars = np.zeros(len(entries), int)
        unsup_stars[rated] = stars_matching_distribution(unsup[rated], stars[rated])
        if (~rated).any():
            unsup_stars[~rated] = energy.to_stars_by_quantile(unsup[~rated], unsup[rated])
        most = max(dist, key=dist.get)

        candidates = {"Ansatz 3: Messwerte, gelernt": energy.cross_val_predict(X[rated], ys)}
        if ai:
            candidates["Ansatz 4: KI-Einschätzungen + BPM, gelernt"] = energy.cross_val_predict(
                np.hstack([H, bpm_col])[rated], ys)
            print("Lerne auf dem KI-Fingerabdruck (1280 Merkmale) …")
            candidates["Ansatz 5: KI-Fingerabdruck, gelernt"] = energy.cross_val_predict_tuned(
                np.hstack([E, bpm_col])[rated], ys)
            candidates["Ansatz 6: alles kombiniert, gelernt"] = energy.cross_val_predict_tuned(
                np.hstack([E, H, X])[rated], ys)

        print("\nTrefferquote (je höher, desto besser):")
        print_eval(energy.evaluate(f"Zum Vergleich: immer ★{most}", ys, np.full(len(ys), most)))
        print_eval(energy.evaluate("Ansatz 2: Messwerte, ungelernt", ys, unsup_stars[rated]))
        evals = {name: energy.evaluate(name, ys, pred) for name, pred in candidates.items()}
        for ev in evals.values():
            print_eval(ev)
        print("  (Gelernte Ansätze werden fair gemessen: jeder Track wird von einem Modell geschätzt, "
              "das ihn nicht kannte.)")

        best_name = min(evals, key=lambda n: evals[n].mae)
        best_pred = np.full(len(entries), np.nan)
        best_pred[rated] = candidates[best_name]
        print(f"\nBester Ansatz im Detail – {best_name}:")
        confusion(ys.astype(int), best_pred[rated])

        print("\nWelche Werte hängen mit deinen Sternen zusammen (Rangkorrelation, ±1 = perfekt):")
        cols = [(energy.FEATURE_LABELS[f], X[rated][:, j]) for j, f in enumerate(energy.FEATURES)]
        if ai:
            cols += [(HEAD_LABELS[h], H[rated][:, j]) for j, h in enumerate(heads)]
        corr = sorted(((energy.spearman(v, ys), label) for label, v in cols), key=lambda c: -abs(np.nan_to_num(c[0])))
        for c, label in corr:
            bar = "█" * int(round(abs(np.nan_to_num(c)) * 20))
            print(f"  {label:<34} {c:+.2f} {bar}")

        miss = [(abs(round(p) - s), e, s, p) for e, s, p in zip(np.array(entries)[rated], ys, best_pred[rated])]
        miss = sorted((m for m in miss if m[0] >= 2), key=lambda m: -m[0])[:10]
        if miss:
            print("\nGrößte Ausreißer (lohnt sich anzuhören):")
            for _, e, s, p in miss:
                print(f"  deine ★{int(s)}  geschätzt ★{int(np.clip(round(p), 1, 5))}   {e.label}")
    else:
        print("Zu wenige bewertete Tracks für einen Vergleich – zeige nur die ungelernte Schätzung.")
        dist = Counter(unsup_stars.tolist())
        print("Geschätzte Verteilung: " + "  ".join(f"★{s}: {dist.get(s, 0)}" for s in range(1, 6)))

    if ai:
        vocal = H[:, heads.index("vocal")]
        print(f"\nVocal-Erkennung: {int((vocal >= 0.5).sum())} von {len(vocal)} Tracks als „mit Vocals“ erkannt "
              "(Spalte „KI vocal“ in der CSV, 0–1).")

    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        header = ["Track", "Datei", "Deine Sterne", "Ansatz 2 (ungelernt)", f"Bester gelernter Ansatz ({best_name or '–'})",
                  *energy.FEATURES]
        if ai:
            header += [f"KI {h}" for h in heads]
        w.writerow(header)
        for i, (e, s, u, c, x) in enumerate(zip(entries, stars, unsup_stars, best_pred, X)):
            row = [e.label, str(e.path), s or "", u, "" if np.isnan(c) else int(np.clip(round(c), 1, 5)),
                   *[f"{v:.4f}" for v in x]]
            if ai:
                row += [f"{v:.3f}" for v in H[i]]
            w.writerow(row)
    print(f"\nAlle Messwerte: {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
