"""Umzugs-Journal: welche Datei aus der alten Library liegt jetzt wo in der neuen?

Wird bei jedem Kopieren/Verschieben geschrieben und später benutzt, um in Rekordbox die Pfade
umzustellen – ohne Neuimport, damit Sterne, Cues, Playlists und Import-Datum erhalten bleiben.
"""
from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass
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


class Journal:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "umzug.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.execute("""CREATE TABLE IF NOT EXISTS moves (
            src TEXT PRIMARY KEY, dst TEXT NOT NULL, created TEXT NOT NULL, switched TEXT)""")
        self.con.commit()

    def record(self, src: Path, dst: Path) -> None:
        """Merkt sich alt → neu. Wird eine Datei erneut übernommen, zählt das neueste Ziel."""
        self.con.execute(
            "INSERT INTO moves(src, dst, created, switched) VALUES(?, ?, ?, NULL) "
            "ON CONFLICT(src) DO UPDATE SET dst=excluded.dst, created=excluded.created, switched=NULL",
            (norm(src), norm(dst), datetime.now().isoformat(timespec="seconds")))
        self.con.commit()

    def target_for(self, src: Path) -> str | None:
        row = self.con.execute("SELECT dst FROM moves WHERE src=?", (norm(src),)).fetchone()
        return row[0] if row else None

    def forget(self, src: Path) -> None:
        self.con.execute("DELETE FROM moves WHERE src=?", (norm(src),))
        self.con.commit()

    def all(self) -> list[Move]:
        return [Move(*r) for r in self.con.execute("SELECT src, dst, created, switched FROM moves ORDER BY created")]

    def mark_switched(self, srcs: list[str]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self.con.executemany("UPDATE moves SET switched=? WHERE src=?", [(now, s) for s in srcs])
        self.con.commit()

    def close(self) -> None:
        self.con.close()
