"""Grafische Oberfläche (PySide6) für den MusicLibOrganizer."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, Qt, QThread, QTranslator, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView,
    QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .backup import backup_dir
from . import credentials
from . import rekordbox_db as rbdb
from .journal import Journal
from .bandcamp import BandcampClient
from .converter import find_ffmpeg
from .manual import as_unofficial
from .soundcloud import SoundCloudClient
from .beatport import BeatportClient
from .dialogs import CandidateDialog, MetadataDialog, SettingsDialog, TagsDialog, meta_from_local
from .discogs import DiscogsClient
from .matcher import enrich, match_item
from .urlimport import assign_release, load_url, looks_like_url
from .models import LibraryItem, MatchStatus
from .organizer import assign_targets, validate_template
from .pipeline import ApplyOptions, apply_item, make_cover_loader
from .releases import CONFLICT, harmonize
from .release_dialog import ReleaseDialog
from .release_edit import apply_release_edit
from .scanner import scan
from .settings import AppSettings, effective_meta, effective_tags, missing_fields
from .tagger import TagOptions

STATUS_COLORS = {
    MatchStatus.MATCHED: QColor(46, 160, 67, 70),
    MatchStatus.MANUAL: QColor(46, 160, 67, 110),
    MatchStatus.UNCERTAIN: QColor(219, 171, 9, 80),
    MatchStatus.NOT_FOUND: QColor(207, 34, 46, 60),
    MatchStatus.ERROR: QColor(207, 34, 46, 110),
    MatchStatus.DONE: QColor(9, 105, 218, 70),
}
MISSING_COLOR = QColor(219, 171, 9, 80)

COLUMNS = ["", "Status", "Quelle", "Datei", "Format", "Lokal erkannt", "Treffer", "Score", "Album-Artist", "Nr.",
           "Genre", "Label", "Jahr", "BPM", "Key", "Tags", "Cover", "Fehlt", "Ziel"]
(COL_CHECK, COL_STATUS, COL_SOURCE, COL_FILE, COL_FMT, COL_LOCAL, COL_MATCH, COL_SCORE, COL_ALBUMARTIST, COL_TRACK,
 COL_GENRE, COL_LABEL, COL_YEAR, COL_BPM, COL_KEY, COL_TAGS, COL_COVER, COL_MISSING, COL_TARGET) = range(len(COLUMNS))

FILTERS = {
    "Alle": lambda w, i: True,
    "Offen (nicht erledigt)": lambda w, i: i.status != MatchStatus.DONE,
    "Bereit zur Übernahme": lambda w, i: w.is_auto_ready(i),
    "Unsicher": lambda w, i: i.status == MatchStatus.UNCERTAIN,
    "Nicht gefunden / Fehler": lambda w, i: i.status in (MatchStatus.NOT_FOUND, MatchStatus.ERROR),
    "Unvollständig": lambda w, i: i.status != MatchStatus.DONE and bool(w.missing(i)),
    "Erledigt": lambda w, i: i.status == MatchStatus.DONE,
}
CONFIRMED = (MatchStatus.MATCHED, MatchStatus.MANUAL)


class Worker(QThread):
    """Führt eine Funktion im Hintergrund aus; die Funktion bekommt den Worker für Signale."""

    progress = Signal(int, int, str)
    item_done = Signal(int)
    log = Signal(str)
    failed = Signal(str)

    def __init__(self, fn: Callable[["Worker"], None]):
        super().__init__()
        self.fn = fn
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    @property
    def cancelled(self) -> bool:
        return self._cancel

    def run(self) -> None:
        try:
            self.fn(self)
        except Exception as e:
            self.failed.emit(f"{e}\n{traceback.format_exc()}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"MusicLibOrganizer {__version__}")
        self.resize(1500, 880)
        self.qsettings = QSettings("MusicLibOrganizer", "MusicLibOrganizer")
        self.settings = AppSettings.from_json(self.qsettings.value("settings", ""))
        self.items: list[LibraryItem] = []
        self.worker: Worker | None = None
        self._beatport: BeatportClient | None = None
        self._sources_cache: list | None = None
        self._username, self._password, self._cred_source = credentials.initial_credentials(
            self.qsettings.value("beatport_user", ""))
        self._updating_table = False

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- Ordner + Einstellungen
        top = QGridLayout()
        self.src_edit = QLineEdit(self.qsettings.value("source", ""))
        self.dst_edit = QLineEdit(self.qsettings.value("target", ""))
        self.dst_edit.editingFinished.connect(self.refresh_targets)
        for row, (label, edit) in enumerate((("Quelle", self.src_edit), ("Ziel-Bibliothek", self.dst_edit))):
            top.addWidget(QLabel(label), row, 0)
            top.addWidget(edit, row, 1)
            b = QPushButton("…")
            b.setFixedWidth(32)
            b.clicked.connect(lambda _=False, e=edit: self.pick_dir(e))
            top.addWidget(b, row, 2)
        self.settings_btn = QPushButton("⚙  Einstellungen")
        self.settings_btn.clicked.connect(self.open_settings)
        top.addWidget(self.settings_btn, 0, 3)
        self.login_label = QLabel("Beatport: nicht angemeldet")
        top.addWidget(self.login_label, 1, 3)
        self.rekordbox_btn = QPushButton("🎧  Rekordbox-Umzug")
        self.rekordbox_btn.setToolTip("Status anzeigen, Rekordbox auf die neue Library umstellen, Sicherung zurückspielen")
        top.addWidget(self.rekordbox_btn, 0, 4)
        top.setColumnStretch(1, 1)
        root.addLayout(top)

        # --- Aktionen
        actions = QHBoxLayout()
        self.scan_btn = QPushButton("1. Scannen")
        self.match_btn = QPushButton("2. Abgleichen")
        self.auto_btn = QPushButton("✔ 100%-Treffer übernehmen")
        self.auto_btn.setToolTip("Verarbeitet alle Tracks mit 100%-Treffer (Schwelle in den Einstellungen) "
                                 "und alle manuell bestätigten Tracks – jeweils nur, wenn alle Pflichtfelder gefüllt sind.")
        self.apply_btn = QPushButton("Markierte ausführen")
        self.cancel_btn = QPushButton("Abbrechen")
        self.scan_btn.clicked.connect(self.start_scan)
        self.match_btn.clicked.connect(self.start_match)
        self.auto_btn.clicked.connect(self.apply_auto)
        self.apply_btn.clicked.connect(self.apply_checked)
        self.cancel_btn.clicked.connect(self.cancel)
        for b in (self.scan_btn, self.match_btn, self.auto_btn, self.apply_btn, self.cancel_btn):
            b.setMinimumHeight(32)
            actions.addWidget(b)
        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m")
        actions.addWidget(self.progress, 1)
        root.addLayout(actions)

        # --- Filter + Zusammenfassung
        frow = QHBoxLayout()
        frow.addWidget(QLabel("Anzeigen:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(list(FILTERS))
        self.filter_combo.currentIndexChanged.connect(self.apply_filter)
        frow.addWidget(self.filter_combo)
        for text, tip, fn in (
                ("☑ Alle markieren", "Alle angezeigten Tracks markieren (Strg/⌘+Umschalt+A)", self.check_all),
                ("☐ Keine markieren", "Markierung bei allen angezeigten Tracks entfernen (Strg/⌘+Umschalt+D)", self.check_none),
                ("⇄ Umkehren", "Markierung bei allen angezeigten Tracks umkehren", self.check_invert)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            frow.addWidget(b)
        self.summary = QLabel("")
        frow.addWidget(self.summary, 1)
        hint = QLabel("Doppelklick: Treffer wählen oder URL einfügen · Rechtsklick: weitere Aktionen")
        hint.setStyleSheet("color: gray")
        frow.addWidget(hint)
        root.addLayout(frow)

        # --- Tabelle + Log
        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        for col, w in ((COL_CHECK, 28), (COL_STATUS, 95), (COL_SOURCE, 75), (COL_FILE, 200), (COL_FMT, 75),
                       (COL_LOCAL, 220), (COL_MATCH, 280), (COL_SCORE, 50), (COL_ALBUMARTIST, 120), (COL_TRACK, 45),
                       (COL_GENRE, 110), (COL_LABEL, 120),
                       (COL_YEAR, 45), (COL_BPM, 40), (COL_KEY, 45), (COL_TAGS, 140), (COL_COVER, 60), (COL_MISSING, 90)):
            self.table.setColumnWidth(col, w)
        self.table.cellDoubleClicked.connect(lambda row, _c: self.choose_match(row))
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.table.itemSelectionChanged.connect(self.update_buttons)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        split.addWidget(self.table)
        split.addWidget(self.log_view)
        split.setSizes([680, 140])
        root.addWidget(split, 1)

        # --- Menüs
        m = self.menuBar().addMenu("Datei")
        a = QAction("Einstellungen…", self)
        a.setShortcut(QKeySequence.Preferences)
        a.triggered.connect(self.open_settings)
        m.addAction(a)
        a = QAction("Library prüfen…", self)
        a.triggered.connect(self.check_library)
        m.addAction(a)
        a = QAction("Schreibweisen vereinheitlichen…", self)
        a.triggered.connect(self.unify_spellings)
        m.addAction(a)
        a = QAction("Beenden", self)
        a.setShortcut(QKeySequence.Quit)
        a.triggered.connect(self.close)
        m.addAction(a)

        m = self.menuBar().addMenu("Rekordbox")
        for text, fn in (("Umzugs-Status anzeigen…", self.rekordbox_status),
                         ("Rekordbox auf neue Library umstellen…", self.rekordbox_switch),
                         ("Library-Ordner umbenennen…", self.rename_library),
                         ("Letzte Sicherung zurückspielen…", self.rekordbox_restore)):
            a = QAction(text, self)
            a.triggered.connect(fn)
            m.addAction(a)
        # Dasselbe Menü auch als Button im Fenster (auf dem Mac steht die Menüleiste oben am Bildschirm)
        self.rekordbox_btn.setMenu(m)

        m = self.menuBar().addMenu("Auswahl")
        for text, fn, key in (("Alle angezeigten markieren", self.check_all, "Ctrl+Shift+A"),
                              ("Keine markieren", self.check_none, "Ctrl+Shift+D"),
                              ("Markierung umkehren", self.check_invert, None),
                              ("Nur Bereite markieren", lambda: self.set_enabled(self.is_auto_ready), None),
                              ("Alle unsicheren Treffer bestätigen", self.confirm_all_uncertain, None),
                              ("EPs/Alben auf ein Release angleichen", lambda: self.harmonize_releases(), None)):
            a = QAction(text, self)
            a.triggered.connect(fn)
            if key:
                a.setShortcut(QKeySequence(key))  # Ctrl = ⌘ auf dem Mac
            m.addAction(a)

        if self._username and self._password:
            self.login_label.setText(f"Beatport: Zugangsdaten aus {self._cred_source} ({self._username})")
        elif not self._username:
            self.login_label.setText("Beatport: Zugangsdaten unter ⚙ Einstellungen → Quellen eintragen")
        where = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        self.append_log(f"MusicLibOrganizer {__version__} – gestartet aus {where}")
        if find_ffmpeg() is None:
            self.append_log("⚠ ffmpeg wurde nicht gefunden – FLAC/WAV können nicht konvertiert werden. "
                            "Installation: brew install ffmpeg")
        self.update_buttons()

    # ------------------------------------------------------------ Hilfen
    def pick_dir(self, edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Ordner wählen", edit.text() or str(Path.home()))
        if d:
            edit.setText(d)
            self.refresh_targets()

    def append_log(self, msg: str) -> None:
        self.log_view.appendPlainText(msg)

    def missing(self, item: LibraryItem) -> list[str]:
        return missing_fields(item.selected, self.settings)

    def is_auto_ready(self, item: LibraryItem) -> bool:
        """Kann ohne Rückfrage übernommen werden: 100%-Treffer oder manuell bestätigt, alles vollständig."""
        if item.status == MatchStatus.MANUAL:
            sure = True
        elif item.status == MatchStatus.MATCHED:
            sure = round(item.score, 2) >= self.settings.auto_threshold
        else:
            sure = False
        return sure and item.selected is not None and not self.missing(item)

    def sources(self) -> list:
        """Aktive Quellen in fester Reihenfolge: Beatport zuerst, dann Discogs, dann Bandcamp."""
        if self._sources_cache is None:
            out = []
            if self._username and self._password:
                if self._beatport is None:
                    self._beatport = BeatportClient(self._username, self._password)
                out.append(self._beatport)
            if self.settings.use_discogs and (self.settings.discogs_token or os.environ.get("DISCOGS_TOKEN")):
                out.append(DiscogsClient(token=self.settings.discogs_token or None))
            if self.settings.use_bandcamp:
                out.append(BandcampClient())
            self._sources_cache = out
        return self._sources_cache

    def url_clients(self) -> dict:
        """Clients zum Laden per URL – auch für Quellen, die bei der Suche abgeschaltet sind."""
        clients = {s.name: s for s in self.sources()}
        if "Beatport" not in clients and self._username and self._password:
            if self._beatport is None:
                self._beatport = BeatportClient(self._username, self._password)
            clients["Beatport"] = self._beatport
        token = self.settings.discogs_token or os.environ.get("DISCOGS_TOKEN")
        if "Discogs" not in clients and token:
            clients["Discogs"] = DiscogsClient(token=token)
        clients.setdefault("Bandcamp", BandcampClient())
        clients["SoundCloud"] = SoundCloudClient(default_label=self.settings.unofficial_label)
        return clients

    def save_settings(self) -> None:
        self.qsettings.setValue("source", self.src_edit.text())
        self.qsettings.setValue("target", self.dst_edit.text())
        self.qsettings.setValue("settings", self.settings.to_json())

    def closeEvent(self, event) -> None:
        self.save_settings()
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(event)

    def busy(self) -> bool:
        return bool(self.worker and self.worker.isRunning())

    def update_buttons(self) -> None:
        busy = self.busy()
        has_items = bool(self.items)
        n_ready = sum(self.is_auto_ready(i) for i in self.items)
        n_checked = sum(i.enabled and i.status != MatchStatus.DONE for i in self.items)
        self.scan_btn.setEnabled(not busy)
        self.match_btn.setEnabled(not busy and has_items)
        self.auto_btn.setEnabled(not busy and n_ready > 0)
        self.auto_btn.setText(f"✔ 100%-Treffer übernehmen ({n_ready})")
        self.apply_btn.setEnabled(not busy and n_checked > 0)
        self.apply_btn.setText(f"Markierte ausführen ({n_checked})")
        self.cancel_btn.setEnabled(busy)
        self.settings_btn.setEnabled(not busy)
        c = {s: 0 for s in MatchStatus}
        for i in self.items:
            c[i.status] += 1
        incomplete = sum(1 for i in self.items if i.status != MatchStatus.DONE and i.selected and self.missing(i))
        if has_items:
            self.summary.setText(
                f"{len(self.items)} Dateien · {c[MatchStatus.MATCHED] + c[MatchStatus.MANUAL]} gefunden · "
                f"{c[MatchStatus.UNCERTAIN]} unsicher · {c[MatchStatus.NOT_FOUND] + c[MatchStatus.ERROR]} nicht gefunden · "
                f"{incomplete} unvollständig · {c[MatchStatus.DONE]} erledigt")
        else:
            self.summary.setText("")

    def run_worker(self, fn: Callable[[Worker], None], on_done: Callable[[], None] | None = None) -> None:
        self.worker = Worker(fn)
        self.worker.progress.connect(self.on_progress)
        self.worker.item_done.connect(self.update_row)
        self.worker.log.connect(self.append_log)
        self.worker.failed.connect(lambda msg: (self.append_log("FEHLER: " + msg),
                                                QMessageBox.critical(self, "Fehler", msg.splitlines()[0])))

        def finished():
            self.update_buttons()
            if on_done:
                on_done()

        self.worker.finished.connect(finished)
        self.worker.start()
        self.update_buttons()

    def on_progress(self, i: int, n: int, text: str) -> None:
        self.progress.setMaximum(max(n, 1))
        self.progress.setValue(i)
        self.statusBar().showMessage(text)

    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.append_log("Abbruch angefordert …")

    # ------------------------------------------------------------ Tabelle
    def fill_table(self) -> None:
        self._updating_table = True
        self.table.setRowCount(len(self.items))
        for row in range(len(self.items)):
            for col in range(len(COLUMNS)):
                if self.table.item(row, col) is None:
                    self.table.setItem(row, col, QTableWidgetItem())
        self._updating_table = False
        for row in range(len(self.items)):
            self.update_row(row)

    @staticmethod
    def cover_state(it: LibraryItem) -> str:
        if it.status == MatchStatus.DONE:
            return ""
        if it.cover:
            return "eigenes"
        if it.selected and it.selected.image_url and it.selected.source != "Manuell":
            return "Quelle"
        return "Datei" if it.local.has_cover else "–"

    def update_row(self, row: int) -> None:
        if row >= self.table.rowCount():
            return
        it = self.items[row]
        loc = it.local
        meta = effective_meta(it.selected, self.settings) if it.selected else None
        missing = [] if it.status == MatchStatus.DONE else self.missing(it)
        target = ""
        if it.target:
            try:
                target = str(it.target.relative_to(Path(self.dst_edit.text())))
            except ValueError:
                target = str(it.target)
        key = ""
        if meta:
            key = meta.key_camelot if self.settings.key_format == "camelot" and meta.key_camelot else meta.key_name
        values = {
            COL_STATUS: it.status.value,
            COL_SOURCE: (meta.source + (" ✎" if meta.edited else "")) if meta else "",
            COL_FILE: loc.path.name,
            COL_FMT: loc.format + (" → mp3" if loc.needs_conversion else ""),
            COL_LOCAL: f"{loc.artist} – {loc.title}" + (f" ({loc.mix})" if loc.mix else ""),
            COL_MATCH: meta.display if meta else "",
            COL_SCORE: f"{it.score:.0%}" if it.candidates else "",
            COL_ALBUMARTIST: meta.effective_album_artist if meta else "",
            COL_TRACK: (f"{meta.track_number}/{meta.track_total}" if meta.track_total else str(meta.track_number))
            if meta and meta.track_number else "",
            COL_GENRE: meta.genre if meta else "",
            COL_LABEL: meta.label if meta else "",
            COL_YEAR: meta.year if meta else "",
            COL_BPM: str(meta.bpm or "") if meta else "",
            COL_KEY: key,
            COL_TAGS: " ".join(f"#{t}" for t in effective_tags(it, self.settings)),
            COL_COVER: self.cover_state(it),
            COL_MISSING: ", ".join(missing),
            COL_TARGET: target,
        }
        self._updating_table = True
        check = self.table.item(row, COL_CHECK)
        check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        check.setCheckState(Qt.Checked if it.enabled else Qt.Unchecked)
        color = STATUS_COLORS.get(it.status)
        for col, val in values.items():
            cell = self.table.item(row, col)
            cell.setText(val)
            if col == COL_STATUS:
                cell.setToolTip(it.message or val)
                cell.setBackground(color if color is not None else QColor(0, 0, 0, 0))
            elif col == COL_COVER:
                cell.setToolTip("Eigenes Cover: Rechtsklick → Release / Cover bearbeiten")
                cell.setBackground(MISSING_COLOR if val == "–" and it.status != MatchStatus.DONE else QColor(0, 0, 0, 0))
            elif col == COL_MISSING:
                cell.setToolTip("Fehlende Pflichtfelder – Rechtsklick → Metadaten bearbeiten")
                cell.setBackground(MISSING_COLOR if missing else QColor(0, 0, 0, 0))
            else:
                cell.setToolTip(str(loc.path) if col == COL_FILE else (meta.url if col == COL_SOURCE and meta else val))
        self._updating_table = False
        self.table.setRowHidden(row, not FILTERS[self.filter_combo.currentText()](self, it))

    def apply_filter(self) -> None:
        pred = FILTERS[self.filter_combo.currentText()]
        for row, it in enumerate(self.items):
            self.table.setRowHidden(row, not pred(self, it))

    def on_item_changed(self, cell: QTableWidgetItem) -> None:
        if self._updating_table or cell.column() != COL_CHECK:
            return
        self.items[cell.row()].enabled = cell.checkState() == Qt.Checked
        self.refresh_targets()

    def set_enabled(self, pred: Callable[[LibraryItem], bool], visible_only: bool = True) -> None:
        """Setzt die Markierung; standardmäßig nur für die gerade angezeigten (gefilterten) Zeilen."""
        for row, i in enumerate(self.items):
            if visible_only and self.table.isRowHidden(row):
                continue
            i.enabled = i.status != MatchStatus.DONE and pred(i)
        self.refresh_targets()

    def check_all(self) -> None:
        self.set_enabled(lambda i: True)

    def check_none(self) -> None:
        self.set_enabled(lambda i: False)

    def check_invert(self) -> None:
        self.set_enabled(lambda i: not i.enabled)

    def confirm_all_uncertain(self) -> None:
        for i in self.items:
            if i.status == MatchStatus.UNCERTAIN and i.selected and not i.message.startswith(CONFLICT):
                i.status = MatchStatus.MANUAL
                i.message = "unsicheren Treffer bestätigt"
        self.refresh_targets()

    def refresh_targets(self) -> None:
        if self.busy():
            return
        err = validate_template(self.settings.template)
        if err:
            self.statusBar().showMessage(err)
            return
        if self.items and self.dst_edit.text():
            pending = [i for i in self.items if i.status != MatchStatus.DONE]
            assign_targets(pending, Path(self.dst_edit.text()), self.settings.template,
                           self.settings.key_format, self.settings.label_fallback, self.settings.hide_original_mix)
        for row in range(len(self.items)):
            self.update_row(row)
        self.update_buttons()

    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def context_menu(self, pos) -> None:
        rows = self.selected_rows()
        if not rows or self.busy():
            return
        menu = QMenu(self)
        if len(rows) == 1:
            row = rows[0]
            it = self.items[row]
            menu.addAction("Treffer wählen / suchen…", lambda: self.choose_match(row))
            menu.addAction("Von URL übernehmen…", lambda: self.from_url(rows))
            menu.addAction("Metadaten bearbeiten…" if it.selected else "Metadaten manuell erfassen…",
                           lambda: self.edit_metadata(row))
            if it.selected and it.selected.url:
                menu.addAction(f"Auf {it.selected.source} öffnen",
                               lambda: QDesktopServices.openUrl(QUrl(it.selected.url)))
            menu.addSeparator()
        if len(rows) > 1:
            menu.addAction(f"Release-URL für {len(rows)} Tracks übernehmen…", lambda: self.from_url(rows))
            menu.addSeparator()
        menu.addAction("Release / Cover bearbeiten…" + (f" – {len(rows)} Tracks gemeinsam" if len(rows) > 1 else ""),
                       lambda: self.edit_release(rows))
        menu.addAction("Tags setzen…" + (f" – {len(rows)} Tracks" if len(rows) > 1 else ""), lambda: self.set_tags(rows))
        menu.addAction("Als inoffiziell erfassen (Bootleg/Edit/SoundCloud)" + (f" – {len(rows)} Tracks" if len(rows) > 1 else ""),
                       lambda: self.mark_unofficial(rows))
        menu.addSeparator()
        if any(self.items[r].status == MatchStatus.UNCERTAIN for r in rows):
            menu.addAction("Treffer bestätigen", lambda: self._confirm_rows(rows))
        menu.addAction("Markieren", lambda: self._set_rows(rows, True))
        menu.addAction("Nicht markieren", lambda: self._set_rows(rows, False))
        menu.addSeparator()
        menu.addAction("Nur diese ausführen", lambda: self.start_apply(rows))
        if any(self.items[r].status == MatchStatus.DONE for r in rows):
            menu.addAction("Erneut bearbeiten", lambda: self.reprocess(rows))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _confirm_rows(self, rows: list[int]) -> None:
        for r in rows:
            if self.items[r].status == MatchStatus.UNCERTAIN and self.items[r].selected:
                self.items[r].status = MatchStatus.MANUAL
        self.refresh_targets()

    def _set_rows(self, rows: list[int], enabled: bool) -> None:
        for r in rows:
            if self.items[r].status != MatchStatus.DONE:
                self.items[r].enabled = enabled
        self.refresh_targets()

    def from_url(self, rows: list[int]) -> None:
        """Metadaten von einer Track-/Release-URL laden und den markierten Dateien zuordnen."""
        clip = QApplication.clipboard().text().strip()
        url, ok = QInputDialog.getText(
            self, "Von URL übernehmen",
            "URL eines Tracks oder Releases (Beatport, Discogs, Bandcamp, SoundCloud):"
            + ("\nBei mehreren Dateien wird jede dem passenden Track des Releases zugeordnet." if len(rows) > 1 else ""),
            text=clip if looks_like_url(clip) else "")
        url = url.strip()
        if not ok or not url:
            return
        if len(rows) == 1:
            self.choose_match(rows[0], url=url)
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            tracks = load_url(url, self.url_clients())
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "URL laden", str(e))
            return
        QApplication.restoreOverrideCursor()
        items = [self.items[r] for r in rows]
        pairs = assign_release(items, tracks)
        for it, meta, s in pairs:
            it.selected, it.score, it.status = meta, s, MatchStatus.MANUAL
            it.message = f"von URL zugeordnet ({meta.source})"
            it.enabled = True
        self.refresh_targets()
        assigned = {id(p[0]) for p in pairs}
        missing = [it.local.path.name for it in items if id(it) not in assigned]
        text = f"{len(pairs)} von {len(items)} Dateien wurden einem Track aus „{tracks[0].release if tracks else url}“ zugeordnet."
        if missing:
            text += "\n\nNicht zugeordnet (bitte einzeln per Doppelklick wählen):\n• " + "\n• ".join(missing)
        QMessageBox.information(self, "Von URL übernehmen", text)

    def set_tags(self, rows: list[int]) -> None:
        items = [self.items[r] for r in rows if self.items[r].status != MatchStatus.DONE]
        if not items:
            return
        current = [list(it.tags if it.tags is not None else it.local.hashtags) for it in items]
        dlg = TagsDialog(self, self.settings.tag_groups, current)
        if dlg.exec() != QDialog.Accepted:
            return
        add, remove = dlg.picker.changes()
        for it, tags in zip(items, current):
            it.tags = [t for t in tags if t not in remove] + [t for t in add if t not in tags]
        self.refresh_targets()

    def mark_unofficial(self, rows: list[int]) -> None:
        """Füllt Album, Tracknummer, Label und Jahr für Tracks ohne offizielles Release vor."""
        for r in rows:
            it = self.items[r]
            if it.status == MatchStatus.DONE:
                continue
            # Ein sicherer oder bestätigter Treffer (z. B. das Original bei Beatport) liefert Artist, Titel und Genre
            base = it.selected if it.status in (MatchStatus.MANUAL, MatchStatus.MATCHED) else None
            it.selected = as_unofficial(it.local, base, self.settings.unofficial_label)
            it.status, it.enabled = MatchStatus.MANUAL, True
            it.message = "als inoffiziell erfasst"
        self.refresh_targets()
        if len(rows) == 1:
            self.edit_metadata(rows[0])  # direkt prüfen/ergänzen, z. B. Genre

    def choose_match(self, row: int, url: str = "") -> None:
        if self.busy():
            return
        item = self.items[row]
        try:
            sources = self.sources()
        except Exception as e:
            QMessageBox.warning(self, "Quellen", str(e))
            return
        dlg = CandidateDialog(self, item, lambda: sources, self.settings.match_threshold,
                              url_clients=self.url_clients, initial_query=url)
        if url:
            dlg.load_url(url)
        if dlg.exec() != QDialog.Accepted:
            return
        if dlg.result_action == "none":
            item.selected, item.status, item.score = None, MatchStatus.NOT_FOUND, 0.0
            item.message = "manuell: kein Treffer"
        else:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                item.selected = enrich(dlg.choice.track, sources)  # Tracknummer/Album-Artist nachladen
            finally:
                QApplication.restoreOverrideCursor()
            item.score = dlg.choice.score
            item.status = MatchStatus.MANUAL
            item.message = f"manuell gewählt ({dlg.choice.track.source})"
            if dlg.choice not in item.candidates:
                item.candidates = dlg.candidates
            if dlg.result_action == "edit":
                self.refresh_targets()
                self.edit_metadata(row)
                return
            self.harmonize_releases(sources, only=item)
            return
        self.refresh_targets()

    def harmonize_releases(self, sources: list | None = None, only: LibraryItem | None = None) -> None:
        """Tracks einer EP/eines Albums auf dasselbe Release (dieselbe Quelle) bringen."""
        if self.busy():
            return
        try:
            sources = sources if sources is not None else self.sources()
        except Exception as e:
            QMessageBox.warning(self, "Quellen", str(e))
            return
        thr = self.settings.match_threshold

        def job(w: Worker):
            lines = harmonize(self.items, sources, thr, only=only, cancelled=lambda: w.cancelled)
            for line in lines:
                w.log.emit(line)
            if only is None and not lines:
                w.log.emit("Alle EPs/Alben kommen jeweils aus einem Release ✔")

        self.run_worker(job, self.refresh_targets)

    def edit_metadata(self, row: int) -> None:
        if self.busy():
            return
        item = self.items[row]
        meta = item.selected or meta_from_local(item.local)
        current = item.tags if item.tags is not None else item.local.hashtags
        dlg = MetadataDialog(self, meta, self.settings, item.local, item.keep_tags, current)
        if dlg.exec() != QDialog.Accepted:
            return
        item.selected = dlg.result_meta()
        item.keep_tags = dlg.result_keep()
        item.tags = dlg.result_tags()
        item.status = MatchStatus.MANUAL
        item.message = "Metadaten bearbeitet"
        self.refresh_targets()

    def edit_release(self, rows: list[int]) -> None:
        """Gemeinsame Release-Felder und Cover für mehrere Tracks auf einmal."""
        if self.busy():
            return
        items = [self.items[r] for r in rows if self.items[r].status != MatchStatus.DONE]
        if not items:
            QMessageBox.information(self, "Release bearbeiten", "Die gewählten Tracks sind schon übernommen. "
                                    "Rechtsklick → „Erneut bearbeiten“, um sie noch einmal zu ändern.")
            return
        dlg = ReleaseDialog(self, items)
        if dlg.exec() != QDialog.Accepted:
            return
        n = apply_release_edit(items, dlg.changes(), dlg.renumber.isChecked())
        if dlg.cover_changed:
            for it in items:
                it.cover = dlg.cover
        skipped = len(rows) - len(items)
        self.append_log(f"Release bearbeitet: {n or len(items)} Tracks"
                        + (" (Cover gesetzt)" if dlg.cover_changed and dlg.cover else "")
                        + (f", {skipped} bereits übernommene übersprungen" if skipped else ""))
        self.refresh_targets()

    def check_library(self) -> None:
        """Bericht über die Ziel-Library (und Rekordbox) – ändert nichts."""
        if self.busy():
            return
        root = Path(self.dst_edit.text())
        if not root.is_dir():
            QMessageBox.warning(self, "Library prüfen", "Bitte oben die Ziel-Bibliothek wählen.")
            return
        old = Path(self.src_edit.text()) if self.src_edit.text() else None
        result: list[str] = []

        def job(w: Worker):
            from datetime import datetime

            from . import audit
            from .backup import data_dir

            w.log.emit(f"Prüfe {root} …")
            files = audit.collect(root, lambda i, n, p: w.progress.emit(i, n, p.name))
            try:
                rb = audit.rekordbox_paths()
            except Exception as e:
                rb = None
                w.log.emit(f"Rekordbox nicht geprüft: {e}")
            j = Journal()
            migrated = {m.src for m in j.all()}
            j.close()
            text = audit.render(audit.build_report(root, files, rb, old if old and old != root else None, migrated))
            out = data_dir() / "berichte" / f"library-{datetime.now():%Y-%m-%d_%H-%M}.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            w.log.emit(f"Bericht gespeichert: {out}")
            result.append(text)

        self.run_worker(job, lambda: result and self._show_text("Library-Prüfung", result[0]))

    def unify_spellings(self) -> None:
        """Namen wie „Omar-S“/„Omar S“ oder „Not On Label“ in der Ziel-Library vereinheitlichen."""
        if self.busy():
            return
        root = Path(self.dst_edit.text())
        if not root.is_dir():
            QMessageBox.warning(self, "Schreibweisen", "Bitte oben die Ziel-Bibliothek wählen.")
            return
        found: list = []

        def scan_job(w: Worker):
            from . import audit, unify

            w.log.emit(f"Suche Schreibvarianten in {root} …")
            files = audit.collect(root, lambda i, n, p: w.progress.emit(i, n, p.name))
            found.append((files, unify.find_rules(files, self.settings.label_fallback)))

        self.run_worker(scan_job, lambda: found and self._unify_choose(root, *found[0]))

    def _unify_choose(self, root: Path, files: list, rules: list) -> None:
        from . import unify
        from .unify_dialog import UnifyDialog

        if not rules:
            QMessageBox.information(self, "Schreibweisen", "Keine unterschiedlichen Schreibweisen gefunden ✔")
            return
        dlg = UnifyDialog(self, rules)
        if dlg.exec() != QDialog.Accepted:
            return
        changes = unify.plan(root, files, dlg.result_rules())
        if not changes:
            QMessageBox.information(self, "Schreibweisen", "Nichts zu ändern.")
            return
        text = unify.summary(changes)
        if QMessageBox.question(self, "Schreibweisen vereinheitlichen", text + "\n\nJetzt ausführen?") != QMessageBox.Yes:
            return
        result: list = []

        def job(w: Worker):
            journal = Journal()
            try:
                result.append(unify.apply(root, changes, journal, lambda i, n, name: w.progress.emit(i, n, name)))
            finally:
                journal.close()
            ok, problems, log = result[0]
            w.log.emit(f"Schreibweisen: {ok} Dateien geändert, Protokoll mit allen alten Werten: {log}")
            for p in problems:
                w.log.emit("  ✘ " + p)

        self.run_worker(job, lambda: result and self._unify_done(changes, *result[0]))

    def _unify_done(self, changes: list, ok: int, problems: list[str], log: Path) -> None:
        moved = sum(c.moves for c in changes)
        msg = (f"{ok} Dateien geändert, {moved} davon umbenannt/verschoben."
               + (f"\n⚠ {len(problems)} Probleme – siehe Log unten." if problems else ""))
        if moved:
            msg += ("\n\nDamit Rekordbox die umbenannten Dateien findet, jetzt Rekordbox umstellen? "
                    "(Rekordbox muss dafür beendet sein.)")
            if QMessageBox.question(self, "Schreibweisen", msg) == QMessageBox.Yes:
                self.rekordbox_switch()
        else:
            QMessageBox.information(self, "Schreibweisen", msg)
        self.append_log("Tipp: In Rekordbox die geänderten Tracks markieren → Rechtsklick → "
                        "„Tag-Informationen neu laden“, damit die neuen Namen auch dort erscheinen.")
        if self.items:
            self.append_log("Hinweis: Die Liste oben zeigt noch den alten Stand – bei Bedarf neu scannen.")

    # ------------------------------------------------------------ Einstellungen
    def open_settings(self) -> None:
        dlg = SettingsDialog(self, self.settings, self._username, self._password)
        if dlg.exec() != QDialog.Accepted:
            return
        self.settings = dlg.result_settings()
        user, pw = dlg.beatport_credentials()
        self.qsettings.setValue("beatport_user", user)
        if dlg.remember_password():
            if not credentials.save_password(user, pw):
                self.append_log("⚠ Passwort konnte nicht im Schlüsselbund gespeichert werden.")
        else:
            credentials.save_password(user, "")
        if (user, pw) != (self._username, self._password):
            self._username, self._password = user, pw
            self._beatport = None
            self.login_label.setText("Beatport: Zugangsdaten geändert – wird beim Abgleich angemeldet")
        self._sources_cache = None
        self.save_settings()
        self.refresh_targets()

    # ------------------------------------------------------------ Aktionen
    def start_scan(self) -> None:
        src = Path(self.src_edit.text())
        if not src.is_dir():
            QMessageBox.warning(self, "Scannen", "Bitte einen gültigen Quellordner wählen.")
            return
        self.save_settings()
        result: list[LibraryItem] = []

        def job(w: Worker):
            w.log.emit(f"Scanne {src} …")
            tracks = scan(src, lambda i, n, p: w.progress.emit(i, n, p.name))
            result.extend(LibraryItem(local=t) for t in tracks)
            w.log.emit(f"{len(tracks)} Audiodateien gefunden.")

        def done():
            self.items = result
            self.mark_already_moved()
            self.fill_table()
            self.refresh_targets()

        self.run_worker(job, done)

    def mark_already_moved(self) -> None:
        """Dateien, die laut Umzugs-Journal schon in der neuen Library liegen, als erledigt zeigen."""
        journal = Journal()
        n = 0
        for it in self.items:
            dst = journal.target_for(it.local.path)
            if dst and Path(dst).is_file():
                it.status, it.enabled, it.target = MatchStatus.DONE, False, Path(dst)
                it.message = "bereits in die neue Library übernommen"
                n += 1
            elif journal.is_target(it.local.path):
                it.previous = it.local.path  # Datei aus der neuen Library: wird beim Bearbeiten ersetzt
        journal.close()
        if n:
            self.append_log(f"{n} Dateien wurden schon früher übernommen und sind als „erledigt“ markiert "
                            "(Rechtsklick → „Erneut bearbeiten“, um sie noch einmal zu verarbeiten).")

    def reprocess(self, rows: list[int]) -> None:
        for r in rows:
            it = self.items[r]
            if it.status == MatchStatus.DONE:
                if it.target and it.target.exists():
                    it.previous = it.target  # wird nach dem erneuten Ausführen ersetzt, nicht verdoppelt
                it.status = MatchStatus.MANUAL if it.selected else MatchStatus.PENDING
                it.enabled, it.message = True, "erneut bearbeiten"
        self.refresh_targets()

    # ------------------------------------------------------------ Rekordbox
    def _open_rekordbox(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return rbdb.open_db(), Journal()
        finally:
            QApplication.restoreOverrideCursor()

    def rekordbox_status(self) -> None:
        try:
            db, journal = self._open_rekordbox()
        except Exception as e:
            QMessageBox.warning(self, "Rekordbox", str(e))
            return
        try:
            text = rbdb.summary(rbdb.plan(db, journal))
        finally:
            db.close()
            journal.close()
        self._show_text("Rekordbox – Umzugs-Status", text)

    def rekordbox_switch(self) -> None:
        if rbdb.rekordbox_running():
            QMessageBox.warning(self, "Rekordbox umstellen", "Bitte zuerst Rekordbox beenden.")
            return
        try:
            db, journal = self._open_rekordbox()
        except Exception as e:
            QMessageBox.warning(self, "Rekordbox", str(e))
            return
        try:
            steps = rbdb.plan(db, journal)
            n = sum(s.action == rbdb.SWITCH for s in steps)
            if not n:
                journal.mark_switched([s.key or s.old for s in steps if s.action == rbdb.ALREADY])
                self._show_text("Rekordbox umstellen", "Nichts umzustellen.\n\n" + rbdb.summary(steps))
                return
            msg = (f"{n} Tracks in Rekordbox auf die neue Library umstellen?\n\n"
                   "Sterne, Farben, Cues, Playlists und Import-Datum bleiben erhalten. "
                   "Vorher werden master.db und die Analyse-Dateien gesichert.")
            if QMessageBox.question(self, "Rekordbox umstellen", msg) != QMessageBox.Yes:
                return
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                backup_dir = rbdb.backup(db, steps)
                warnings: list[str] = []
                done = rbdb.apply(db, steps, journal, warnings)
                problems = rbdb.verify(db, steps)
            finally:
                QApplication.restoreOverrideCursor()
            self.append_log(f"Rekordbox: {done} Tracks umgestellt, Sicherung: {backup_dir}")
            for w in warnings:
                self.append_log("  Hinweis: " + w)
            if problems:
                self._show_text("Rekordbox umstellen – Probleme",
                                f"{done} umgestellt, aber {len(problems)} Probleme:\n\n" + "\n".join(problems[:50])
                                + "\n\nZurück zum vorherigen Stand: Menü Rekordbox → Letzte Sicherung zurückspielen")
            else:
                QMessageBox.information(self, "Rekordbox umstellen",
                                        f"{done} Tracks umgestellt und geprüft ✔\nRekordbox kann wieder gestartet werden.")
        except Exception as e:
            self.append_log("Rekordbox umstellen – Fehler:\n" + traceback.format_exc())
            QMessageBox.critical(self, "Rekordbox umstellen", f"Fehler: {e}\n\nNichts wurde gespeichert, "
                                 "oder die Sicherung kann über das Menü zurückgespielt werden.")
        finally:
            db.close()
            journal.close()

    def rename_library(self) -> None:
        """Ganzen Library-Ordner umbenennen (z. B. LibOrganized → Library) und Rekordbox nachziehen."""
        from PySide6.QtWidgets import QInputDialog

        from . import relocate

        if self.busy():
            return
        old_root = Path(self.dst_edit.text())
        if not old_root.is_dir():
            QMessageBox.warning(self, "Library umbenennen", "Bitte oben die Ziel-Bibliothek wählen.")
            return
        if rbdb.rekordbox_running():
            QMessageBox.warning(self, "Library umbenennen", "Bitte zuerst Rekordbox beenden.")
            return
        new_text, ok = QInputDialog.getText(self, "Library umbenennen", f"Neuer Pfad für\n{old_root}:",
                                            text=str(old_root.with_name("Library")))
        if not ok or not new_text.strip():
            return
        new_root = Path(new_text.strip()).expanduser()
        err = relocate.check(old_root, new_root)
        if err:
            QMessageBox.warning(self, "Library umbenennen", err)
            return
        if QMessageBox.question(self, "Library umbenennen",
                                f"„{old_root.name}“ wird zu\n{new_root}\n\nDanach wird Rekordbox auf die neuen Pfade "
                                "umgestellt (mit Sicherung). Weiter?") != QMessageBox.Yes:
            return
        journal = Journal()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            n = relocate.rename_library(old_root, new_root, journal)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Library umbenennen", f"Fehler: {e}")
            return
        finally:
            journal.close()
        QApplication.restoreOverrideCursor()
        self.append_log(f"Library umbenannt: {old_root} → {new_root} ({n} Dateien im Umzugs-Journal)")
        self.dst_edit.setText(str(new_root))
        if Path(self.src_edit.text() or "/") == old_root:
            self.src_edit.setText(str(new_root))
        self.save_settings()
        self.rekordbox_switch()

    def rekordbox_restore(self) -> None:
        b = rbdb.latest_backup()
        if not b:
            QMessageBox.information(self, "Rekordbox", "Keine Sicherung vorhanden.")
            return
        if rbdb.rekordbox_running():
            QMessageBox.warning(self, "Rekordbox", "Bitte zuerst Rekordbox beenden.")
            return
        if QMessageBox.question(self, "Rekordbox", f"Sicherung vom {b.name} zurückspielen?") != QMessageBox.Yes:
            return
        master = rbdb.restore(b)
        QMessageBox.information(self, "Rekordbox", f"Sicherung zurückgespielt ({master}).")

    def _show_text(self, title: str, text: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(900, 520)
        lay = QVBoxLayout(dlg)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        lay.addWidget(view)
        b = QPushButton("Schließen")
        b.clicked.connect(dlg.accept)
        lay.addWidget(b)
        dlg.exec()

    def start_match(self) -> None:
        sources = self.sources()
        if not sources:
            QMessageBox.warning(self, "Abgleichen", "Keine Quelle aktiv. Bitte in den Einstellungen Beatport-Zugangsdaten "
                                                    "eintragen oder Discogs/Bandcamp aktivieren.")
            return
        if self._beatport is not None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._beatport.ensure_token()
                self.login_label.setText(f"Beatport: ✔ angemeldet als <b>{self._username}</b>")
            except Exception as e:
                self.login_label.setText("Beatport: ✘ Anmeldung fehlgeschlagen")
                QApplication.restoreOverrideCursor()
                if QMessageBox.question(self, "Beatport", f"{e}\n\nOhne Beatport mit den anderen Quellen weitermachen?") != QMessageBox.Yes:
                    return
                sources = [s for s in sources if s is not self._beatport]
            else:
                QApplication.restoreOverrideCursor()
        else:
            self.append_log("Hinweis: Keine Beatport-Zugangsdaten – es wird nur in Discogs/Bandcamp gesucht.")
        self.append_log("Quellen: " + " → ".join(s.name for s in sources))
        todo = [i for i, it in enumerate(self.items) if it.status not in (MatchStatus.MATCHED, MatchStatus.MANUAL, MatchStatus.DONE)]
        thr = self.settings.match_threshold

        def job(w: Worker):
            for n, row in enumerate(todo, 1):
                if w.cancelled:
                    break
                it = self.items[row]
                w.progress.emit(n, len(todo), it.local.path.name)
                match_item(it, sources, match_threshold=thr)
                if it.message:
                    w.log.emit(f"{it.local.path.name}: {it.message}")
                w.item_done.emit(row)
            if not w.cancelled:
                w.log.emit("Prüfe, ob EPs/Alben einheitlich aus einem Release kommen …")
                for line in harmonize(self.items, sources, thr, cancelled=lambda: w.cancelled):
                    w.log.emit(line)
            w.log.emit("Abgleich fertig.")

        self.run_worker(job, self.refresh_targets)

    def apply_auto(self) -> None:
        rows = [i for i, it in enumerate(self.items) if self.is_auto_ready(it)]
        self.start_apply(rows, confirm_details=False)

    def apply_checked(self) -> None:
        rows = [i for i, it in enumerate(self.items) if it.enabled and it.status != MatchStatus.DONE]
        self.start_apply(rows)

    def start_apply(self, rows: list[int], confirm_details: bool = True) -> None:
        if not self.dst_edit.text():
            QMessageBox.warning(self, "Ausführen", "Bitte einen Ziel-Ordner wählen.")
            return
        err = validate_template(self.settings.template)
        if err:
            QMessageBox.warning(self, "Ausführen", err)
            return
        self.save_settings()
        # Ziele für genau diese Einträge berechnen (auch wenn sie nicht markiert sind)
        for r in rows:
            self.items[r].enabled = True
        self.refresh_targets()
        rows = [r for r in rows if self.items[r].target and self.items[r].status != MatchStatus.DONE]
        if not rows:
            QMessageBox.information(self, "Ausführen", "Nichts zu tun.")
            return
        s = self.settings
        items = [self.items[r] for r in rows]
        n_conv = sum(i.local.needs_conversion for i in items)
        n_unmatched = sum(i.selected is None for i in items)
        n_incomplete = sum(bool(self.missing(i)) for i in items if i.selected)
        lines = [f"{len(rows)} Tracks verarbeiten?", "",
                 f"• {n_conv} werden zu MP3 320 kbit/s konvertiert"]
        if confirm_details:
            if n_unmatched:
                lines.append(f"• {n_unmatched} ohne Treffer (landen ohne neue Tags unter „_Unbekannt“)")
            if n_incomplete:
                lines.append(f"• ⚠ {n_incomplete} mit fehlenden Pflichtfeldern")
        lines.append("• Modus: " + ("VERSCHIEBEN – Originale (auch FLAC/WAV) werden entfernt!" if s.move
                                    else "Kopieren – Originale bleiben unverändert"))
        if s.clean_tags:
            lines.append("• Vorhandene Tags werden ersetzt (Backup der alten Tags wird angelegt)")
        if QMessageBox.question(self, "Ausführen", "\n".join(lines)) != QMessageBox.Yes:
            return
        opts = ApplyOptions(move=s.move, label_fallback=s.label_fallback,
                            tag=TagOptions(key_format=s.key_format, mix_in_title=s.mix_in_title,
                                           hide_original_mix=s.hide_original_mix,
                                           embed_cover=s.embed_cover, clean=s.clean_tags))
        cover_loader = make_cover_loader(list(self.url_clients().values()))

        def job(w: Worker):
            ok = fail = 0
            journal = Journal()  # eigene Verbindung im Hintergrund-Thread
            for n, row in enumerate(rows, 1):
                if w.cancelled:
                    break
                it = self.items[row]
                w.progress.emit(n, len(rows), it.local.path.name)
                try:
                    result = apply_item(it, opts, cover_loader, effective_tags(it, s))
                    journal.record(it.local.path, it.target)  # für das spätere Umstellen in Rekordbox
                    it.message = result
                    it.enabled = False
                    it.status = MatchStatus.DONE
                    ok += 1
                    w.log.emit(f"✔ {it.local.path.name} → {it.target} ({result})")
                except Exception as e:
                    it.message = str(e)
                    fail += 1
                    w.log.emit(f"✘ {it.local.path.name}: {e}")
                w.item_done.emit(row)
            w.log.emit(f"Fertig: {ok} erfolgreich, {fail} fehlgeschlagen.")
            if s.clean_tags and ok:
                w.log.emit(f"Backup der alten Tags: {backup_dir()}")

        self.run_worker(job, self.update_buttons)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MusicLibOrganizer")
    # Qt-Standardtexte (OK/Abbrechen/Speichern …) in der Systemsprache
    translator = QTranslator(app)
    if translator.load(QLocale.system(), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    win = MainWindow()
    win.show()
    if os.environ.get("MUSICLIB_SMOKE_TEST"):  # für den automatischen Build-Test: starten und gleich beenden
        from PySide6.QtCore import QTimer

        print(f"MusicLibOrganizer {__version__} gestartet")
        import pyrekordbox.db6.database  # noqa: F401  (im App-Paket enthalten?)
        import sqlcipher3  # noqa: F401
        print("Rekordbox-Datenbankzugriff verfügbar")
        QTimer.singleShot(1500, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
