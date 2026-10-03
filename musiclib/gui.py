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
from .bandcamp import BandcampClient
from .beatport import BeatportClient
from .dialogs import CandidateDialog, MetadataDialog, SettingsDialog, meta_from_local
from .discogs import DiscogsClient
from .matcher import enrich, match_item
from .urlimport import assign_release, load_url, looks_like_url
from .models import LibraryItem, MatchStatus
from .organizer import assign_targets, validate_template
from .pipeline import ApplyOptions, apply_item, make_cover_loader
from .scanner import scan
from .settings import AppSettings, effective_meta, missing_fields
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
           "Genre", "Label", "Jahr", "BPM", "Key", "Fehlt", "Ziel"]
(COL_CHECK, COL_STATUS, COL_SOURCE, COL_FILE, COL_FMT, COL_LOCAL, COL_MATCH, COL_SCORE, COL_ALBUMARTIST, COL_TRACK,
 COL_GENRE, COL_LABEL, COL_YEAR, COL_BPM, COL_KEY, COL_MISSING, COL_TARGET) = range(len(COLUMNS))

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
        self._username = os.environ.get("BEATPORT_USERNAME", "")
        self._password = os.environ.get("BEATPORT_PASSWORD", "")
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
                       (COL_YEAR, 45), (COL_BPM, 40), (COL_KEY, 45), (COL_MISSING, 90)):
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
        a = QAction("Beenden", self)
        a.setShortcut(QKeySequence.Quit)
        a.triggered.connect(self.close)
        m.addAction(a)

        m = self.menuBar().addMenu("Auswahl")
        for text, fn in (("Alle markieren", lambda: self.set_enabled(lambda i: True)),
                         ("Keine markieren", lambda: self.set_enabled(lambda i: False)),
                         ("Nur Bereite markieren", lambda: self.set_enabled(self.is_auto_ready)),
                         ("Alle unsicheren Treffer bestätigen", self.confirm_all_uncertain)):
            a = QAction(text, self)
            a.triggered.connect(fn)
            m.addAction(a)

        if self._username and self._password:
            self.login_label.setText(f"Beatport: Zugangsdaten aus Umgebung ({self._username})")
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

    def set_enabled(self, pred: Callable[[LibraryItem], bool]) -> None:
        for i in self.items:
            i.enabled = i.status != MatchStatus.DONE and pred(i)
        self.refresh_targets()

    def confirm_all_uncertain(self) -> None:
        for i in self.items:
            if i.status == MatchStatus.UNCERTAIN and i.selected:
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
                           self.settings.key_format, self.settings.label_fallback)
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
        if any(self.items[r].status == MatchStatus.UNCERTAIN for r in rows):
            menu.addAction("Treffer bestätigen", lambda: self._confirm_rows(rows))
        menu.addAction("Markieren", lambda: self._set_rows(rows, True))
        menu.addAction("Nicht markieren", lambda: self._set_rows(rows, False))
        menu.addSeparator()
        menu.addAction("Nur diese ausführen", lambda: self.start_apply(rows))
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
            "URL eines Tracks oder Releases (Beatport, Discogs, Bandcamp):"
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
        self.refresh_targets()

    def edit_metadata(self, row: int) -> None:
        if self.busy():
            return
        item = self.items[row]
        meta = item.selected or meta_from_local(item.local)
        dlg = MetadataDialog(self, meta, self.settings, item.local, item.keep_tags)
        if dlg.exec() != QDialog.Accepted:
            return
        item.selected = dlg.result_meta()
        item.keep_tags = dlg.result_keep()
        item.status = MatchStatus.MANUAL
        item.message = "Metadaten bearbeitet"
        self.refresh_targets()

    # ------------------------------------------------------------ Einstellungen
    def open_settings(self) -> None:
        dlg = SettingsDialog(self, self.settings, self._username, self._password)
        if dlg.exec() != QDialog.Accepted:
            return
        self.settings = dlg.result_settings()
        user, pw = dlg.beatport_credentials()
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
            self.fill_table()
            self.refresh_targets()

        self.run_worker(job, done)

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
                                           embed_cover=s.embed_cover, clean=s.clean_tags))
        cover_loader = make_cover_loader(list(self.url_clients().values()))

        def job(w: Worker):
            ok = fail = 0
            for n, row in enumerate(rows, 1):
                if w.cancelled:
                    break
                it = self.items[row]
                w.progress.emit(n, len(rows), it.local.path.name)
                try:
                    result = apply_item(it, opts, cover_loader)
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
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
