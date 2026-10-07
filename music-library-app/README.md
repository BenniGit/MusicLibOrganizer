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

## Mac-App (DMG)

Jeder Push baut auf GitHub Actions (macOS, Apple Silicon) die App und ein DMG:
**Releases** → „MusicLib Organizer (…)“ → `MusicLib-Organizer-<version>-arm64.dmg`.

1. DMG öffnen, „MusicLib Organizer“ auf „Programme“ ziehen.
2. Erster Start: Die App ist nicht von Apple notarisiert. Rechtsklick → **Öffnen**, oder
   Systemeinstellungen → Datenschutz & Sicherheit → **Trotzdem öffnen**.
3. Musikordner und Sicherungsordner wählen, „Reset-Vorschau“ ändert nichts.
   „Tags zurücksetzen …“ fragt vorher nach. Zugangsdaten landen im macOS-Schlüsselbund.

Lokal bauen (auf dem Mac): `pip install -e '.[app]' && ./packaging/build_macos.sh`.
Icon ändern: `packaging/icon.svg` bearbeiten, dann `python packaging/make_icon.py`.

## Benutzung (Kommandozeile)

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

.venv/bin/musiclib show  "Datei.mp3"                       # vorhandene Tags anzeigen
.venv/bin/musiclib reset ~/Nextcloud/Music/LibOrganized/Test  # Vorschau, ändert nichts
.venv/bin/musiclib reset ~/Nextcloud/Music/LibOrganized/Test \
    --backup-dir ~/MusicBackup --apply                         # sichern + zurücksetzen
.venv/bin/musiclib restore ~/Nextcloud/Music/LibOrganized/Test --backup-dir ~/MusicBackup
```

Verbindung zu den Quellen prüfen (liest `DISCOGS_TOKEN`, `BEATPORT_USERNAME`,
`BEATPORT_PASSWORD` aus der Umgebung, gibt sie nie aus):

```sh
.venv/bin/musiclib check-sources                 # beide
.venv/bin/musiclib check-sources --only beatport
```

Tests (brauchen `ffmpeg`): `.venv/bin/pytest`
