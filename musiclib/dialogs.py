"""Dialoge der GUI: Einstellungen, Trefferauswahl und Metadaten-Editor."""
from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
    QSpinBox, QScrollArea, QFrame,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QTabWidget, QVBoxLayout, QWidget,
)

from .manual import meta_from_local, split_number  # noqa: F401  (meta_from_local: Re-Export)
from . import credentials, hashtags
from .matcher import rank
from .urlimport import load_url, looks_like_url
from .models import Candidate, LibraryItem, LocalTrack, TrackMeta
from .organizer import PLACEHOLDERS, target_path, validate_template
from .settings import REQUIRED_FIELD_CHOICES, TEMPLATE_PRESETS, AppSettings
from .tagger import CAMELOT_TO_KEY

CUSTOM_PRESET = "Eigene Vorlage"


# ---------------------------------------------------------------------------- Einstellungen
class SettingsDialog(QDialog):
    """Alle Optionen an einem Ort, in Reitern gruppiert."""

    def __init__(self, parent, settings: AppSettings, beatport_user: str, beatport_password: str):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.resize(640, 520)
        self._settings = settings
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        tabs.addTab(self._folder_tab(settings), "Ordnerstruktur")
        tabs.addTab(self._tags_tab(settings), "Tags && Pflichtfelder")
        tabs.addTab(self._hashtags_tab(settings), "Eigene Tags")
        tabs.addTab(self._sources_tab(settings, beatport_user, beatport_password), "Quellen")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update_preview()

    # --- Reiter
    def _folder_tab(self, s: AppSettings) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.preset = QComboBox()
        self.preset.addItems(list(TEMPLATE_PRESETS) + [CUSTOM_PRESET])
        current = next((k for k, v in TEMPLATE_PRESETS.items() if v == s.template), CUSTOM_PRESET)
        self.preset.setCurrentText(current)
        self.preset.currentTextChanged.connect(self._preset_changed)
        form.addRow("Vorlage", self.preset)

        self.template = QLineEdit(s.template)
        self.template.textChanged.connect(self._template_edited)
        form.addRow("Muster", self.template)
        hint = QLabel("Platzhalter: " + " ".join("{" + p + "}" for p in PLACEHOLDERS)
                      + "<br>„/“ erzeugt Unterordner, leere Klammern werden entfernt. "
                        "<code>{added}</code> = Import-Monat (z. B. 2026-10).")
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        form.addRow("", hint)

        self.preview = QLabel()
        self.preview.setTextFormat(Qt.RichText)
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Vorschau", self.preview)

        mode = QGroupBox("Beim Ausführen")
        ml = QVBoxLayout(mode)
        self.copy_radio = QRadioButton("Kopieren – Originale bleiben unverändert liegen")
        self.move_radio = QRadioButton("Verschieben – Originale werden entfernt (auch FLAC/WAV nach Konvertierung)")
        grp = QButtonGroup(self)
        grp.addButton(self.copy_radio)
        grp.addButton(self.move_radio)
        (self.move_radio if s.move else self.copy_radio).setChecked(True)
        ml.addWidget(self.copy_radio)
        ml.addWidget(self.move_radio)
        form.addRow(mode)
        return w

    def _tags_tab(self, s: AppSettings) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        self.key_combo = QComboBox()
        self.key_combo.addItem("Camelot (z. B. 8A)", "camelot")
        self.key_combo.addItem("Tonart (z. B. A Minor)", "musical")
        self.key_combo.setCurrentIndex(max(0, self.key_combo.findData(s.key_format)))
        form.addRow("Key-Format", self.key_combo)
        self.mix_check = QCheckBox("Mix-Name im Titel, z. B. „Song (Extended Mix)“")
        self.mix_check.setChecked(s.mix_in_title)
        form.addRow("", self.mix_check)
        self.hide_original_check = QCheckBox("„Original Mix“ weglassen (nur andere Versionen wie Extended Mix, Remix, Dub stehen im Titel)")
        self.hide_original_check.setToolTip("Der Mix-Name bleibt im Tag MIX erhalten.")
        self.hide_original_check.setChecked(s.hide_original_mix)
        self.hide_original_check.toggled.connect(lambda _on: self._update_preview())
        form.addRow("", self.hide_original_check)
        self.cover_check = QCheckBox("Cover einbetten")
        self.cover_check.setChecked(s.embed_cover)
        form.addRow("", self.cover_check)
        self.clean_check = QCheckBox("Vorhandene Tags komplett ersetzen (alte Tags werden vorher gesichert)")
        self.clean_check.setToolTip("Entfernt alle bisherigen Tags. Einzelne Tags kannst du pro Track im "
                                    "Metadaten-Editor behalten. Die alten Tags landen als Backup im App-Datenordner.")
        self.clean_check.setChecked(s.clean_tags)
        form.addRow("", self.clean_check)
        lay.addLayout(form)

        req = QGroupBox("Pflichtfelder – Tracks ohne diese Angaben gelten als „unvollständig“")
        grid = QGridLayout(req)
        self.required_checks: dict[str, QCheckBox] = {}
        for i, (key, label) in enumerate(REQUIRED_FIELD_CHOICES.items()):
            cb = QCheckBox(label)
            cb.setChecked(key in s.required_fields)
            self.required_checks[key] = cb
            grid.addWidget(cb, i // 3, i % 3)
        lay.addWidget(req)

        lf = QFormLayout()
        self.label_fallback = QLineEdit(s.label_fallback)
        self.label_fallback.setPlaceholderText("leer lassen = kein Ersatz")
        lf.addRow("Ersatz, wenn kein Label", self.label_fallback)
        note = QLabel("Viele Tracks erscheinen ohne Label (Eigenveröffentlichung, Discogs: „Not On Label“). "
                      "Dann wird dieser Text als Label eingetragen und das Pflichtfeld gilt als erfüllt.")
        note.setWordWrap(True)
        lf.addRow("", note)
        self.unofficial_label = QLineEdit(s.unofficial_label)
        lf.addRow("Label für inoffizielle Tracks", self.unofficial_label)
        note2 = QLabel("Wird bei „Als inoffiziell erfassen“ und für SoundCloud-URLs ohne Label eingetragen "
                       "(z. B. Bootleg, White Label, SoundCloud).")
        note2.setWordWrap(True)
        lf.addRow("", note2)
        lay.addLayout(lf)
        lay.addStretch()
        return w

    def _hashtags_tab(self, s: AppSettings) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        intro = QLabel(
            "Rekordbox liest „My Tags“ nicht aus Dateien. Deshalb schreibt die App deine Tags als "
            "<b>#Hashtags in den Kommentar</b>, z. B. <code>#peaktime #vocal</code>.<br>"
            "In Rekordbox: Spalte „Kommentare“ einblenden, nach <code>#peaktime</code> suchen oder eine "
            "<b>Intelligente Playlist</b> mit „Kommentare enthält #peaktime“ anlegen.<br>"
            "Bei bereits importierten Tracks: Rechtsklick → Tag-Informationen neu laden.")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        lay.addWidget(intro)
        lay.addWidget(QLabel("Deine Tags – eine Gruppe pro Zeile, Format „Gruppe: Tag, Tag, Tag“:"))
        self.tag_groups = QPlainTextEdit(hashtags.groups_to_text(s.tag_groups))
        lay.addWidget(self.tag_groups, 1)
        auto = QGroupBox("Automatische Tags")
        al = QVBoxLayout(auto)
        self.auto_unofficial = QCheckBox("Inoffizielle Tracks bekommen das Label für inoffizielle Tracks als Tag (z. B. #bootleg)")
        self.auto_unofficial.setChecked(s.auto_tag_unofficial)
        self.auto_subgenre = QCheckBox("Sub-Genre als Tag (z. B. #techtrance)")
        self.auto_subgenre.setChecked(s.auto_tag_subgenre)
        al.addWidget(self.auto_unofficial)
        al.addWidget(self.auto_subgenre)
        lay.addWidget(auto)
        return w

    def _sources_tab(self, s: AppSettings, user: str, password: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        bp = QGroupBox("Beatport (wird immer zuerst gefragt – ein sicherer Treffer hat Vorrang)")
        bf = QFormLayout(bp)
        self.bp_user = QLineEdit(user)
        self.bp_password = QLineEdit(password)
        self.bp_password.setEchoMode(QLineEdit.Password)
        bf.addRow("Benutzername", self.bp_user)
        bf.addRow("Passwort", self.bp_password)
        self.bp_remember = QCheckBox("Passwort sicher im Schlüsselbund speichern")
        self.bp_remember.setChecked(credentials.keyring_available() and bool(password))
        self.bp_remember.setEnabled(credentials.keyring_available())
        if not credentials.keyring_available():
            self.bp_remember.setToolTip("Kein Schlüsselbund verfügbar – das Passwort gilt nur bis zum Beenden.")
        bf.addRow("", self.bp_remember)
        lay.addWidget(bp)

        dc = QGroupBox("Discogs")
        df = QFormLayout(dc)
        self.use_discogs = QCheckBox("Discogs verwenden, wenn Beatport keinen sicheren Treffer hat")
        self.use_discogs.setChecked(s.use_discogs)
        df.addRow(self.use_discogs)
        self.discogs_token = QLineEdit(s.discogs_token)
        self.discogs_token.setEchoMode(QLineEdit.Password)
        self.discogs_token.setPlaceholderText("aus DISCOGS_TOKEN" if os.environ.get("DISCOGS_TOKEN") else "Token einfügen")
        df.addRow("Access-Token", self.discogs_token)
        link = QLabel('<a href="https://www.discogs.com/settings/developers">Token erzeugen (discogs.com → Einstellungen → Entwickler)</a>')
        link.setOpenExternalLinks(True)
        df.addRow("", link)
        lay.addWidget(dc)

        bc = QGroupBox("Bandcamp")
        bcl = QVBoxLayout(bc)
        self.use_bandcamp = QCheckBox("Bandcamp verwenden, wenn Beatport und Discogs keinen sicheren Treffer haben")
        self.use_bandcamp.setChecked(s.use_bandcamp)
        bcl.addWidget(self.use_bandcamp)
        lay.addWidget(bc)

        th = QGroupBox("Schwellen")
        tf = QFormLayout(th)
        self.match_threshold = QSpinBox()
        self.match_threshold.setRange(50, 100)
        self.match_threshold.setSuffix(" %")
        self.match_threshold.setValue(round(s.match_threshold * 100))
        tf.addRow("„Gefunden“ ab", self.match_threshold)
        self.auto_threshold = QSpinBox()
        self.auto_threshold.setRange(50, 100)
        self.auto_threshold.setSuffix(" %")
        self.auto_threshold.setValue(round(s.auto_threshold * 100))
        tf.addRow("„100%-Treffer übernehmen“ ab", self.auto_threshold)
        lay.addWidget(th)
        lay.addStretch()
        return w

    # --- Logik
    def _preset_changed(self, name: str) -> None:
        if name in TEMPLATE_PRESETS:
            self.template.blockSignals(True)
            self.template.setText(TEMPLATE_PRESETS[name])
            self.template.blockSignals(False)
        self._update_preview()

    def _template_edited(self, text: str) -> None:
        match = next((k for k, v in TEMPLATE_PRESETS.items() if v == text), CUSTOM_PRESET)
        self.preset.blockSignals(True)
        self.preset.setCurrentText(match)
        self.preset.blockSignals(False)
        self._update_preview()

    def _update_preview(self) -> None:
        tpl = self.template.text()
        err = validate_template(tpl)
        if err:
            self.preview.setText(f'<span style="color:#cf222e">{err}</span>')
            return
        examples = [
            TrackMeta(id=1, name="Losing It", mix="Original Mix", artists=["Fisher"], release="Losing It",
                      label="Catch & Release", genre="Tech House", bpm=125, key_camelot="9B", key_name="G Major",
                      release_date="2018-07-13", catalog_number="CR001", track_number=1, track_total=1),
            TrackMeta(id=2, name="Doppler", mix="", artists=["Charlotte de Witte"], release="Formula EP",
                      label="", genre="Techno (Peak Time / Driving)", bpm=135, key_camelot="6B",
                      release_date="2021-04-29", track_number=2, track_total=3),
            TrackMeta(id=3, name="Gecko (Overdrive)", mix="Extended Mix", artists=["Oliver Heldens", "Becky Hill"],
                      release="Defected Ibiza 2019", album_artist="Various Artists", label="Defected",
                      genre="House", release_date="2019-05-24", catalog_number="DFTDDCD2", track_number=17,
                      track_total=62),
        ]
        fallback = self.label_fallback.text() if hasattr(self, "label_fallback") else ""
        lines = []
        for meta in examples:
            item = LibraryItem(LocalTrack(Path("x.mp3")), selected=meta)
            hide = getattr(self, "hide_original_check", None)
            lines.append(str(target_path(item, Path("Bibliothek"), tpl, "camelot", fallback,
                                         hide.isChecked() if hide else self._settings.hide_original_mix)))
        self.preview.setText("<br>".join(f"<code>{line}</code>" for line in lines))

    def _accept(self) -> None:
        err = validate_template(self.template.text())
        if err:
            QMessageBox.warning(self, "Einstellungen", err)
            return
        self.accept()

    def result_settings(self) -> AppSettings:
        return replace(
            self._settings,
            template=self.template.text().strip(),
            move=self.move_radio.isChecked(),
            key_format=self.key_combo.currentData(),
            mix_in_title=self.mix_check.isChecked(),
            hide_original_mix=self.hide_original_check.isChecked(),
            embed_cover=self.cover_check.isChecked(),
            clean_tags=self.clean_check.isChecked(),
            required_fields=[k for k, cb in self.required_checks.items() if cb.isChecked()],
            label_fallback=self.label_fallback.text().strip(),
            unofficial_label=self.unofficial_label.text().strip(),
            tag_groups=hashtags.parse_groups_text(self.tag_groups.toPlainText()),
            auto_tag_unofficial=self.auto_unofficial.isChecked(),
            auto_tag_subgenre=self.auto_subgenre.isChecked(),
            use_discogs=self.use_discogs.isChecked(),
            discogs_token=self.discogs_token.text().strip(),
            use_bandcamp=self.use_bandcamp.isChecked(),
            match_threshold=self.match_threshold.value() / 100,
            auto_threshold=self.auto_threshold.value() / 100,
        )

    def beatport_credentials(self) -> tuple[str, str]:
        return self.bp_user.text().strip(), self.bp_password.text()

    def remember_password(self) -> bool:
        return self.bp_remember.isChecked()


# ---------------------------------------------------------------------------- Eigene #Tags
class TagPicker(QWidget):
    """Häkchen für die eigenen Tags, gruppiert wie in den Einstellungen.

    Mit ``tristate`` (für mehrere Tracks): ■ = bei allen setzen, ☐ = bei allen entfernen, ▣ = unverändert.
    """

    def __init__(self, groups: dict[str, list[str]], states: dict[str, Qt.CheckState], tristate: bool = False):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.checks: dict[str, QCheckBox] = {}
        names = hashtags.display_names(groups)
        unknown = [t for t in states if t not in names and states[t] != Qt.Unchecked]
        all_groups = dict(groups)
        if unknown:
            all_groups["Sonstige (aus der Datei)"] = unknown
        for group, tags in all_groups.items():
            box = QGroupBox(group)
            grid = QGridLayout(box)
            for i, name in enumerate(tags):
                tok = hashtags.token(name)
                if tok in self.checks:
                    continue
                cb = QCheckBox(f"{name}  #{tok}" if tok != name else f"#{tok}")
                cb.setTristate(tristate)
                cb.setCheckState(states.get(tok, Qt.Unchecked))
                self.checks[tok] = cb
                grid.addWidget(cb, i // 3, i % 3)
            lay.addWidget(box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Weitere Tags:"))
        self.extra = QLineEdit()
        self.extra.setPlaceholderText("z. B. #festival #b2b (mit Leerzeichen oder Komma getrennt)")
        row.addWidget(self.extra, 1)
        lay.addLayout(row)

    def _extra_tokens(self) -> list[str]:
        return [t for t in (hashtags.token(p) for p in re.split(r"[\s,]+", self.extra.text())) if t]

    def selected(self) -> list[str]:
        return [t for t, cb in self.checks.items() if cb.checkState() == Qt.Checked] + self._extra_tokens()

    def changes(self) -> tuple[set[str], set[str]]:
        """(hinzufügen, entfernen) für den Mehrfach-Modus."""
        add = {t for t, cb in self.checks.items() if cb.checkState() == Qt.Checked} | set(self._extra_tokens())
        remove = {t for t, cb in self.checks.items() if cb.checkState() == Qt.Unchecked}
        return add, remove


class TagsDialog(QDialog):
    """Tags für mehrere Tracks auf einmal setzen oder entfernen."""

    def __init__(self, parent, groups: dict[str, list[str]], current: list[list[str]]):
        super().__init__(parent)
        self.setWindowTitle(f"Tags für {len(current)} Tracks")
        lay = QVBoxLayout(self)
        info = QLabel("☑ = bei allen setzen · ☐ = bei allen entfernen · ▣ = unverändert lassen")
        lay.addWidget(info)
        states: dict[str, Qt.CheckState] = {}
        for tok in {t for tags in current for t in tags} | set(hashtags.display_names(groups)):
            n = sum(tok in tags for tags in current)
            states[tok] = Qt.Checked if n == len(current) else (Qt.Unchecked if n == 0 else Qt.PartiallyChecked)
        self.picker = TagPicker(groups, states, tristate=True)
        lay.addWidget(self.picker)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


# ---------------------------------------------------------------------------- Treffer wählen
class CandidateDialog(QDialog):
    """Zeigt alle Treffer (alle Quellen) und erlaubt eine manuelle Suche."""

    def __init__(self, parent, item: LibraryItem, sources: Callable[[], list], match_threshold: float,
                 url_clients: Callable[[], dict] | None = None, initial_query: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Treffer wählen")
        self.resize(1100, 480)
        self.item = item
        self.sources = sources
        self.url_clients = url_clients or (lambda: {s.name: s for s in sources()})
        self.match_threshold = match_threshold
        self.candidates: list[Candidate] = list(item.candidates)
        self.choice: Candidate | None = None
        self.result_action = ""  # "select" | "edit" | "none"

        lay = QVBoxLayout(self)
        loc = item.local
        info = QLabel(f"<b>Datei:</b> {loc.path.name}<br><b>Erkannt:</b> {loc.artist} – {loc.title}"
                      + (f" ({loc.mix})" if loc.mix else ""))
        lay.addWidget(info)

        row = QHBoxLayout()
        self.query = QLineEdit(initial_query or " ".join(p for p in (loc.artist, loc.title, loc.mix) if p))
        self.query.setPlaceholderText("Suchbegriff – oder URL von Beatport, Discogs, Bandcamp oder SoundCloud einfügen")
        self.query.setToolTip("Statt eines Suchbegriffs kannst du eine Track- oder Release-URL einfügen "
                              "(Beatport, Discogs, Bandcamp). Die Daten werden dann direkt von der Seite gelesen.")
        self.source_combo = QComboBox()
        self.source_combo.addItem("Alle Quellen", "")
        for src in sources():
            self.source_combo.addItem(src.name, src.name)
        btn = QPushButton("Suchen / URL laden")
        btn.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        row.addWidget(self.query, 1)
        row.addWidget(self.source_combo)
        row.addWidget(btn)
        lay.addLayout(row)

        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(["Score", "Quelle", "Artist", "Titel", "Mix", "Release", "Nr.", "Label",
                                              "Genre", "Jahr", "BPM/Key"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(lambda *_: self._finish("select"))
        lay.addWidget(self.table, 1)
        self._fill()

        bb = QDialogButtonBox()
        ok = bb.addButton("Übernehmen", QDialogButtonBox.AcceptRole)
        edit = bb.addButton("Übernehmen && bearbeiten…", QDialogButtonBox.ActionRole)
        web = bb.addButton("Im Browser öffnen", QDialogButtonBox.ActionRole)
        none = bb.addButton("Kein Treffer", QDialogButtonBox.DestructiveRole)
        bb.addButton(QDialogButtonBox.Cancel)
        ok.clicked.connect(lambda: self._finish("select"))
        edit.clicked.connect(lambda: self._finish("edit"))
        web.clicked.connect(self._open_web)
        none.clicked.connect(lambda: self._finish("none"))
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _fill(self) -> None:
        self.table.setRowCount(len(self.candidates))
        for row, c in enumerate(self.candidates):
            t = c.track
            key = t.key_camelot or t.key_name
            nr = (f"{t.track_number}/{t.track_total}" if t.track_total else str(t.track_number)) if t.track_number else ""
            vals = [f"{c.score:.0%}", t.source, t.artist, t.name, t.mix, t.release, nr, t.label, t.genre, t.year,
                    " / ".join(v for v in (str(t.bpm or ""), key) if v)]
            for col, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                cell.setToolTip(t.url or v)
                self.table.setItem(row, col, cell)
        sel = 0
        if self.item.selected:
            sel = next((i for i, c in enumerate(self.candidates) if c.track.key == self.item.selected.key), 0)
        if self.candidates:
            self.table.selectRow(sel)

    def search(self) -> None:
        q = self.query.text().strip()
        if not q:
            return
        if looks_like_url(q):
            self.load_url(q)
            return
        wanted = self.source_combo.currentData()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        errors = []
        found: list[TrackMeta] = []
        try:
            for src in self.sources():
                if wanted and src.name != wanted:
                    continue
                try:
                    found += src.search_text(q)
                except Exception as e:
                    errors.append(f"{src.name}: {e}")
            self.candidates = rank(self.item.local, found, self.match_threshold)
            self._fill()
        finally:
            QApplication.restoreOverrideCursor()
        if errors:
            QMessageBox.warning(self, "Suche", "\n".join(errors))

    def load_url(self, url: str) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            tracks = load_url(url, self.url_clients())
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "URL laden", str(e))
            return
        QApplication.restoreOverrideCursor()
        self.candidates = rank(self.item.local, tracks, self.match_threshold)
        self._fill()

    def _current(self) -> Candidate | None:
        row = self.table.currentRow()
        return self.candidates[row] if 0 <= row < len(self.candidates) else None

    def _open_web(self) -> None:
        c = self._current()
        if c and c.track.url:
            QDesktopServices.openUrl(QUrl(c.track.url))

    def _finish(self, action: str) -> None:
        if action != "none":
            self.choice = self._current()
            if self.choice is None:
                return
        self.result_action = action
        self.accept()


# ---------------------------------------------------------------------------- Metadaten bearbeiten
# Felder, deren alter Wert im Editor angeboten wird (Schlüssel wie in LocalTrack.old)
MAPPED_OLD_KEYS = {"artist", "title", "mix", "remixers", "albumartist", "album", "label", "catno", "genre",
                   "subgenre", "date", "bpm", "key", "isrc", "track", "disc"}


class MetadataDialog(QDialog):
    """Kleine Korrekturen vor dem Schreiben; zeigt die bisherigen Tags der Datei zum Übernehmen."""

    def __init__(self, parent, meta: TrackMeta, settings: AppSettings, local: LocalTrack | None = None,
                 keep: set[str] | None = None, tags: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Metadaten bearbeiten")
        self.setSizeGripEnabled(True)
        self.meta = meta
        self.settings = settings
        self.old = dict(local.old) if local else {}
        # Inhalt in einem Scrollbereich – Pflichtfeld-Hinweis und Buttons bleiben immer sichtbar
        outer = QVBoxLayout(self)
        content = QWidget()
        lay = QVBoxLayout(content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        src = meta.source + (" (bearbeitet)" if meta.edited else "")
        head = QLabel(f'Quelle: <a href="{meta.url}">{src}</a>' if meta.url else f"Quelle: {src}")
        head.setOpenExternalLinks(True)
        lay.addWidget(head)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Neu</b>"), 0, 1)
        if self.old:
            grid.addWidget(QLabel("<b>Bisher in der Datei</b> (Klick = übernehmen)"), 0, 2)
        lay.addLayout(grid)
        self._row = 1

        def line(value: str, placeholder: str = "") -> QLineEdit:
            e = QLineEdit(value)
            e.setPlaceholderText(placeholder)
            e.textChanged.connect(self._update_missing)
            return e

        def spin(value: int | None, maximum: int) -> QSpinBox:
            sp = QSpinBox()
            sp.setRange(0, maximum)
            sp.setSpecialValueText("–")
            sp.setValue(int(value or 0))
            sp.valueChanged.connect(self._update_missing)
            return sp

        self.artists = line(", ".join(meta.artists), "mehrere mit Komma trennen")
        self.title = line(meta.name)
        self.mix = line(meta.mix, "z. B. Original Mix, Extended Mix")
        self.remixers = line(", ".join(meta.remixers))
        self.album_artist = line(meta.album_artist, f"leer = Artist ({meta.artist})" if meta.artist else "")
        self.release = line(meta.release)
        self.track = spin(meta.track_number, 999)
        self.total = spin(meta.track_total, 999)
        self.disc = spin(meta.disc_number, 99)
        self.label = line(meta.label, f"leer = „{settings.label_fallback}“" if settings.label_fallback else "")
        self.catno = line(meta.catalog_number)
        self.genre = line(meta.genre)
        self.sub_genre = line(meta.sub_genre)
        self.date = line(meta.release_date, "JJJJ-MM-TT oder JJJJ")
        self.isrc = line(meta.isrc)
        self.bpm = spin(meta.bpm, 300)
        self.key = QComboBox()
        self.key.setEditable(True)
        self.key.addItem("")
        for code, name in CAMELOT_TO_KEY.items():
            self.key.addItem(f"{code} – {name}", code)
        idx = self.key.findData(meta.key_camelot)
        if idx >= 0:
            self.key.setCurrentIndex(idx)
        else:
            self.key.setEditText(meta.key_camelot or meta.key_name)
        self.key.currentTextChanged.connect(self._update_missing)

        track_box = QWidget()
        tl = QHBoxLayout(track_box)
        tl.setContentsMargins(0, 0, 0, 0)
        for w, text in ((self.track, None), (self.total, "von"), (self.disc, "Disc")):
            if text:
                tl.addWidget(QLabel(text))
            tl.addWidget(w)
        tl.addStretch()

        def set_line(edit):
            return lambda v: edit.setText(v)

        def set_track(v):
            n, t = split_number(v)
            self.track.setValue(n)
            if t:
                self.total.setValue(t)

        def set_key(v):
            code = v.upper().replace(" ", "")
            i = self.key.findData(code)
            self.key.setCurrentIndex(i) if i >= 0 else self.key.setEditText(v)

        def set_bpm(v):
            try:
                self.bpm.setValue(round(float(v.replace(",", "."))))
            except ValueError:
                pass

        rows = [
            ("Artist(s)", self.artists, "artist", set_line(self.artists)),
            ("Titel", self.title, "title", set_line(self.title)),
            ("Mix", self.mix, "mix", set_line(self.mix)),
            ("Remixer", self.remixers, "remixers", set_line(self.remixers)),
            ("Album-Artist", self.album_artist, "albumartist", set_line(self.album_artist)),
            ("Release / Album", self.release, "album", set_line(self.release)),
            ("Tracknummer", track_box, "track", set_track),
            ("Label", self.label, "label", set_line(self.label)),
            ("Katalognummer", self.catno, "catno", set_line(self.catno)),
            ("Genre", self.genre, "genre", set_line(self.genre)),
            ("Sub-Genre", self.sub_genre, "subgenre", set_line(self.sub_genre)),
            ("Release-Datum", self.date, "date", set_line(self.date)),
            ("BPM", self.bpm, "bpm", set_bpm),
            ("Key", self.key, "key", set_key),
            ("ISRC", self.isrc, "isrc", set_line(self.isrc)),
        ]
        for label, widget, old_key, setter in rows:
            grid.addWidget(QLabel(label), self._row, 0)
            grid.addWidget(widget, self._row, 1)
            old = self.old.get(old_key, "")
            if old:
                b = QPushButton("← " + (old if len(old) <= 40 else old[:38] + "…"))
                b.setFlat(True)
                b.setStyleSheet("text-align: left; color: palette(link);")
                b.setToolTip(f"Bisheriger Wert: {old}\nKlicken zum Übernehmen")
                b.clicked.connect(lambda _=False, s=setter, v=old: s(v))
                grid.addWidget(b, self._row, 2)
            self._row += 1
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 2)

        tag_box = QGroupBox("Eigene Tags – landen als #Hashtags im Kommentar (in Rekordbox durchsuchbar)")
        tl2 = QVBoxLayout(tag_box)
        current = tags if tags is not None else (local.hashtags if local else [])
        self.tag_picker = TagPicker(settings.tag_groups, {t: Qt.Checked for t in current})
        tl2.addWidget(self.tag_picker)
        lay.addWidget(tag_box)

        # Übrige vorhandene Tags (z. B. Kommentar, Komponist, Rating) zum Behalten anhaken
        self.extra_checks: dict[str, QCheckBox] = {}
        extra = [(k, label, v) for k, label, v in (local.raw_tags if local else [])
                 if not self._is_mapped(k)]
        if extra:
            title = ("Weitere vorhandene Tags – werden entfernt, außer du hakst sie an"
                     if settings.clean_tags else "Weitere vorhandene Tags – bleiben erhalten")
            box = QGroupBox(title)
            bl = QVBoxLayout(box)
            for k, label, v in extra:
                short = v if len(v) <= 70 else v[:68] + "…"
                cb = QCheckBox(f"{label}: {short}")
                cb.setToolTip(f"{k}\n{v}")
                cb.setChecked(k in (keep or set()) or not settings.clean_tags)
                cb.setEnabled(settings.clean_tags)
                self.extra_checks[k] = cb
                bl.addWidget(cb)
            lay.addWidget(box)
        lay.addStretch()

        self.missing = QLabel()
        self.missing.setWordWrap(True)
        outer.addWidget(self.missing)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)
        self._update_missing()
        self._fit_to_screen(content)

    def _fit_to_screen(self, content: QWidget) -> None:
        """Startgröße: so groß wie der Inhalt, höchstens 85 % des Bildschirms; kleiner ziehen geht immer."""
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        hint = content.sizeHint()
        w = min(max(hint.width() + 40, 700), int(screen.width() * 0.9))
        h = min(hint.height() + 110, int(screen.height() * 0.85))
        self.resize(w, h)
        self.setMinimumSize(420, 300)

    @staticmethod
    def _is_mapped(key: str) -> bool:
        from .scanner import ID3_FIELDS, VORBIS_FIELDS

        return key in ID3_FIELDS or key.split(":", 1)[0] in ID3_FIELDS or key.lower() in VORBIS_FIELDS

    def _key_values(self) -> tuple[str, str]:
        data = self.key.currentData()
        text = self.key.currentText().strip()
        if data and text.startswith(data):
            return data, CAMELOT_TO_KEY[data]
        code = text.upper().replace(" ", "")
        if code in CAMELOT_TO_KEY:
            return code, CAMELOT_TO_KEY[code]
        if text == (self.meta.key_camelot or self.meta.key_name):
            return self.meta.key_camelot, self.meta.key_name
        return "", text

    def result_meta(self) -> TrackMeta:
        camelot, key_name = self._key_values()
        split = lambda s: [p.strip() for p in s.split(",") if p.strip()]  # noqa: E731
        return replace(
            self.meta,
            artists=split(self.artists.text()),
            name=self.title.text().strip(),
            mix=self.mix.text().strip(),
            remixers=split(self.remixers.text()),
            album_artist=self.album_artist.text().strip(),
            release=self.release.text().strip(),
            track_number=self.track.value() or None,
            track_total=self.total.value() or None,
            disc_number=self.disc.value() or None,
            label=self.label.text().strip(),
            catalog_number=self.catno.text().strip(),
            genre=self.genre.text().strip(),
            sub_genre=self.sub_genre.text().strip(),
            release_date=self.date.text().strip(),
            isrc=self.isrc.text().strip(),
            bpm=self.bpm.value() or None,
            key_camelot=camelot,
            key_name=key_name,
            edited=True,
            enriched=True,
        )

    def result_tags(self) -> list[str]:
        return self.tag_picker.selected()

    def result_keep(self) -> set[str]:
        return {k for k, cb in self.extra_checks.items() if cb.isChecked()}

    def _update_missing(self, *_args) -> None:
        from .settings import missing_fields

        missing = missing_fields(self.result_meta(), self.settings)
        if missing:
            self.missing.setText('<span style="color:#cf222e">Fehlende Pflichtfelder: ' + ", ".join(missing) + "</span>")
        else:
            self.missing.setText('<span style="color:#1a7f37">Alle Pflichtfelder ausgefüllt.</span>')
