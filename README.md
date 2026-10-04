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

Beim Übernehmen werden FLAC/WAV/AIFF per ffmpeg zu **MP3 CBR 320 kbit/s** konvertiert (MP3s werden nicht neu kodiert), die Metadaten als ID3v2.4-Tags geschrieben und die Datei nach der gewählten Ordnerstruktur in die Ziel-Bibliothek gelegt.

### Geschriebene Tags

Artist, Titel (optional mit Mix), Album-Artist, Release/Album, Tracknummer (z. B. `3/12`), Disc, Label, Genre, BPM, Key, Release-Datum, ISRC, Remixer, Cover sowie als eigene Felder Mix-Name, Katalognummer, Sub-Genre, Quelle und Quellen-ID.
Album-Artist und Tracknummer kommen aus dem Release (Beatport: eigene Abfrage pro Release, Compilations mit mehr als drei Artists werden zu „Various Artists“).

### Eigene Tags für Rekordbox (#Hashtags im Kommentar)

Rekordbox liest „My Tags“ nicht aus Dateien. Deshalb schreibt die App deine eigenen Tags als **#Hashtags in den Kommentar**, z. B. `#peaktime #vocal #bootleg`.
In Rekordbox: Spalte „Kommentare“ einblenden, nach `#peaktime` suchen oder eine **Intelligente Playlist** mit „Kommentare enthält #peaktime“ anlegen. Bei bereits importierten Tracks nach Änderungen: Rechtsklick → Tag-Informationen neu laden.

- Tags vergeben: im Metadaten-Editor oder per **Rechtsklick → Tags setzen…** (auch für viele Tracks auf einmal).
- Tag-Liste in den Einstellungen → „Eigene Tags“ (eine Gruppe pro Zeile, z. B. `Situation: Warm-up, Peak Time, Closing`).
- Automatische Tags: `#bootleg` für inoffizielle Tracks (an), Sub-Genre (aus).
- Vorhandene #Tags im Kommentar einer Datei werden beim Scannen erkannt und übernommen.

### Vorhandene Tags

