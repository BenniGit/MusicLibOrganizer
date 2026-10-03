# Music Library App – Übergabe (Stand 2026-10-03, Abend)

Plan (Claude Doc): https://claude.ai/code/artifact/80f25e1b-fd5a-49fe-944d-17a5af1c5e0a
Code: dieses Verzeichnis, Branch `claude/sharp-mccarthy-frzgj7`.

## Stand

- **Netzwerk:** PyPI, Discogs-API und Beatport-API sind aus Claude Code erreichbar.
  `www.beatport.com` blockiert Cloudflare (Bot-Challenge) – wird nicht gebraucht.
- **Phase 1, erledigt:** `musiclib show/reset/restore` – vollständiger Tag-Reset für MP3
  (ID3v1, ID3v2, APEv2, auch gestapelt) und FLAC (Vorbis, Bilder, APPLICATION/CUESHEET,
  eingeschleuste ID3/APE). Prüfung nach dem Reset, Änderungsdatum bleibt, Sicherung vor
  dem ersten Schreiben, Vorschau ohne `--apply`. 14 Tests mit absichtlich verschmutzten Dateien.
- **`musiclib check-sources`:** prüft Discogs (Token, Suche) und Beatport (Client-ID,
  Login, Token, Katalogsuche), ohne Zugangsdaten auszugeben.
- **Discogs:** Token gültig, 60 Anfragen/min, Suche liefert Treffer.
- **Beatport: Login offen.** Drei Versuche mit 403 „Incorrect username or password.“
  Das alte Passwort enthielt einen Backtick und ein `"` – vermutlich beim Eintragen in die
  Umgebungsvariable verändert. Empfehlung: neues Beatport-Passwort nur aus Buchstaben/Ziffern.
  Geänderte Umgebungsvariablen sind erst in einer neuen Sitzung sichtbar.
  **Erst prüfen, ob sich die Werte geändert haben** (Länge/Zeichenklassen, ohne Ausgabe),
  dann einmal `musiclib check-sources --only beatport`. Keine wiederholten Fehlversuche
  (Kontosperre).

## Zugangsdaten

Umgebungsvariablen der Claude-Code-Umgebung: `DISCOGS_TOKEN`, `BEATPORT_USERNAME`,
`BEATPORT_PASSWORD`. Auf dem Mac später zusätzlich macOS-Schlüsselbund (noch nicht gebaut).
Nie ins Repo, in den Nextcloud-Ordner oder in den Chat.

## Entscheidungen

- Eigene App (OneTagger früher getestet: fehlende Kontrolle vor dem Schreiben).
  Vorschau + Bestätigung = Kernfunktion.
- Vor jedem Taggen kompletter Reset aller Tags (inkl. Traktor-Daten, MusicBrainz,
  Kommentare – auch eigene Notizen dürfen weg).
- Quellen: Beatport (Account ohne Abo, Zugang inoffiziell, testen) + Discogs (offizieller Token).
- Tonart im Camelot-Format (8A).
- DJ-Tags in der App mit Vorschlägen, Benjamin bestätigt: Muss = Crate (genau 1),
  Energie 1–10, Vocals ja/nein; Soll = Set-Phase (zuerst manuell, nicht aus BPM ableiten);
  Elemente optional; Stimmung gestrichen.
- Energie-Score ohne BPM (Tempo sagt nichts über Energie).
- Genre-Ordnung künftig über Tags + intelligente Playlists in rekordbox;
  Set-/Anlass-Playlists sind von der Ein-Playlist-Regel ausgenommen.
- Importdatum (rekordbox „StockDate“) muss erhalten bleiben; Datei-Änderungsdatum ebenfalls.
- Rollen: Claude baut, getestet wird gemeinsam.

## Umgebung

- Arbeitsordner: `/Users/benjamin/Nextcloud/Music/LibOrganized` (Kopie der Library, Backup existiert).
- rekordbox 7 nutzt noch den alten Ordner `/Users/benjamin/Nextcloud/Music/Library` – gleiche
  Unterordner-Struktur, Umstellung = Pfad-Tausch (Library → LibOrganized) ohne Neuimport.
- master.db: `/Users/benjamin/Library/Pioneer/rekordbox/master.db` (SQLCipher 4, Passphrase-Key
  wie in pyrekordbox; eigene Entschlüsselung mit Python + cryptography funktionierte).
  Nur Kopien lesen, schreiben zunächst per rekordbox-XML.
- Die Musikdateien liegen nur auf dem Mac, nicht in der Cloud-Umgebung. Tests an echten
  Dateien laufen dort (Repo klonen, siehe README).

## Inventur LibOrganized

- 2.561 Dateien (2.557 MP3 ~320 kbps, 4 FLAC), 39 GB. Main 2.081, Tagged 202, Sorted 153,
  #Bandcamp 36, #EPs 35, #DigitalizedVinylOnly 27, #Soundcloud 18, #Theo Hermann 9.
- Genre fehlt bei 423, BPM/Key bei ~25 %. 1.696 Dateien mit Fremdfeldern (203 Arten, Traktor 1.237).
- 103 vermutlich hochkonvertierte MP3s (kein Signal 17–19,5 kHz), 85 davon in Main.
- Duplikat-Verdacht: 4 Gruppen, mind. 2 echt (z. B. Roman Flügel – Wilkie in Main).

## rekordbox

- 2.599 Tracks, 54 Playlists (keine intelligenten), 791 Tracks in mehreren Playlists;
  UNSORTED 528, NOTSURE 82.
- My Tags ungenutzt (nur Vorlage). Ratings 851, Farben 198, Cues 30 – erhalten.

## Nächste Schritte (Phase 1)

1. Beatport-Login in neuer Sitzung testen (siehe oben).
2. Scanner: Suchbegriffe aus Dateiname und Alt-Tags (Interpret/Titel/Mix, Präfixe säubern).
3. Discogs-Provider (+ Beatport-Provider, sobald Login geht) hinter gemeinsamer Schnittstelle,
   Antworten in SQLite zwischenspeichern.
4. Treffer-Bewertung (≥ 90 % auto, 60–89 % Prüfliste, < 60 % manuell), Vorschau alt/neu.
5. Schreiben: Reset → neue Felder → erneut lesen und vergleichen; Quelle + Release-ID vermerken.
6. Benjamin testet Reset-Vorschau und Tagging an ~20 Kopien auf dem Mac.
