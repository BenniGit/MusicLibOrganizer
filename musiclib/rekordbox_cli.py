"""Rekordbox auf die neue Library umstellen – Sterne, Cues, Playlists und Import-Datum bleiben erhalten.

    musiclib-rekordbox status              # zeigt, was umgestellt würde (ändert nichts)
    musiclib-rekordbox umstellen           # Probelauf
    musiclib-rekordbox umstellen --anwenden   # sichert, stellt um, prüft (Rekordbox muss geschlossen sein)
    musiclib-rekordbox zurueck             # letzte Sicherung zurückspielen
    musiclib-rekordbox umbenennen ALT NEU  # Library-Ordner umbenennen und Rekordbox nachziehen
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import rekordbox_db as rbdb
from .journal import Journal


def _print_plan(steps: list[rbdb.Step], show: int = 8) -> None:
    print(rbdb.summary(steps, show))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="musiclib-rekordbox", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, help="Pfad zur master.db (Standard: die der installierten Rekordbox)")
    ap.add_argument("--journal", type=Path, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="zeigen, was umgestellt würde")
    p = sub.add_parser("umstellen", help="Pfade in Rekordbox auf die neue Library umstellen")
    p.add_argument("--anwenden", action="store_true", help="wirklich ändern (sonst nur Probelauf)")
    p.add_argument("--sicherungen", type=Path, help=argparse.SUPPRESS)
    u = sub.add_parser("umbenennen", help="Library-Ordner umbenennen und Rekordbox umstellen")
    u.add_argument("alt", type=Path)
    u.add_argument("neu", type=Path)
    u.add_argument("--sicherungen", type=Path, help=argparse.SUPPRESS)
    z = sub.add_parser("zurueck", help="Sicherung zurückspielen")
    z.add_argument("sicherung", nargs="?", type=Path, help="Sicherungsordner (Standard: die neueste)")
    z.add_argument("--sicherungen", type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.cmd == "zurueck":
        b = args.sicherung or rbdb.latest_backup(args.sicherungen)
        if not b:
            print("Keine Sicherung gefunden.")
            return 1
        if rbdb.rekordbox_running():
            print("Bitte zuerst Rekordbox beenden.")
            return 1
        master = rbdb.restore(b)
        print(f"Sicherung {b.name} zurückgespielt nach {master}.")
        return 0

    if args.cmd == "umbenennen":
        from . import relocate

        if rbdb.rekordbox_running():
            print("Bitte zuerst Rekordbox beenden.")
            return 1
        err = relocate.check(args.alt.expanduser(), args.neu.expanduser())
        if err:
            print(err)
            return 1
        j = Journal(args.journal)
        try:
            n = relocate.rename_library(args.alt.expanduser(), args.neu.expanduser(), j)
        finally:
            j.close()
        print(f"Umbenannt: {args.alt} → {args.neu} ({n} Dateien). Stelle Rekordbox um …\n")
        args.cmd, args.anwenden = "umstellen", True

    journal = Journal(args.journal)
    try:
        db = rbdb.open_db(args.db)
    except rbdb.RekordboxError as e:
        print(e)
        return 1
    try:
        steps = rbdb.plan(db, journal)
        _print_plan(steps)
        if args.cmd == "status" or not getattr(args, "anwenden", False):
            if args.cmd == "umstellen":
                print("\nProbelauf – nichts geändert. Zum Ausführen:  musiclib-rekordbox umstellen --anwenden")
            return 0
        if not any(s.action == rbdb.SWITCH for s in steps):
            print("\nNichts umzustellen.")
            journal.mark_switched([s.key or s.old for s in steps if s.action == rbdb.ALREADY])
            return 0
        if rbdb.rekordbox_running():
            print("\nRekordbox läuft noch – bitte beenden und erneut starten.")
            return 1
        backup_dir = rbdb.backup(db, steps, args.sicherungen)
        print(f"\nSicherung: {backup_dir}")
        warnings: list[str] = []
        n = rbdb.apply(db, steps, journal, warnings)
        problems = rbdb.verify(db, steps)
        print(f"{n} Tracks umgestellt.")
        for w in warnings[:20]:
            print("  Hinweis:", w)
        if problems:
            print(f"⚠ {len(problems)} Probleme:")
            for p in problems[:20]:
                print("  ", p)
            print("Zurück zum vorherigen Stand:  musiclib-rekordbox zurueck")
            return 2
        print("Alles geprüft ✔  Rekordbox kann wieder gestartet werden.")
        return 0
    finally:
        db.close()
        journal.close()


if __name__ == "__main__":
    sys.exit(main())
