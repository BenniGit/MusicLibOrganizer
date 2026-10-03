# MusicLibOrganizer

Desktop-Tool (Python + Qt), das eine DJ-Musiksammlung aufräumt:

1. **Scannen** – findet MP3, FLAC, WAV und AIFF in einem Quellordner und liest vorhandene Tags bzw. den Dateinamen (`01 - Artist - Titel (Extended Mix).mp3`).
2. **Abgleichen** – sucht jeden Track in mehreren Quellen, in fester Reihenfolge:
   1. **Beatport** (zuerst per ISRC, sonst über Artist/Titel/Mix) – ein sicherer Beatport-Treffer hat immer Vorrang,
   2. **Discogs**, falls Beatport nichts Sicheres liefert,
   3. **Bandcamp**, falls auch Discogs nichts Sicheres liefert.

   Jeder Treffer bekommt einen Score: **gefunden** (≥ 85 %), **unsicher**, **nicht gefunden**. Eine abweichende Version (z. B. Extended statt Radio Edit) gilt nie als sicher.
3. **Übernehmen**
   - **„✔ 100%-Treffer übernehmen“** verarbeitet mit einem Klick alle Tracks mit 100 %-Treffer und alle manuell bestätigten Tracks – sofern alle Pflichtfelder gefüllt sind.
   - **„Markierte ausführen“** verarbeitet alle angehakten Tracks (mit Rückfrage und Warnung bei fehlenden Angaben).

Beim Übernehmen werden FLAC/WAV/AIFF per ffmpeg zu **MP3 CBR 320 kbit/s** konvertiert (MP3s werden nicht neu kodiert), die Metadaten als ID3v2.4-Tags geschrieben (Artist, Titel, Mix, Release, Label, Genre, BPM, Key, Datum, ISRC, Remixer, Katalognummer, Cover, Quelle) und die Datei nach der gewählten Ordnerstruktur in die Ziel-Bibliothek gelegt.

## Treffer prüfen und korrigieren

- **Doppelklick** auf eine Zeile: alle Treffer aller Quellen ansehen, manuell suchen (auch gezielt nur in einer Quelle), im Browser öffnen, übernehmen.
- **Rechtsklick → Metadaten bearbeiten…**: kleine Korrekturen (Genre, Label, Mix, Datum, Key …) vor dem Schreiben. Bei Tracks ohne Treffer lassen sich die Daten auch komplett manuell erfassen.
- Die Spalte **Fehlt** zeigt fehlende Pflichtfelder; über **Anzeigen** lässt sich die Liste filtern (z. B. „Unvollständig“, „Unsicher“, „Bereit zur Übernahme“).

## Einstellungen (⚙ bzw. Menü Datei → Einstellungen)

- **Ordnerstruktur** – Vorlagen zur Auswahl, mit Live-Vorschau:

  | Vorlage | Beispiel |
  |---|---|
  | Genre (empfohlen) | `Tech House/Fisher - Losing It (Original Mix).mp3` |
  | Genre / Label | `Tech House/Catch & Release/Fisher - Losing It (Original Mix).mp3` |
  | Import-Monat / Genre | `2026-10/Tech House/Fisher - Losing It (Original Mix).mp3` |
  | Label / Release | `Catch & Release/2018 - Losing It/Fisher - Losing It (Original Mix).mp3` |
  | Flach | `Fisher - Losing It (Original Mix).mp3` |

  Eigene Muster sind möglich mit `{artist}` `{title}` `{mix}` `{genre}` `{label}` `{album}` `{year}` `{bpm}` `{key}` `{added}`; `/` erzeugt Unterordner. Außerdem: Kopieren oder Verschieben.
- **Tags & Pflichtfelder** – Key-Format (Camelot/Tonart), Mix-Name im Titel, Cover, welche Felder Pflicht sind, und ein **Ersatz-Label** (Standard „Self-Released“) für Tracks ohne Label.
- **Quellen** – Beatport-Zugang, Discogs-Token, Bandcamp an/aus, Schwellen für „gefunden“ und „100 %-Übernahme“.

## Installation

Voraussetzungen: Python ≥ 3.10 und [ffmpeg](https://ffmpeg.org/download.html) im `PATH`
(Windows: `winget install ffmpeg`, macOS: `brew install ffmpeg`, Linux: Paketmanager).

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

## Zugangsdaten

Werden aus Umgebungsvariablen gelesen oder in den Einstellungen eingetragen:

```bash
export BEATPORT_USERNAME="dein-name"
export BEATPORT_PASSWORD="dein-passwort"
export DISCOGS_TOKEN="dein-token"    # https://www.discogs.com/settings/developers
```

Das Beatport-Passwort wird nie gespeichert; das Access-Token liegt im Cache-Ordner des Systems (macOS: `~/Library/Caches/musiclib/`, Windows: `%LOCALAPPDATA%\musiclib\`, Linux: `~/.cache/musiclib/`). Ein in den Einstellungen eingetragenes Discogs-Token wird in den App-Einstellungen gespeichert. Bandcamp braucht keinen Zugang.

## Starten

```bash
musiclib-organizer      # oder: python -m musiclib
```

## Tests

```bash
pip install -e ".[dev]"
pytest                    # Live-Tests gegen Beatport/Discogs laufen nur, wenn Zugangsdaten gesetzt sind
pytest -m "not live"      # ohne Netzwerk
```
