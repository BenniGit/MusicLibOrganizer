"""Library prüfen (ändert nichts).

    musiclib-pruefen ~/Nextcloud/Music/LibOrganized
    musiclib-pruefen ~/Nextcloud/Music/LibOrganized --alt ~/Nextcloud/Music/Library --rekordbox
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import audit
from .backup import data_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="musiclib-pruefen", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ordner", type=Path, help="die sortierte Library")
    ap.add_argument("--alt", type=Path, help="alte Library (zählt, was dort noch liegt)")
    ap.add_argument("--rekordbox", action="store_true", help="auch Rekordbox prüfen (nur lesend)")
    ap.add_argument("--db", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--bericht", type=Path, help="Bericht hierhin speichern (Standard: App-Datenordner)")
    args = ap.parse_args(argv)
    root = args.ordner.expanduser()
    if not root.is_dir():
        print(f"Ordner nicht gefunden: {root}")
        return 1

    def progress(i, n, _p):
        if i % 100 == 0 or i == n:
            print(f"\r{i}/{n} Dateien gelesen", end="", file=sys.stderr, flush=True)

    files = audit.collect(root, progress)
    print(file=sys.stderr)
    rb = None
    if args.rekordbox or args.db:
        try:
            rb = audit.rekordbox_paths(args.db)
        except Exception as e:
            print(f"Rekordbox konnte nicht gelesen werden: {e}", file=sys.stderr)
    migrated = None
    if args.alt:
        from .journal import Journal

        j = Journal()
        migrated = {m.src for m in j.all()}
        j.close()
    text = audit.render(audit.build_report(root, files, rb, args.alt.expanduser() if args.alt else None, migrated))
    out = args.bericht or data_dir() / "berichte" / f"library-{datetime.now():%Y-%m-%d_%H-%M}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Bericht gespeichert: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
