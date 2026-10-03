# MusicLibOrganizer

Desktop-Tool (Python + Qt), das eine DJ-Musiksammlung aufräumt:

1. **Scannen** – findet MP3, FLAC, WAV und AIFF in einem Quellordner und liest vorhandene Tags bzw. den Dateinamen (`01 - Artist - Titel (Extended Mix).mp3`).
2. **Bei Beatport abgleichen** – sucht jeden Track über die Beatport-API (zuerst per ISRC, sonst über Artist/Titel/Mix) und bewertet die Treffer:
   - **gefunden** (≥ 85 %), **unsicher** (60–85 %), **nicht gefunden**.
   - Doppelklick auf eine Zeile öffnet die Trefferliste bzw. eine manuelle Suche.
3. **Ausführen** – für alle angehakten Einträge:
   - FLAC/WAV/AIFF werden per ffmpeg zu **MP3 CBR 320 kbit/s** konvertiert (MP3s werden nicht neu kodiert),
   - Beatport-Daten werden als ID3v2.4-Tags geschrieben: Artist, Titel (optional mit Mix-Name), Album/Release, Label, Genre, BPM, Key (Camelot oder Tonart), Release-Datum, ISRC, Remixer, Katalognummer, Cover,
   - die Datei landet nach der Vorlage in der Ziel-Bibliothek, z. B. `{genre}/{artist} - {title} ({mix})`.

Vor dem Ausführen siehst du in der Spalte **Ziel** genau, wo jede Datei landet. Im Modus *Kopieren* bleiben die Originale unverändert; im Modus *Verschieben* werden sie entfernt (auch FLAC/WAV nach erfolgreicher Konvertierung).

## Installation

Voraussetzungen: Python ≥ 3.10 und [ffmpeg](https://ffmpeg.org/download.html) im `PATH`
(Windows: `winget install ffmpeg`, macOS: `brew install ffmpeg`, Linux: Paketmanager).

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

## Beatport-Zugang

Die Anmeldedaten werden aus Umgebungsvariablen gelesen (oder beim Klick auf „Anmelden“ abgefragt):

```bash
export BEATPORT_USERNAME="dein-name"
export BEATPORT_PASSWORD="dein-passwort"
```

Das Access-Token wird im Cache-Ordner des Systems (macOS: `~/Library/Caches/musiclib/`, Windows: `%LOCALAPPDATA%\musiclib\`, Linux: `~/.cache/musiclib/`) gespeichert und automatisch erneuert. Das Passwort wird nicht gespeichert.

## Starten

```bash
musiclib-organizer      # oder: python -m musiclib
```

### Platzhalter für die Dateinamen-Vorlage

`{artist}` `{title}` `{mix}` `{genre}` `{label}` `{album}` `{year}` `{bpm}` `{key}` – ein `/` erzeugt Unterordner, leere Klammern werden entfernt.
Tracks ohne Beatport-Treffer landen mit ihren bisherigen Tags unter `_Unbekannt/`.

## Tests

```bash
pip install -e ".[dev]"
pytest                    # Live-Test gegen Beatport läuft nur, wenn die Umgebungsvariablen gesetzt sind
pytest -m "not live"      # ohne Netzwerk
```
