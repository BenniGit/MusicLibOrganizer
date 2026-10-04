"""Rekordbox-Bibliothek (master.db) auf die neuen Dateipfade umstellen – ohne Neuimport.

Rekordbox hängt Sterne, Farben, Cues, Beatgrids, Playlists, History und Import-Datum an den
Datenbank-Eintrag eines Tracks, nicht an die Datei. Wird nur der Pfad des Eintrags geändert,
bleibt all das erhalten. Dafür nutzen wir pyrekordbox (liest/schreibt die verschlüsselte master.db
von Rekordbox 6/7). Vor jeder Änderung werden master.db und die betroffenen Analyse-Dateien gesichert.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .backup import data_dir
from .journal import Journal, norm

# Was beim Umstellen mit einem Journal-Eintrag passiert
SWITCH = "umstellen"
ALREADY = "bereits umgestellt"
NOT_IN_RB = "nicht in Rekordbox"
TYPE_CHANGED = "Dateityp geändert"
TARGET_MISSING = "neue Datei fehlt"
ACTION_TEXT = {
    SWITCH: "wird auf den neuen Pfad umgestellt",
    ALREADY: "zeigt schon auf den neuen Pfad",
    NOT_IN_RB: "alte Datei ist nicht in Rekordbox – nichts zu tun",
    TYPE_CHANGED: "Format geändert (z. B. FLAC → MP3) – bleibt auf der alten Datei, bitte in Rekordbox neu zuordnen",
    TARGET_MISSING: "neue Datei existiert nicht (mehr) – übersprungen",
}


class RekordboxError(RuntimeError):
    pass


@dataclass
class Step:
    content_id: str
    title: str
    rating: int
    old: str
    new: str
    action: str


def rekordbox_running() -> bool:
    try:
        import psutil
    except ImportError:
        return False
    for p in psutil.process_iter(["name"]):
        name = (p.info.get("name") or "").lower()
        if name.startswith("rekordbox") and "agent" not in name:
            return True
    return False


def open_db(path: Path | None = None, db_dir: Path | None = None):
    """Öffnet die master.db (Standard: die der installierten Rekordbox-Version)."""
    try:
        from pyrekordbox.db6.database import Rekordbox6Database
    except ImportError as e:
        raise RekordboxError("pyrekordbox fehlt:  pip install pyrekordbox") from e
    try:
        if path:
            return Rekordbox6Database(path=path, db_dir=db_dir or Path(path).parent)
        return Rekordbox6Database()
    except Exception as e:
        raise RekordboxError(f"Rekordbox-Datenbank konnte nicht geöffnet werden: {e}") from e


def db_file(db) -> Path:
    return Path(db.engine.url.database)


def plan(db, journal: Journal) -> list[Step]:
    """Was würde das Umstellen tun? Ändert nichts."""
    by_path = {}
    for c in db.get_content():
        by_path.setdefault(norm(c.FolderPath or ""), c)
    steps = []
    for m in journal.all():
        old_c = by_path.get(m.src)
        new_c = by_path.get(m.dst)
        if new_c is not None:
            steps.append(Step(str(new_c.ID), new_c.Title or "", int(new_c.Rating or 0), m.src, m.dst, ALREADY))
        elif old_c is None:
            steps.append(Step("", "", 0, m.src, m.dst, NOT_IN_RB))
        elif not Path(m.dst).is_file():
            steps.append(Step(str(old_c.ID), old_c.Title or "", int(old_c.Rating or 0), m.src, m.dst, TARGET_MISSING))
        elif Path(m.src).suffix.lower() != Path(m.dst).suffix.lower():
            steps.append(Step(str(old_c.ID), old_c.Title or "", int(old_c.Rating or 0), m.src, m.dst, TYPE_CHANGED))
        else:
            steps.append(Step(str(old_c.ID), old_c.Title or "", int(old_c.Rating or 0), m.src, m.dst, SWITCH))
    return steps


def summary(steps: list[Step], show: int = 8) -> str:
    """Lesbare Zusammenfassung eines Plans."""
    from collections import Counter

    counts = Counter(s.action for s in steps)
    lines = [f"Umzugs-Journal: {len(steps)} übernommene Dateien"]
    for action in (SWITCH, ALREADY, TYPE_CHANGED, TARGET_MISSING, NOT_IN_RB):
        if counts.get(action):
            lines.append(f"  {counts[action]:5d}  {ACTION_TEXT[action]}")
    examples = [s for s in steps if s.action == SWITCH][:show]
    if examples:
        lines.append("\nBeispiele:")
        for s in examples:
            stars = "★" * s.rating if s.rating else "–"
            lines.append(f"  {stars:5} {s.title}\n        alt: {s.old}\n        neu: {s.new}")
    special = [s for s in steps if s.action in (TYPE_CHANGED, TARGET_MISSING)]
    if special:
        lines.append("\nBitte ansehen:")
        lines += [f"  [{s.action}] {s.title or Path(s.old).name}" for s in special[:20]]
    return "\n".join(lines)


def _anlz_dir(db, content) -> Path | None:
    try:
        d = db.get_anlz_dir(content)
    except Exception:
        return None
    return d if d.is_dir() else None


def backup(db, steps: list[Step], root: Path | None = None) -> Path:
    """Sichert master.db (+ -wal/-shm) und die Analyse-Ordner der betroffenen Tracks."""
    dest = (root or data_dir() / "rekordbox-backups") / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest.mkdir(parents=True, exist_ok=False)
    src_db = db_file(db)
    for suffix in ("", "-wal", "-shm"):
        f = src_db.with_name(src_db.name + suffix)
        if f.exists():
            shutil.copy2(f, dest / f.name)
    anlz = {}
    for i, s in enumerate(st for st in steps if st.action == SWITCH):
        d = _anlz_dir(db, db.get_content(ID=s.content_id))
        if d:
            target = dest / "anlz" / str(i)
            shutil.copytree(d, target)
            anlz[str(target)] = str(d)
    (dest / "sicherung.json").write_text(json.dumps({
        "created": datetime.now().isoformat(timespec="seconds"),
        "master_db": str(src_db),
        "anlz": anlz,
        "steps": [asdict(s) for s in steps if s.action == SWITCH],
    }, ensure_ascii=False, indent=1))
    return dest


def _set_path(db, content, new_path: str) -> None:
    """Pfad in Datenbank und (falls vorhanden) Analyse-Dateien setzen."""
    try:
        db.update_content_path(content, new_path, save=True, check_path=True, commit=False)
    except FileNotFoundError:
        # Nie analysierter Track: keine Analyse-Dateien – nur den Datenbank-Eintrag ändern
        old = content.FolderPath
        content.FolderPath = new_path
        if content.OrgFolderPath == old:
            content.OrgFolderPath = new_path
        content.FileNameL = Path(new_path).name


def apply(db, steps: list[Step], journal: Journal | None = None) -> int:
    """Stellt alle Schritte mit Aktion SWITCH um (Rekordbox muss geschlossen sein)."""
    todo = [s for s in steps if s.action == SWITCH]
    for s in todo:
        _set_path(db, db.get_content(ID=s.content_id), s.new)
    db.commit()
    if journal:
        journal.mark_switched([s.old for s in todo] + [s.old for s in steps if s.action == ALREADY])
    return len(todo)


def verify(db, steps: list[Step]) -> list[str]:
    """Liefert Probleme: Einträge, deren Pfad nicht stimmt oder deren Datei fehlt."""
    problems = []
    for s in steps:
        if s.action not in (SWITCH, ALREADY):
            continue
        c = db.get_content(ID=s.content_id)
        if c is None or norm(c.FolderPath) != s.new:
            problems.append(f"{s.title or s.old}: Pfad in Rekordbox stimmt nicht")
        elif not Path(c.FolderPath).is_file():
            problems.append(f"{s.title}: Datei fehlt – {c.FolderPath}")
    return problems


def latest_backup(root: Path | None = None) -> Path | None:
    root = root or data_dir() / "rekordbox-backups"
    dirs = sorted(d for d in root.glob("*") if (d / "sicherung.json").exists()) if root.exists() else []
    return dirs[-1] if dirs else None


def restore(backup_dir: Path) -> Path:
    """Spielt master.db und die Analyse-Ordner aus einer Sicherung zurück."""
    info = json.loads((backup_dir / "sicherung.json").read_text())
    master = Path(info["master_db"])
    for suffix in ("", "-wal", "-shm"):
        saved = backup_dir / (master.name + suffix)
        live = master.with_name(master.name + suffix)
        if saved.exists():
            shutil.copy2(saved, live)
        elif suffix and live.exists():
            live.unlink()  # zur Sicherung passende Datenbank ohne neuere WAL-Reste
    for saved, original in info["anlz"].items():
        shutil.copytree(saved, original, dirs_exist_ok=True)
    return master
