# musiclib

Hält die MP3/FLAC-Sammlung sauber getaggt. Plan: siehe „Plan: Music Library App“ (Claude Docs).

## Stand: Phase 1, Schritt 1 – vollständiger Tag-Reset

- **MP3:** entfernt ID3v1, ID3v2 (alle Frames inkl. Cover, Kommentare, Traktor-/Serato-Daten,
  ReplayGain, MusicBrainz-IDs) und APEv2, auch wenn mehrere Tags am Dateiende gestapelt sind.
- **FLAC:** entfernt Vorbis-Comments, Bild-, APPLICATION- und CUESHEET-Blöcke sowie
  ID3-/APE-Tags, die manche Programme fälschlich in FLAC schreiben.
- Audiodaten bleiben bitgleich (per Test geprüft), das Änderungsdatum der Datei bleibt erhalten.
- Nach jedem Reset wird die Datei neu gelesen; bleibt etwas übrig, bricht die Datei mit Fehler ab.
- Vor dem ersten Schreiben wird das Original gesichert (nie überschrieben, wiederherstellbar).

## Benutzung

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

.venv/bin/musiclib show  "Datei.mp3"                       # vorhandene Tags anzeigen
.venv/bin/musiclib reset ~/Nextcloud/Music/LibOrganized/Test  # Vorschau, ändert nichts
.venv/bin/musiclib reset ~/Nextcloud/Music/LibOrganized/Test \
    --backup-dir ~/MusicBackup --apply                         # sichern + zurücksetzen
.venv/bin/musiclib restore ~/Nextcloud/Music/LibOrganized/Test --backup-dir ~/MusicBackup
```

Tests (brauchen `ffmpeg`): `.venv/bin/pytest`
