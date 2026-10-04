"""Schreibweisen vereinheitlichen: „Omar-S“/„Omar S“, „K7 Records“/„!K7 Records“, „Not On Label“ …

Ablauf: Varianten finden (``find_rules``) → für jede Regel eine Schreibweise wählen → Änderungen
planen (``plan``, ändert nichts) → ausführen (``apply``): Tags neu schreiben, Ordner/Dateien
umbenennen und jede Umbenennung ins Umzugs-Journal eintragen. Danach stellt
„Rekordbox auf neue Library umstellen“ die Pfade in Rekordbox um – Sterne, Cues und Playlists bleiben.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from mutagen.id3 import ID3, TCON, TPE1, TPE2, TPUB

from .audit import FileInfo, _artists
from .backup import data_dir
from .journal import Journal, norm
from .matcher import normalize
from .models import no_label
from .organizer import MAX_PATH_LEN, sanitize
from .scanner import SUPPORTED_EXTENSIONS
from .tagger import clean_text

# Regel-Feld -> (Tag-Felder in FileInfo.tags, ID3-Frames)
FIELDS = {
    "artist": ("Artist / Album-Artist", ("artist", "albumartist")),
    "label": ("Label", ("label",)),
    "genre": ("Genre", ("genre",)),
}
FRAMES = {"artist": TPE1, "albumartist": TPE2, "label": TPUB, "genre": TCON}


@dataclass
class Rule:
    field: str
    spellings: dict[str, int]     # Schreibweise -> Anzahl Dateien
    target: str                   # gewählte Schreibweise
    enabled: bool = True

    @property
    def label(self) -> str:
        return FIELDS[self.field][0]

    def replaces(self, value: str) -> bool:
        return value in self.spellings and value != self.target


@dataclass
class Change:
    path: Path
    new_path: Path
    tags: dict[str, tuple[str, str]] = field(default_factory=dict)  # Feld -> (alt, neu)

    @property
    def moves(self) -> bool:
        return self.path != self.new_path


def _suggest(spellings: Counter) -> str:
    """Häufigste Schreibweise; bei Gleichstand die „saubere“ (ohne unsichtbare Zeichen, mit Großbuchstaben)."""
    return max(spellings, key=lambda s: (spellings[s], clean_text(s) == s, sum(c.isupper() for c in s) > 0, s))


def _values(f: FileInfo, rule_field: str) -> list[str]:
    if rule_field == "artist":
        return _artists(f.tags.get("artist", "")) + [f.tags.get("albumartist", "")]
    return [f.tags.get(rule_field, "")]


def find_rules(files: list[FileInfo], label_fallback: str = "Self-Released") -> list[Rule]:
    rules: list[Rule] = []
    for rule_field in FIELDS:
        groups: dict[str, Counter] = defaultdict(Counter)
        for f in files:
            for v in set(_values(f, rule_field)):
                if v.strip() and not (rule_field == "label" and no_label(v)):
                    groups[normalize(v)][v] += 1
        for spellings in groups.values():
            if len(spellings) > 1:
                rules.append(Rule(rule_field, dict(spellings.most_common()), clean_text(_suggest(spellings))))
    placeholders = Counter(f.tags.get("label", "") for f in files if f.tags.get("label") and no_label(f.tags["label"]))
    if placeholders and label_fallback.strip():
        rules.append(Rule("label", dict(placeholders.most_common()), label_fallback.strip()))
    return sorted(rules, key=lambda r: (list(FIELDS).index(r.field), r.target.lower()))


def _replace_tokens(value: str, rules: list[Rule]) -> str:
    """Ersetzt einzelne Namen in einem Feld wie „A, B & C“ (nur ganze Namen)."""
    for rule in rules:
        for spelling in rule.spellings:
            if spelling != rule.target:
                value = re.sub(rf"(?<!\w){re.escape(spelling)}(?!\w)", lambda _m: rule.target, value)
    return value


def path_part(value: str) -> str:
    """Wie ein Feldwert im Ordner-/Dateinamen erscheint (siehe organizer.target_path)."""
    return sanitize(re.sub(r"\s*/\s*", " - ", value))


def _same(a: str, b: str) -> bool:
    return clean_text(a).casefold() == clean_text(b).casefold()


def _new_parts(parts: list[str], old: dict[str, str], new: dict[str, str]) -> list[str]:
    """Ordner/Datei passend zu den neuen Werten umbenennen (Standardvorlage
    „Album-Artist/Jahr - Release [Label]/Nr - Artist - Titel“). Was nicht passt, bleibt."""
    parts = list(parts)
    if len(parts) >= 3:
        if new.get("albumartist") != old.get("albumartist") and _same(parts[0], path_part(old["albumartist"])):
            parts[0] = path_part(new["albumartist"])
        if new.get("label") != old.get("label"):
            old_l, new_l = f"[{path_part(old['label'])}]", f"[{path_part(new['label'])}]"
            idx = parts[1].casefold().rfind(old_l.casefold())
            if idx >= 0:
                parts[1] = parts[1][:idx] + new_l + parts[1][idx + len(old_l):]
            elif no_label(old["label"]):  # Ordner „[Not On Label]“, Tag „Not On Label (… Self-released)“
                parts[1] = re.sub(r"\[not on label[^\]]*\]", lambda _m: new_l, parts[1], flags=re.I)
    if new.get("artist") != old.get("artist"):
        stem, ext = os.path.splitext(parts[-1])
        segs = stem.split(" - ")
        if len(segs) >= 3 and _same(segs[1], path_part(old["artist"])):
            segs[1] = path_part(new["artist"])
            parts[-1] = " - ".join(segs) + ext
    return parts


def plan(root: Path, files: list[FileInfo], rules: list[Rule]) -> list[Change]:
    active = [r for r in rules if r.enabled and r.target.strip()]
    by_field = {k: [r for r in active if r.field == k] for k in FIELDS}
    changes = []
    for f in files:
        old = {k: f.tags.get(k, "") for k in FRAMES}
        new = dict(old)
        new["artist"] = _replace_tokens(old["artist"], by_field["artist"])
        new["albumartist"] = _replace_tokens(old["albumartist"], by_field["artist"])
        for k in ("label", "genre"):
            for r in by_field[k]:
                if r.replaces(old[k]):
                    new[k] = r.target
        tags = {k: (old[k], new[k]) for k in FRAMES if old[k] != new[k]}
        if not tags:
            continue
        try:
            parts = list(f.path.relative_to(root).parts)
        except ValueError:
            parts = [f.path.name]
        new_path = root.joinpath(*_new_parts(parts, old, new))
        changes.append(Change(f.path, new_path, tags))
    return changes


def summary(changes: list[Change]) -> str:
    moves = [c for c in changes if c.moves]
    lines = [f"{len(changes)} Dateien bekommen neue Tags, {len(moves)} davon werden umbenannt/verschoben."]
    for c in moves[:12]:
        lines.append(f"  {c.path.name}\n    → {c.new_path}")
    if len(moves) > 12:
        lines.append(f"  … und {len(moves) - 12} weitere")
    return "\n".join(lines)


# --- Ausführen ---------------------------------------------------------------------------

def _key(name: str) -> str:
    return clean_text(name).casefold()


def _ensure_dir(root: Path, parts: list[str], on_rename: Callable[[Path, Path], None]) -> Path:
    """Legt den Zielordner an. Gibt es ihn schon in anderer Groß-/Kleinschreibung (macOS behandelt
    das als denselben Ordner), wird er auf die neue Schreibweise umbenannt."""
    cur = root
    for part in parts:
        entries = {e.name: e for e in cur.iterdir()} if cur.is_dir() else {}
        same = next((n for n in entries if norm(n) == norm(part)), None)  # nur andere Umlaut-Kodierung
        if same is not None:
            cur = cur / same
            continue
        twin = next((e for n, e in entries.items() if e.is_dir() and _key(n) == _key(part)), None)
        target = cur / part
        if twin is not None:
            tmp = cur / f".{part}.umbenennen"
            os.rename(twin, tmp)
            os.rename(tmp, target)
            on_rename(twin, target)
        else:
            target.mkdir(parents=True, exist_ok=True)
        cur = target
    return cur


def _move(src: Path, dst: Path) -> None:
    if dst.exists():
        if os.path.samefile(src, dst) and src.name != dst.name:  # nur Groß-/Kleinschreibung anders
            tmp = src.with_name(f".{src.name}.umbenennen")
            os.rename(src, tmp)
            os.rename(tmp, dst)
            return
        if os.path.samefile(src, dst):
            return
        raise FileExistsError(f"Ziel existiert schon: {dst}")
    os.rename(src, dst)


def _remove_empty_dirs(root: Path, start: Path) -> None:
    d = start
    while d != root and root in d.parents:
        try:
            entries = [e for e in d.iterdir() if e.name != ".DS_Store"]
        except OSError:
            return
        if entries:
            return
        for e in d.iterdir():
            e.unlink()
        d.rmdir()
        d = d.parent


def _write_tags(path: Path, tags: dict[str, tuple[str, str]]) -> None:
    id3 = ID3(path)
    for k, (_old, new) in tags.items():
        frame = FRAMES[k]
        id3.delall(frame.__name__)
        if new:
            id3.add(frame(encoding=3, text=[new]))
    id3.save(path, v2_version=4, v1=0)


def apply(root: Path, changes: list[Change], journal: Journal | None = None,
          progress: Callable[[int, int, str], None] | None = None) -> tuple[int, list[str], Path]:
    """Schreibt Tags, benennt um, trägt Umbenennungen ins Journal ein.
    Gibt (erfolgreich, Probleme, Protokolldatei) zurück. Das Protokoll enthält alle alten Werte."""
    log_file = data_dir() / "vereinheitlichen" / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    renamed: list[tuple[Path, Path]] = []  # umbenannte Ordner (alt, neu)

    def on_rename(old_dir: Path, new_dir: Path) -> None:
        renamed.append((old_dir, new_dir))
        if journal is not None:  # alle Dateien darin haben jetzt einen neuen Pfad
            for f in new_dir.rglob("*"):
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
                    journal.record(old_dir / f.relative_to(new_dir), f)

    def current(path: Path) -> Path:
        for old_dir, new_dir in renamed:
            if old_dir in path.parents:
                path = new_dir / path.relative_to(old_dir)
        return path

    ok, problems = 0, []
    with log_file.open("w", encoding="utf-8") as log:
        for i, c in enumerate(changes, 1):
            if progress:
                progress(i, len(changes), c.path.name)
            try:
                if c.moves and len(str(c.new_path)) > MAX_PATH_LEN:
                    raise ValueError(f"neuer Pfad länger als {MAX_PATH_LEN} Zeichen")
                if c.path.suffix.lower() != ".mp3":
                    raise ValueError("nur MP3 wird unterstützt")
                src = current(c.path)
                _write_tags(src, c.tags)
                if c.moves:
                    rel = list(c.new_path.relative_to(root).parts)
                    folder = _ensure_dir(root, rel[:-1], on_rename)
                    src = current(src)
                    dst = folder / rel[-1]
                    _move(src, dst)
                    if journal is not None:
                        journal.record(src, dst)
                    _remove_empty_dirs(root, src.parent)
                log.write(json.dumps({"alt": str(c.path), "neu": str(c.new_path),
                                      "tags": {k: list(v) for k, v in c.tags.items()}}, ensure_ascii=False) + "\n")
                ok += 1
            except Exception as e:
                problems.append(f"{c.path.name}: {e}")
    return ok, problems, log_file
