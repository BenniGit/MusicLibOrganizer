"""Library prüfen: liest die sortierte Library (und optional Rekordbox) und listet, was auffällt.

Ändert nichts. Ergebnis ist ein Textbericht, z. B.:
fehlende Angaben, Cover, Bitraten, Schreibvarianten (die Ordner aufspalten), mögliche Duplikate,
uneinheitliche Release-Ordner, zu lange Pfade, Rekordbox-Einträge ohne Datei.
"""
from __future__ import annotations

import os
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import mutagen
from mutagen.id3 import ID3

from .matcher import canonical_mix, normalize
from .organizer import MAX_PATH_LEN
from .scanner import SUPPORTED_EXTENSIONS, _read_id3, _read_vorbis, iter_audio_files, split_mix

REQUIRED = [("artist", "Artist"), ("title", "Titel"), ("albumartist", "Album-Artist"), ("album", "Album"),
            ("track", "Tracknummer"), ("label", "Label"), ("genre", "Genre"), ("date", "Jahr")]
IGNORED_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
SHOW = 15  # Beispiele pro Abschnitt im Bericht


@dataclass
class FileInfo:
    path: Path
    fmt: str
    bitrate: int = 0          # kbit/s
    vbr: bool = False
    tags: dict[str, str] = field(default_factory=dict)
    has_cover: bool = False


def read_file(path: Path) -> FileInfo:
    info = FileInfo(path, path.suffix.lower().lstrip("."))
    try:
        audio = mutagen.File(path)
    except Exception:
        return info
    if audio is None:
        return info
    if audio.info is not None:
        info.bitrate = round((getattr(audio.info, "bitrate", 0) or 0) / 1000)
        mode = str(getattr(audio.info, "bitrate_mode", ""))
        info.vbr = mode.endswith(("VBR", "ABR"))
    if isinstance(audio.tags, ID3):
        info.tags, _ = _read_id3(audio.tags)
        info.has_cover = bool(audio.tags.getall("APIC"))
    elif audio.tags is not None:
        info.tags, _ = _read_vorbis(audio.tags)
    info.has_cover = info.has_cover or bool(getattr(audio, "pictures", None))
    return info


def collect(root: Path, progress: Callable[[int, int, Path], None] | None = None) -> list[FileInfo]:
    files = list(iter_audio_files(root))
    out = []
    for i, p in enumerate(files, 1):
        out.append(read_file(p))
        if progress:
            progress(i, len(files), p)
    return out


def _nfc(p) -> str:
    return unicodedata.normalize("NFC", str(p))


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


class Report:
    def __init__(self):
        self.lines: list[str] = []
        self.hints: list[str] = []  # Kurzfassung oben

    def section(self, title: str) -> None:
        self.lines += ["", title, "-" * len(title)]

    def add(self, text: str = "") -> None:
        self.lines.append(text)

    def examples(self, items: list[str], show: int = SHOW) -> None:
        self.lines += [f"  {x}" for x in items[:show]]
        if len(items) > show:
            self.lines.append(f"  … und {len(items) - show} weitere")


def _variants(values: list[str]) -> list[str]:
    """Gleiche Namen in verschiedener Schreibweise ('FISHER' / 'Fisher'), mit Anzahl."""
    groups: dict[str, Counter] = defaultdict(Counter)
    for v in values:
        if v.strip():
            groups[normalize(v)][v.strip()] += 1
    from .tagger import clean_text

    out = []
    for spellings in groups.values():
        if len(spellings) > 1:
            line = "  |  ".join(f"{s} ({n})" for s, n in spellings.most_common())
            if len({clean_text(s) for s in spellings}) == 1:
                line += "   ← nur unsichtbares Zeichen / andere Umlaut-Kodierung"
            out.append(line)
    return sorted(out, key=str.lower)


def _artists(value: str) -> list[str]:
    return [a.strip() for a in value.replace(" & ", ", ").split(",") if a.strip()]


