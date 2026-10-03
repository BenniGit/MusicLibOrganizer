"""Kommandozeile.

    musiclib show DATEI...                      vorhandene Tags anzeigen
    musiclib reset PFAD... --backup-dir DIR     Vorschau: was würde entfernt?
    musiclib reset PFAD... --backup-dir DIR --apply
                                                sichern, Tags entfernen, prüfen
    musiclib restore PFAD... --backup-dir DIR   aus der Sicherung zurückholen
    musiclib check-sources [--only discogs|beatport]
                                                Verbindung zu Discogs/Beatport prüfen
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from . import __version__
from .backup import ensure_backup, restore
from .reset import inspect, is_supported, reset


def iter_files(paths: list[Path]):
    """Alle unterstützten Dateien, Ordner rekursiv, sortiert."""
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and is_supported(f) and not f.name.startswith("._"):
                    yield f
        elif p.is_file() and is_supported(p):
            yield p
        elif not p.exists():
            print(f"Nicht gefunden: {p}", file=sys.stderr)


def cmd_show(args) -> int:
    for f in iter_files(args.paths):
        inv = inspect(f)
        print(f)
        for line in inv.summary() or ["(keine Tags)"]:
            print(f"  {line}")
    return 0


def cmd_reset(args) -> int:
    files = list(iter_files(args.paths))
    if args.apply and args.backup_dir is None:
        print("--apply braucht --backup-dir (Sicherung vor dem ersten Schreiben).", file=sys.stderr)
        return 2

    dirty, failed = 0, 0
    fields: Counter[str] = Counter()
    for f in files:
        try:
            inv = inspect(f)
            if inv.is_clean:
                continue
            dirty += 1
            fields.update(set(inv.id3v2) | {f"APE:{k}" for k in inv.ape} | set(inv.vorbis))
            if args.verbose or not args.apply:
                print(f)
                for line in inv.summary():
                    print(f"  {line}")
            if args.apply:
                ensure_backup(f, args.backup_dir)
                reset(f)
        except Exception as e:  # eine kaputte Datei stoppt nicht den Lauf
            failed += 1
            print(f"FEHLER {f}: {e}", file=sys.stderr)

    verb = "zurückgesetzt" if args.apply else "würden zurückgesetzt"
    print(f"\n{len(files)} Dateien geprüft, {dirty - failed} {verb}, {failed} Fehler.")
    if fields and not args.apply:
        print("Häufigste Felder:", ", ".join(f"{k} ({n})" for k, n in fields.most_common(10)))
        print("Vorschau – nichts geändert. Zum Ausführen --apply angeben.")
    return 1 if failed else 0


def cmd_restore(args) -> int:
    missing = 0
    for f in iter_files(args.paths):
        if restore(f, args.backup_dir):
            print(f"wiederhergestellt: {f}")
        else:
            missing += 1
            print(f"keine Sicherung: {f}", file=sys.stderr)
    return 1 if missing else 0


def cmd_check_sources(args) -> int:
    from .check_sources import run  # importiert requests erst bei Bedarf

    checks = run(args.only)
    for c in checks:
        print(f"{'OK  ' if c.ok else 'FEHL'}  {c.name}: {c.detail}")
    return 0 if all(c.ok for c in checks) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="musiclib", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("show", help="vorhandene Tags anzeigen")
    p.add_argument("paths", nargs="+", type=Path)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("reset", help="alle Tags entfernen (ohne --apply nur Vorschau)")
    p.add_argument("paths", nargs="+", type=Path)
    p.add_argument("--backup-dir", type=Path, help="Ordner für die Sicherung der Originale")
    p.add_argument("--apply", action="store_true", help="wirklich schreiben")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("restore", help="Dateien aus der Sicherung zurückholen")
    p.add_argument("paths", nargs="+", type=Path)
    p.add_argument("--backup-dir", type=Path, required=True)
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("check-sources", help="Verbindung zu Discogs und Beatport prüfen")
    p.add_argument("--only", choices=["discogs", "beatport"])
    p.set_defaults(func=cmd_check_sources)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
