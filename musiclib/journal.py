"""Umzugs-Journal: welche Datei aus der alten Library liegt jetzt wo in der neuen?

Wird bei jedem Kopieren/Verschieben geschrieben und später benutzt, um in Rekordbox die Pfade
umzustellen – ohne Neuimport, damit Sterne, Cues, Playlists und Import-Datum erhalten bleiben.
"""
from __future__ import annotations

import json
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .backup import data_dir


def norm(path: str | Path) -> str:
    """Einheitliche Schreibweise für Vergleiche (macOS speichert Umlaute teils zerlegt, teils nicht)."""
    return unicodedata.normalize("NFC", str(path))


@dataclass
class Move:
    src: str
    dst: str
    created: str
    switched: str | None
    prev: list[str] = field(default_factory=list)  # frühere Ziele (erneut bearbeitete Tracks)


class Journal:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "umzug.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.execute("""CREATE TABLE IF NOT EXISTS moves (
            src TEXT PRIMARY KEY, dst TEXT NOT NULL, created TEXT NOT NULL, switched TEXT)""")
        if "prev" not in [r[1] for r in self.con.execute("PRAGMA table_info(moves)")]:
            self.con.execute("ALTER TABLE moves ADD COLUMN prev TEXT NOT NULL DEFAULT '[]'")
        self.con.commit()

    def record(self, src: Path, dst: Path, commit: bool = True) -> None:
        """Merkt sich alt → neu.

        Wird eine Datei erneut übernommen, zählt das neueste Ziel; die früheren Ziele bleiben bekannt,
        weil Rekordbox evtl. schon auf eines davon umgestellt ist. Wird eine Datei aus der neuen
        Library selbst erneut bearbeitet, wird der ursprüngliche Eintrag fortgeschrieben.
        """
        src, dst = norm(src), norm(dst)
        now = datetime.now().isoformat(timespec="seconds")
        row = self.con.execute("SELECT src, dst, prev FROM moves WHERE src=?", (src,)).fetchone()
        if row is None:
            row = self.con.execute("SELECT src, dst, prev FROM moves WHERE dst=?", (src,)).fetchone()
        if row is None:
            self.con.execute("INSERT INTO moves(src, dst, created, switched, prev) VALUES(?, ?, ?, NULL, '[]')",
                             (src, dst, now))
        else:
            key, old_dst, prev = row[0], row[1], json.loads(row[2] or "[]")
            if old_dst != dst:
                prev = [p for p in prev if p not in (old_dst, dst)] + [old_dst]
            self.con.execute("UPDATE moves SET dst=?, created=?, switched=NULL, prev=? WHERE src=?",
                             (dst, now, json.dumps(prev, ensure_ascii=False), key))
        if commit:
            self.con.commit()

    def commit(self) -> None:
        self.con.commit()

    def is_target(self, path: Path) -> bool:
        """Liegt die Datei schon als übernommene Datei in der neuen Library?"""
        return self.con.execute("SELECT 1 FROM moves WHERE dst=?", (norm(path),)).fetchone() is not None

    def target_for(self, src: Path) -> str | None:
        row = self.con.execute("SELECT dst FROM moves WHERE src=?", (norm(src),)).fetchone()
        return row[0] if row else None

    def forget(self, src: Path) -> None:
        self.con.execute("DELETE FROM moves WHERE src=?", (norm(src),))
        self.con.commit()

    def all(self) -> list[Move]:
        rows = self.con.execute("SELECT src, dst, created, switched, prev FROM moves ORDER BY created")
        return [Move(*r[:4], json.loads(r[4] or "[]")) for r in rows]

    def mark_switched(self, srcs: list[str]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self.con.executemany("UPDATE moves SET switched=? WHERE src=?", [(now, s) for s in srcs])
        self.con.commit()

    def close(self) -> None:
        self.con.close()