def build_report(root: Path, files: list[FileInfo], rekordbox_paths: list[str] | None = None,
                 old_root: Path | None = None, migrated: set[str] | None = None) -> Report:
    """``migrated``: Quellpfade aus dem Umzugs-Journal (welche alten Dateien übernommen wurden)."""
    r = Report()
    n = len(files)
    r.add(f"Library-Prüfung {datetime.now():%d.%m.%Y %H:%M} – {root}")

    # --- Überblick
    r.section("Überblick")
    size = sum(f.path.stat().st_size for f in files if f.path.exists())
    formats = Counter(f.fmt for f in files)
    r.add(f"{n} Audiodateien, {size / 1e9:.1f} GB – " + ", ".join(f"{c}× {k}" for k, c in formats.most_common()))
    genres = Counter(f.tags.get("genre", "") or "(leer)" for f in files)
    r.add(f"{len(genres)} Genres: " + ", ".join(f"{g} ({c})" for g, c in genres.most_common(20)))
    labels = Counter(f.tags.get("label", "") for f in files if f.tags.get("label"))
    r.add(f"{len(labels)} Labels, häufigste: " + ", ".join(f"{g} ({c})" for g, c in labels.most_common(10)))
    years = Counter((f.tags.get("date", "") or "")[:4] for f in files)
    decades = Counter((y[:3] + "0er") if y.isdigit() else "ohne Jahr" for y in years.elements())
    r.add("Jahre: " + ", ".join(f"{d} ({c})" for d, c in sorted(decades.items())))

    # --- Fehlende Angaben
    r.section("Fehlende Angaben")
    any_missing = False
    for key, label in REQUIRED:
        missing = [_rel(root, f.path) for f in files if not f.tags.get(key)]
        if missing:
            any_missing = True
            r.add(f"{label}: {len(missing)} Dateien")
            r.examples(missing, 5)
    no_cover = [_rel(root, f.path) for f in files if not f.has_cover]
    if no_cover:
        any_missing = True
        r.add(f"Cover: {len(no_cover)} Dateien ohne Cover")
        r.examples(no_cover, 10)
        r.hints.append(f"{len(no_cover)} Dateien ohne Cover")
    if not any_missing:
        r.add("Alles vollständig ✔")

    # --- Audioqualität
    r.section("Audioqualität")
    mp3 = [f for f in files if f.fmt == "mp3"]
    low = [f for f in mp3 if f.bitrate and f.bitrate < 320 and not f.vbr]
    vbr = [f for f in mp3 if f.vbr]
    other = [f for f in files if f.fmt != "mp3"]
    r.add(f"MP3 mit 320 kbit/s: {len(mp3) - len(low) - len(vbr)} von {len(mp3)}")
    if low:
        by_rate = Counter(f.bitrate for f in low)
        r.add("Unter 320 kbit/s: " + ", ".join(f"{b} kbit/s ({c})" for b, c in sorted(by_rate.items())))
        r.examples([f"{f.bitrate:3d} kbit/s  {_rel(root, f.path)}" for f in sorted(low, key=lambda f: f.bitrate)])
        r.hints.append(f"{len(low)} MP3s unter 320 kbit/s – Kandidaten für einen Neukauf/Neudownload")
    if vbr:
        r.add(f"VBR (variable Bitrate): {len(vbr)}")
        r.examples([f"~{f.bitrate} kbit/s  {_rel(root, f.path)}" for f in vbr], 5)
    if other:
        r.add(f"Nicht-MP3: {len(other)}")
        r.examples([_rel(root, f.path) for f in other], 5)

    # --- Schreibvarianten
    r.section("Schreibvarianten (gleicher Name, andere Schreibweise – teilt Ordner auf)")
    found = False
    for label, values in (
        ("Album-Artist", [f.tags.get("albumartist", "") for f in files]),
        ("Artist", [a for f in files for a in _artists(f.tags.get("artist", ""))]),
        ("Label", [f.tags.get("label", "") for f in files]),
        ("Genre", [f.tags.get("genre", "") for f in files]),
    ):
        variants = _variants(values)
        if variants:
            found = True
            r.add(f"{label}: {len(variants)}")
            r.examples(variants)
            if label in ("Album-Artist", "Label", "Genre"):
                r.hints.append(f"{len(variants)} {label}-Schreibvarianten")
    if not found:
        r.add("Keine ✔")

    # --- Mögliche Duplikate
    r.section("Mögliche Duplikate")
    by_song: dict[tuple, list[FileInfo]] = defaultdict(list)
    by_isrc: dict[str, list[FileInfo]] = defaultdict(list)
    for f in files:
        title, mix = split_mix(f.tags.get("title", ""))
        mix = f.tags.get("mix") or mix
        if title:
            artist = normalize(_artists(f.tags.get("artist", ""))[0] if f.tags.get("artist") else "")
            by_song[(artist, normalize(title), canonical_mix(mix))].append(f)
        if f.tags.get("isrc"):
            by_isrc[f.tags["isrc"].upper()].append(f)
    dups = [g for g in by_song.values() if len(g) > 1]
    seen = {frozenset(id(f) for f in g) for g in dups}
    dups += [g for g in by_isrc.values() if len(g) > 1 and frozenset(id(f) for f in g) not in seen]
    if dups:
        r.add(f"{len(dups)} Gruppen (gleicher Artist/Titel/Mix oder gleiche ISRC):")
        r.examples([" ↔ ".join(f"{_rel(root, f.path)} ({f.bitrate} kbit/s)" for f in g) for g in dups], 25)
        r.hints.append(f"{len(dups)} mögliche Duplikate")
    else:
        r.add("Keine ✔")

    # --- Release-Ordner
    r.section("Release-Ordner")
    folders: dict[Path, list[FileInfo]] = defaultdict(list)
    for f in files:
        folders[f.path.parent].append(f)
    mixed, numbering, incomplete = [], [], 0
    for folder, fs in sorted(folders.items()):
        rel = _rel(root, folder)
        for key, label in (("album", "Album"), ("albumartist", "Album-Artist"), ("label", "Label")):
            values = {f.tags.get(key, "") for f in fs}
            if len(values) > 1:
                mixed.append(f"{rel}: {label} uneinheitlich – " + " / ".join(sorted(v or "(leer)" for v in values)))
        years = {(f.tags.get("date", "") or "")[:4] for f in fs}
        if len(years) > 1:
            mixed.append(f"{rel}: Jahr uneinheitlich – " + " / ".join(sorted(y or "(leer)" for y in years)))
        nums = [f.tags.get("track", "").split("/") for f in fs]
        numbers = [int(x[0]) for x in nums if x and x[0].strip().isdigit()]
        totals = {int(x[1]) for x in nums if len(x) > 1 and x[1].strip().isdigit()}
        dup_numbers = sorted(k for k, c in Counter(numbers).items() if c > 1)
        if dup_numbers:
            numbering.append(f"{rel}: Tracknummer doppelt – {', '.join(map(str, dup_numbers))}")
        if totals and max(totals) > len(fs):
            incomplete += 1
    r.add(f"{len(folders)} Ordner, {incomplete} davon nur teilweise vorhanden (z. B. einzelne Tracks einer EP – normal)")
    if mixed:
        r.add(f"Uneinheitliche Angaben in {len(mixed)} Fällen:")
        r.examples(mixed, 25)
        r.hints.append(f"{len(mixed)} uneinheitliche Release-Ordner")
    if numbering:
        r.add("Tracknummern:")
        r.examples(numbering)

    # --- Struktur
    r.section("Ordnerstruktur")
    too_long = [str(f.path) for f in files if len(str(f.path)) > MAX_PATH_LEN]
    if too_long:
        r.add(f"Pfad länger als {MAX_PATH_LEN} Zeichen (Rekordbox importiert sie nicht): {len(too_long)}")
        r.examples(too_long)
        r.hints.append(f"{len(too_long)} Pfade zu lang für Rekordbox")
    unknown = [_rel(root, f.path) for f in files if "_Unbekannt" in f.path.parts]
    if unknown:
        r.add(f"Im Ordner „_Unbekannt“: {len(unknown)}")
        r.examples(unknown, 10)
    empty, stray = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        names = [x for x in filenames if x not in IGNORED_FILES and not x.startswith("._")]
        if not names and not dirnames:
            empty.append(_rel(root, Path(dirpath)))
        stray += [_rel(root, Path(dirpath) / x) for x in names
                  if Path(x).suffix.lower() not in SUPPORTED_EXTENSIONS and not x.endswith(".tmp")]
    if empty:
        r.add(f"Leere Ordner: {len(empty)}")
        r.examples(empty, 10)
    if stray:
        r.add(f"Andere Dateien (keine Musik): {len(stray)}")
        r.examples(stray, 10)
    if not (too_long or unknown or empty or stray):
        r.add("Alles sauber ✔")

    # --- Alte Library
    if old_root is not None and old_root.is_dir():
        r.section(f"Alte Library ({old_root})")
        old_files = list(iter_audio_files(old_root))
        r.add(f"Noch {len(old_files)} Audiodateien im alten Ordner.")
        if migrated is not None:
            todo = [_rel(old_root, p) for p in old_files if _nfc(p) not in migrated]
            if todo:
                r.add(f"Davon nie in die neue Library übernommen: {len(todo)}")
                r.examples(todo, 30)
                r.hints.append(f"{len(todo)} Dateien der alten Library wurden nie übernommen")
            else:
                r.add("Alle wurden übernommen ✔ – der alte Ordner kann nach einer Sicherung weg.")

    # --- Rekordbox
    if rekordbox_paths is not None:
        r.section("Rekordbox")
        streaming = [p for p in rekordbox_paths if p and not p.startswith("/")]  # z. B. soundcloud:tracks:123
        sampler = [p for p in rekordbox_paths if "/rekordbox/Sampler/" in p]
        rb = {_nfc(p) for p in rekordbox_paths if p and p.startswith("/") and "/rekordbox/Sampler/" not in p}
        lib = {_nfc(f.path) for f in files}
        root_nfc = _nfc(root).rstrip("/") + "/"
        missing = sorted(p for p in rb if not Path(p).exists())
        outside = sorted(p for p in rb if not p.startswith(root_nfc) and Path(p).exists()
                         and Path(p).suffix.lower() in SUPPORTED_EXTENSIONS)
        not_imported = sorted(lib - rb)
        r.add(f"{len(rb)} Dateien in Rekordbox, davon {len(rb & lib)} aus der neuen Library"
              + (f"; außerdem {len(streaming)} Streaming-Einträge (SoundCloud/Beatport Streaming …)" if streaming else "")
              + (f" und {len(sampler)} mitgelieferte Sampler-Sounds" if sampler else "") + " – ignoriert.")
        if missing:
            r.add(f"Datei fehlt (Rekordbox zeigt „!“): {len(missing)}")
            r.examples(missing, 20)
            r.hints.append(f"{len(missing)} Rekordbox-Einträge ohne Datei")
        if outside:
            r.add(f"Liegen noch außerhalb der neuen Library: {len(outside)}")
            r.examples(outside, 20)
            r.hints.append(f"{len(outside)} Rekordbox-Tracks noch außerhalb der neuen Library")
        if not_imported:
            r.add(f"In der neuen Library, aber nicht in Rekordbox: {len(not_imported)}")
            r.examples([_rel(root, Path(p)) for p in not_imported], 20)
            r.hints.append(f"{len(not_imported)} Dateien nicht in Rekordbox importiert")
        if not (missing or outside or not_imported):
            r.add("Alles verbunden ✔")
    return r


def render(r: Report) -> str:
    head = ["Kurzfassung:"] + ([f"  • {h}" for h in r.hints] or ["  • Nichts Auffälliges ✔"])
    return "\n".join(r.lines[:1] + [""] + head + r.lines[1:]) + "\n"


def rekordbox_paths(db_path: Path | None = None) -> list[str]:
    """Alle Dateipfade aus der Rekordbox-Datenbank (nur lesend)."""
    from .rekordbox_db import open_db

    db = open_db(db_path)
    try:
        return [c.FolderPath for c in db.get_content() if c.FolderPath]
    finally:
        db.close()