Standardmäßig werden **alle vorhandenen Tags entfernt** (ID3v1, ID3v2, APE) und nur die neuen geschrieben. Vorher werden die alten Tags gesichert – eine JSON-Zeile pro Datei im App-Datenordner unter `tag-backups/`
(macOS: `~/Library/Application Support/MusicLibOrganizer/`, Windows: `%APPDATA%\MusicLibOrganizer\`, Linux: `~/.local/share/musiclib/`).

Im Metadaten-Editor steht neben jedem Feld der **bisherige Wert aus der Datei** – ein Klick übernimmt ihn. Alle übrigen vorhandenen Tags (Kommentar, Komponist, Rating …) werden darunter aufgelistet und können pro Track **zum Behalten angehakt** werden.
Hinweis: Auch Cue-Punkte von Serato/Traktor, die in Tags gespeichert sind, werden entfernt, wenn du sie nicht anhakst. Rekordbox speichert Cues in seiner eigenen Datenbank und ist davon nicht betroffen.

## Umzug in eine neue Library – Rekordbox bleibt erhalten

Die App kann die Sammlung **nach und nach** in eine neue Library kopieren (z. B. von `Music/Library` nach
`Music/LibOrganized`), während Rekordbox weiter mit den alten Dateien arbeitet. Danach werden in Rekordbox nur die
**Dateipfade** umgestellt – Sterne, Farben, Cues, Beatgrids, Playlists, History und Import-Datum bleiben erhalten,
es gibt keinen Neuimport.

1. **Übernehmen:** Quelle = alte Library, Ziel = neue Library, Modus „Kopieren“. Jede übernommene Datei wird im
   Umzugs-Journal vermerkt (alter ↔ neuer Pfad). Beim nächsten Scan erscheinen schon übernommene Dateien als „erledigt“.
2. **Umstellen:** Rekordbox beenden, dann Menü **Rekordbox → Rekordbox auf neue Library umstellen…** (oder
   `musiclib-rekordbox umstellen --anwenden`). Vorher werden `master.db` und die Analyse-Dateien der betroffenen Tracks
   gesichert, danach wird geprüft, dass jeder umgestellte Track seine Datei findet. Das geht beliebig oft – jedes Mal
   werden die seitdem übernommenen Dateien umgestellt.
3. **Zurück:** Menü **Rekordbox → Letzte Sicherung zurückspielen…** (oder `musiclib-rekordbox zurueck`).

Hinweise: Tracks, deren Format sich ändert (FLAC → MP3), werden nicht automatisch umgestellt, sondern im Status
aufgeführt. Titel/Artist usw. zeigt Rekordbox aus der eigenen Datenbank – nach dem Umstellen in Rekordbox die Tracks
markieren und „Tag-Informationen neu laden“, um die neuen Tags zu übernehmen. Der Zugriff auf die `master.db` nutzt
[pyrekordbox](https://github.com/dylanljones/pyrekordbox) und ist von Pioneer nicht offiziell unterstützt.

```bash
musiclib-rekordbox status                  # was würde umgestellt (ändert nichts)
musiclib-rekordbox umstellen --anwenden    # sichern, umstellen, prüfen
musiclib-rekordbox zurueck                 # letzte Sicherung zurückspielen
```

## Treffer prüfen und korrigieren

- **Doppelklick** auf eine Zeile: alle Treffer aller Quellen ansehen, manuell suchen (auch gezielt nur in einer Quelle), im Browser öffnen, übernehmen.
- **Per URL übernehmen**, wenn die Suche nichts findet: im Doppelklick-Fenster eine URL ins Suchfeld einfügen (statt eines Suchbegriffs) oder **Rechtsklick → Von URL übernehmen…**. Unterstützt werden Beatport (Track/Release), Discogs (Release/Master), Bandcamp (Track/Album, auch mit eigener Domain) und SoundCloud (Track/Set).
  Mehrere Dateien markieren und eine **Release-URL** angeben: jede Datei wird dem passenden Track des Releases zugeordnet – über Titel/Artist oder, bei Namen wie `01 track.wav`, über die Tracknummer.
- **Inoffizielle Tracks** (Bootlegs, Edits, Free Downloads): **Rechtsklick → Als inoffiziell erfassen** – auch für viele Tracks auf einmal. Hat der Track einen Treffer auf das Original (z. B. Beatport), kommen davon nur Artist, Titel, Genre, BPM und Key; Release, Label, ISRC und Tracknummer des Originals werden nicht übernommen, der Bootlegger aus dem Mix („Someone Bootleg“) wird Remixer. Der Track wird als eigene Single behandelt: Album = Titel inkl. Mix, Tracknummer 1/1, Album-Artist = Artist, Label = „Bootleg“ (einstellbar), Jahr = Dateidatum. Mit einer SoundCloud-URL kommen Titel, Artist, Genre, Upload-Datum und Cover direkt von SoundCloud. Beispiel:
  `Fisher/2023 - Losing It (Someone Bootleg) [Bootleg]/01 - Fisher - Losing It (Someone Bootleg).mp3`
- **Ein Release pro EP/Album:** Nach dem Abgleich prüft die App, ob Tracks derselben EP aus verschiedenen Releases oder Quellen kommen (erkannt am alten Album-Tag im selben Ordner oder am gleichen Release-Namen). Gewählt wird ein Release – bereits übernommene, dann manuell gewählte, dann Beatport, dann das mit den meisten Tracks – und die übrigen Tracks werden auf dessen Trackliste umgestellt. Geht das nicht, wird der Track „unsicher“ mit Hinweis „anderes Release als der Rest der EP“ und nicht automatisch übernommen. Wählst du für einen Track manuell ein Release, folgen die anderen Tracks der EP automatisch. Von Hand erneut prüfen: **Menü Auswahl → EPs/Alben auf ein Release angleichen**.
- **Rechtsklick → Release / Cover bearbeiten…**: mehrere Tracks markieren und die gemeinsamen Felder eines Releases auf einmal setzen (Release, Album-Artist, Label, Katalognummer, Datum, Genre, Sub-Genre, Trackanzahl, Disc). Felder, in denen sich die Tracks unterscheiden, zeigen „verschieden“ und bleiben unverändert, solange du nichts einträgst. Optional werden die Tracknummern 1 … n neu vergeben.
- **Cover:** Die Spalte **Cover** zeigt, woher das Cover kommt (Quelle, eigenes, bisheriges der Datei) – „–“ heißt: kein Cover. Ein eigenes Cover setzt du im selben Dialog: Bild wählen, Bild-URL eingeben oder ein Bild aus dem Finder bzw. Browser auf die Vorschau ziehen. Große Bilder werden auf 1400 px verkleinert. Reihenfolge beim Schreiben: eigenes Cover → Cover der Quelle → bisheriges Cover der Datei.
- **Rechtsklick → Metadaten bearbeiten…**: kleine Korrekturen (Genre, Label, Mix, Datum, Key …) vor dem Schreiben. Bei Tracks ohne Treffer lassen sich die Daten auch komplett manuell erfassen.
- Die Spalte **Fehlt** zeigt fehlende Pflichtfelder; über **Anzeigen** lässt sich die Liste filtern (z. B. „Unvollständig“, „Unsicher“, „Bereit zur Übernahme“).

## Einstellungen (⚙ bzw. Menü Datei → Einstellungen)

- **Ordnerstruktur** – Vorlagen zur Auswahl, mit Live-Vorschau:

  | Vorlage | Beispiel |
  |---|---|
  | Album-Artist / Jahr - Release [Label] (empfohlen) | `Charlotte de Witte/2021 - Formula EP [KNTXT]/01 - Charlotte de Witte - Doppler (Original Mix).mp3` |
  | Album-Artist / Release (Jahr) [Label] | `Charlotte de Witte/Formula EP (2021) [KNTXT]/01 - Charlotte de Witte - Doppler (Original Mix).mp3` |
  | Album-Artist / Release (Jahr) | `Charlotte de Witte/Formula EP (2021)/01 - Charlotte de Witte - Doppler (Original Mix).mp3` |
  | Genre / Album-Artist / Release | `Techno/Charlotte de Witte/Formula EP (2021)/01 - …` |
  | Label / Release | `KNTXT/[KNTXT010] Charlotte de Witte - Formula EP/01 - …` |
  | Genre (ein Ordner pro Genre) | `Techno/Charlotte de Witte - Doppler (Original Mix).mp3` |
  | Import-Monat / Genre | `2026-10/Techno/Charlotte de Witte - Doppler (Original Mix).mp3` |
  | Flach | `Charlotte de Witte - Doppler (Original Mix).mp3` |

  Zielpfade werden bei Bedarf automatisch gekürzt (erst der Dateiname, dann die längsten Ordnernamen), damit der vollständige Pfad höchstens **255 Zeichen** lang ist – längere Pfade importiert Rekordbox nicht.
  Eigene Muster sind möglich mit `{artist}` `{albumartist}` `{title}` `{mix}` `{track}` `{disc}` `{album}` `{genre}` `{label}` `{catno}` `{year}` `{bpm}` `{key}` `{added}`; `/` erzeugt Unterordner, leere Ordnerebenen und überflüssige Trennzeichen werden entfernt. Außerdem: Kopieren oder Verschieben.
- **Tags & Pflichtfelder** – Key-Format (Camelot/Tonart), Mix-Name im Titel, Cover, vorhandene Tags ersetzen (an/aus), welche Felder Pflicht sind (Standard: Artist, Titel, Album-Artist, Tracknummer, Album, Genre, Label, Jahr) und ein **Ersatz-Label** (Standard „Self-Released“) für Tracks ohne Label.
- **Quellen** – Beatport-Zugang, Discogs-Token, Bandcamp an/aus, Schwellen für „gefunden“ und „100 %-Übernahme“.

## Library prüfen

**Menü Datei → Library prüfen…** (oder im Terminal `musiclib-pruefen ~/Nextcloud/Music/LibOrganized --rekordbox`) liest die sortierte Library und Rekordbox nur und listet, was auffällt: fehlende Angaben und Cover, MP3s unter 320 kbit/s, Schreibvarianten (z. B. „Fisher“/„FISHER“, „Tech House“/„Tech-House“ – teilen Ordner auf), mögliche Duplikate, uneinheitliche Release-Ordner, doppelte Tracknummern, zu lange Pfade, leere Ordner, Rekordbox-Einträge ohne Datei und Dateien, die nicht in Rekordbox sind. Der Bericht wird unter `~/Library/Application Support/MusicLibOrganizer/berichte/` gespeichert.

## Schreibweisen vereinheitlichen

**Menü Datei → Schreibweisen vereinheitlichen…** findet Namen, die in der Ziel-Library unterschiedlich geschrieben sind („Omar-S“/„Omar S“, „K7 Records“/„!K7 Records“, „Tech House“/„Tech-House“, unsichtbare Zeichen oder zerlegte Umlaute) sowie den Discogs-Platzhalter „Not On Label“ (→ „Self-Released“). Pro Zeile wählst du die richtige Schreibweise; nach einer Vorschau werden die Tags neu geschrieben, Ordner und Dateinamen angepasst und alle Umbenennungen ins Umzugs-Journal eingetragen. Anschließend stellt die App auf Wunsch Rekordbox um (Sterne, Cues, Playlists bleiben). Alle alten Werte stehen im Protokoll unter `~/Library/Application Support/MusicLibOrganizer/vereinheitlichen/`.

Damit Rekordbox auch die neuen Namen anzeigt: die betroffenen Tracks markieren → Rechtsklick → „Tag-Informationen neu laden“.

## Test-Werkzeug: Energie schätzen (experimentell)

Misst bei jedem Track Hi-Hat/Percussion-Aktivität, Bewegung im Spektrum, Helligkeit, Bass-Anteil, Dynamik und BPM
und schätzt daraus eine Energie von ★1–5. Mit deinen eigenen Sterne-Bewertungen zeigt es, wie gut das klappt.

```bash
# Rekordbox: Datei → Bibliothek exportieren → im XML-Format exportieren
musiclib-energie --xml ~/Desktop/rekordbox.xml --list-playlists
musiclib-energie --xml ~/Desktop/rekordbox.xml --playlist "Energie"     # mehrfach möglich
# oder Ordner mit Unterordnern 1 … 5 (= Sterne):
musiclib-energie --folder ~/Music/Energie-Test
```

Ausgabe: Trefferquote im Vergleich zu deinen Sternen (ungelernt vs. an deinen Sternen gelernt), welche Messwerte
mit deinen Sternen zusammenhängen, die größten Ausreißer und eine CSV mit allen Messwerten (`energie-test.csv`).
Messwerte werden zwischengespeichert – ein zweiter Lauf ist sofort fertig.

**Mit KI (`--ki`)**: zusätzlich ein KI-„Klang-Fingerabdruck“ (Essentia, Discogs-EffNet) und fertige KI-Einschätzungen
(Engagement, Tanzbarkeit, Aggressivität, Party-Stimmung, Vocal-Anteil). Installation: `pip install -e ".[ki]"`
(macOS 15+ bzw. Linux). Die Modelle (~20 MB) werden beim ersten Lauf von essentia.upf.edu geladen; alles läuft lokal.

```bash
musiclib-energie --xml ~/Desktop/rekordbox.xml --playlist "tech house" --ki
``` Liegen die Dateien inzwischen woanders
als im Export angegeben: `--path-map /Volumes/USB=/Users/ich/Music`.

## Download (Mac-App)

Die fertige App für Macs mit Apple Silicon (M1–M4) gibt es unter
**[Releases](https://github.com/BenniGit/MusicLibOrganizer/releases)** als `.dmg`:

1. DMG öffnen und `MusicLibOrganizer` in den Ordner „Programme“ ziehen.
2. ffmpeg installieren (einmalig, für die FLAC/WAV-Konvertierung): `brew install ffmpeg`
3. Beim ersten Start meldet macOS, dass der Entwickler nicht verifiziert werden kann (die App ist nicht bei Apple
   signiert). Dann: **Systemeinstellungen → Datenschutz & Sicherheit → „Dennoch öffnen“**.
   Alternativ im Terminal: `xattr -dr com.apple.quarantine /Applications/MusicLibOrganizer.app`
4. Beatport-Zugang unter ⚙ Einstellungen → Quellen eintragen; das Passwort kann im Schlüsselbund gespeichert werden.

Eine neue Version entsteht automatisch, sobald ein Versions-Tag (z. B. `v0.7.0`) gepusht wird.
Das Test-Werkzeug `musiclib-energie` ist nicht in der App enthalten – dafür weiterhin die Installation unten.

## Installation (für Entwicklung und das Test-Werkzeug)

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
