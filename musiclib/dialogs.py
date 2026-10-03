"""Dialoge der GUI: Einstellungen, Trefferauswahl und Metadaten-Editor."""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QTabWidget, QVBoxLayout, QWidget,
)

from .matcher import rank
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
        self.cover_check = QCheckBox("Cover einbetten")
        self.cover_check.setChecked(s.embed_cover)
        form.addRow("", self.cover_check)
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
        lay.addLayout(lf)
        lay.addStretch()
        return w

    def _sources_tab(self, s: AppSettings, user: str, password: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        bp = QGroupBox("Beatport (wird immer zuerst gefragt – ein sicherer Treffer hat Vorrang)")
        bf = QFormLayout(bp)
        self.bp_user = QLineEdit(user)
        self.bp_password = QLineEdit(password)
        self.bp_password.setEchoMode(QLineEdit.Password)
        self.bp_password.setPlaceholderText("wird nicht gespeichert")
        bf.addRow("Benutzername", self.bp_user)
        bf.addRow("Passwort", self.bp_password)
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
                      release_date="2018-07-13"),
            TrackMeta(id=2, name="Doppler", mix="", artists=["Charlotte de Witte"], release="Formula EP",
                      label="", genre="Techno (Peak Time / Driving)", bpm=135, key_camelot="6B",
                      release_date="2021-04-29"),
        ]
        fallback = self.label_fallback.text() if hasattr(self, "label_fallback") else ""
        lines = []
        for meta in examples:
            item = LibraryItem(LocalTrack(Path("x.mp3")), selected=meta)
            lines.append(str(target_path(item, Path("Bibliothek"), tpl, "camelot", fallback)))
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
            embed_cover=self.cover_check.isChecked(),
            required_fields=[k for k, cb in self.required_checks.items() if cb.isChecked()],
            label_fallback=self.label_fallback.text().strip(),
            use_discogs=self.use_discogs.isChecked(),
            discogs_token=self.discogs_token.text().strip(),
            use_bandcamp=self.use_bandcamp.isChecked(),
            match_threshold=self.match_threshold.value() / 100,
            auto_threshold=self.auto_threshold.value() / 100,
        )

    def beatport_credentials(self) -> tuple[str, str]:
        return self.bp_user.text().strip(), self.bp_password.text()


# ---------------------------------------------------------------------------- Treffer wählen
class CandidateDialog(QDialog):
    """Zeigt alle Treffer (alle Quellen) und erlaubt eine manuelle Suche."""

    def __init__(self, parent, item: LibraryItem, sources: Callable[[], list], match_threshold: float):
        super().__init__(parent)
        self.setWindowTitle("Treffer wählen")
        self.resize(980, 460)
        self.item = item
        self.sources = sources
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
        self.query = QLineEdit(" ".join(p for p in (loc.artist, loc.title, loc.mix) if p))
        self.source_combo = QComboBox()
        self.source_combo.addItem("Alle Quellen", "")
        for src in sources():
            self.source_combo.addItem(src.name, src.name)
        btn = QPushButton("Suchen")
        btn.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        row.addWidget(self.query, 1)
        row.addWidget(self.source_combo)
        row.addWidget(btn)
        lay.addLayout(row)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["Score", "Quelle", "Artist", "Titel", "Mix", "Label", "Genre", "Jahr", "BPM/Key"])
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
            vals = [f"{c.score:.0%}", t.source, t.artist, t.name, t.mix, t.label, t.genre, t.year,
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
class MetadataDialog(QDialog):
    """Erlaubt kleine Korrekturen an den Metadaten, bevor sie geschrieben werden."""

    def __init__(self, parent, meta: TrackMeta, settings: AppSettings):
        super().__init__(parent)
        self.setWindowTitle("Metadaten bearbeiten")
        self.resize(560, 0)
        self.meta = meta
        self.settings = settings
        form = QFormLayout(self)

        src = meta.source + (" (bearbeitet)" if meta.edited else "")
        src_label = QLabel(f'<a href="{meta.url}">{src}</a>' if meta.url else src)
        src_label.setOpenExternalLinks(True)
        form.addRow("Quelle", src_label)

        def line(value: str, placeholder: str = "") -> QLineEdit:
            e = QLineEdit(value)
            e.setPlaceholderText(placeholder)
            e.textChanged.connect(self._update_missing)
            return e

        self.artists = line(", ".join(meta.artists), "mehrere mit Komma trennen")
        self.title = line(meta.name)
        self.mix = line(meta.mix, "z. B. Original Mix, Extended Mix")
        self.remixers = line(", ".join(meta.remixers))
        self.release = line(meta.release)
        self.label = line(meta.label, f"leer = „{settings.label_fallback}“" if settings.label_fallback else "")
        self.catno = line(meta.catalog_number)
        self.genre = line(meta.genre)
        self.sub_genre = line(meta.sub_genre)
        self.date = line(meta.release_date, "JJJJ-MM-TT oder JJJJ")
        self.isrc = line(meta.isrc)
        self.bpm = QSpinBox()
        self.bpm.setRange(0, 300)
        self.bpm.setSpecialValueText("–")
        self.bpm.setValue(int(meta.bpm or 0))
        self.bpm.valueChanged.connect(self._update_missing)
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

        for label, w in (("Artist(s)", self.artists), ("Titel", self.title), ("Mix", self.mix),
                         ("Remixer", self.remixers), ("Release / Album", self.release), ("Label", self.label),
                         ("Katalognummer", self.catno), ("Genre", self.genre), ("Sub-Genre", self.sub_genre),
                         ("Release-Datum", self.date), ("BPM", self.bpm), ("Key", self.key), ("ISRC", self.isrc)):
            form.addRow(label, w)

        self.missing = QLabel()
        self.missing.setWordWrap(True)
        form.addRow(self.missing)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self._update_missing()

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
            release=self.release.text().strip(),
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
        )

    def _update_missing(self, *_args) -> None:
        from .settings import missing_fields

        missing = missing_fields(self.result_meta(), self.settings)
        if missing:
            self.missing.setText('<span style="color:#cf222e">Fehlende Pflichtfelder: ' + ", ".join(missing) + "</span>")
        else:
            self.missing.setText('<span style="color:#1a7f37">Alle Pflichtfelder ausgefüllt.</span>')


def meta_from_local(local: LocalTrack) -> TrackMeta:
    """Startpunkt für manuelle Erfassung, wenn keine Quelle etwas gefunden hat."""
    return TrackMeta(id=str(local.path), name=local.title, mix=local.mix,
                     artists=[local.artist] if local.artist else [], release=local.album,
                     isrc=local.isrc, source="Manuell")
