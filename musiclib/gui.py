"""Grafische Oberfläche (PySide6) für den MusicLibOrganizer."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .beatport import BeatportClient, BeatportError
from .matcher import match_item, rank
from .models import Candidate, LibraryItem, MatchStatus
from .organizer import DEFAULT_TEMPLATE, PLACEHOLDERS, assign_targets, validate_template
from .pipeline import ApplyOptions, apply_item, make_cover_loader
from .scanner import scan
from .tagger import TagOptions

STATUS_COLORS = {
    MatchStatus.MATCHED: QColor(46, 160, 67, 70),
    MatchStatus.UNCERTAIN: QColor(219, 171, 9, 80),
    MatchStatus.NOT_FOUND: QColor(207, 34, 46, 60),
    MatchStatus.ERROR: QColor(207, 34, 46, 110),
    MatchStatus.DONE: QColor(9, 105, 218, 70),
}

COLUMNS = ["", "Status", "Datei", "Format", "Lokal erkannt", "Beatport-Treffer", "Score", "Genre", "BPM", "Key", "Ziel"]
COL_CHECK, COL_STATUS, COL_FILE, COL_FMT, COL_LOCAL, COL_BP, COL_SCORE, COL_GENRE, COL_BPM, COL_KEY, COL_TARGET = range(len(COLUMNS))


class Worker(QThread):
    """Führt eine Funktion im Hintergrund aus; die Funktion bekommt einen report-Callback."""

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


class CandidateDialog(QDialog):
    """Erlaubt, einen anderen Beatport-Treffer zu wählen oder manuell zu suchen."""

    def __init__(self, parent, item: LibraryItem, client_factory: Callable[[], BeatportClient]):
        super().__init__(parent)
        self.setWindowTitle("Beatport-Treffer wählen")
        self.resize(720, 420)
        self.item = item
        self.client_factory = client_factory
        self.candidates: list[Candidate] = list(item.candidates)
        self.choice: Candidate | None | bool = False  # False = abgebrochen, None = kein Treffer

        lay = QVBoxLayout(self)
        loc = item.local
        lay.addWidget(QLabel(f"<b>Datei:</b> {loc.path.name}<br><b>Erkannt:</b> {loc.artist} – {loc.title} {f'({loc.mix})' if loc.mix else ''}"))

        search_row = QHBoxLayout()
        self.query = QLineEdit(" ".join(p for p in (loc.artist, loc.title, loc.mix) if p))
        btn = QPushButton("Suchen")
        btn.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        search_row.addWidget(self.query)
        search_row.addWidget(btn)
        lay.addLayout(search_row)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self.accept_selected())
        lay.addWidget(self.list)
        self._fill()

        buttons = QDialogButtonBox()
        ok = buttons.addButton("Übernehmen", QDialogButtonBox.AcceptRole)
        none = buttons.addButton("Kein Treffer", QDialogButtonBox.DestructiveRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        ok.clicked.connect(self.accept_selected)
        none.clicked.connect(self.accept_none)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _fill(self) -> None:
        self.list.clear()
        for c in self.candidates:
            t = c.track
            text = f"{c.score:4.0%}   {t.display}   [{t.genre}, {t.bpm} BPM, {t.key_camelot or t.key_name}, {t.label}, {t.release_date[:4]}]"
            li = QListWidgetItem(text)
            if self.item.selected and t.id == self.item.selected.id:
                li.setSelected(True)
            self.list.addItem(li)
        if self.list.count() and not self.list.selectedItems():
            self.list.setCurrentRow(0)

    def search(self) -> None:
        q = self.query.text().strip()
        if not q:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            found = self.client_factory().search_tracks(q, per_page=25)
            self.candidates = rank(self.item.local, found)
            self._fill()
        except Exception as e:
            QMessageBox.warning(self, "Suche fehlgeschlagen", str(e))
        finally:
            QApplication.restoreOverrideCursor()

    def accept_selected(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        self.choice = self.candidates[row]
        self.accept()

    def accept_none(self) -> None:
        self.choice = None
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, parent, username: str):
        super().__init__(parent)
        self.setWindowTitle("Beatport-Anmeldung")
        form = QFormLayout(self)
        self.user = QLineEdit(username)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        form.addRow("Benutzername", self.user)
        form.addRow("Passwort", self.pw)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"MusicLibOrganizer {__version__}")
        self.resize(1400, 850)
        self.settings = QSettings("MusicLibOrganizer", "MusicLibOrganizer")
        self.items: list[LibraryItem] = []
        self.worker: Worker | None = None
        self._client: BeatportClient | None = None
        self._username = os.environ.get("BEATPORT_USERNAME", "")
        self._password = os.environ.get("BEATPORT_PASSWORD", "")
        self._updating_table = False

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- Ordner & Optionen
        top = QHBoxLayout()
        root.addLayout(top)

        folders = QGroupBox("Ordner")
        fg = QGridLayout(folders)
        self.src_edit = QLineEdit(self.settings.value("source", ""))
        self.dst_edit = QLineEdit(self.settings.value("target", ""))
        for row, (label, edit) in enumerate((("Quelle", self.src_edit), ("Ziel-Bibliothek", self.dst_edit))):
            fg.addWidget(QLabel(label), row, 0)
            fg.addWidget(edit, row, 1)
            b = QPushButton("…")
            b.setFixedWidth(32)
            b.clicked.connect(lambda _=False, e=edit: self.pick_dir(e))
            fg.addWidget(b, row, 2)
        top.addWidget(folders, 3)

        opts = QGroupBox("Optionen")
        og = QFormLayout(opts)
        self.template_edit = QLineEdit(self.settings.value("template", DEFAULT_TEMPLATE))
        self.template_edit.setToolTip("Platzhalter: " + ", ".join("{" + p + "}" for p in PLACEHOLDERS) + "\n'/' erzeugt Unterordner.")
        self.template_edit.editingFinished.connect(self.refresh_targets)
        og.addRow("Dateiname-Vorlage", self.template_edit)

        self.key_combo = QComboBox()
        self.key_combo.addItem("Camelot (z. B. 8A)", "camelot")
        self.key_combo.addItem("Tonart (z. B. A Minor)", "musical")
        self.key_combo.setCurrentIndex(max(0, self.key_combo.findData(self.settings.value("key_format", "camelot"))))
        self.key_combo.currentIndexChanged.connect(self.refresh_targets)
        og.addRow("Key-Format", self.key_combo)

        checks = QHBoxLayout()
        self.mix_check = QCheckBox("Mix-Name im Titel")
        self.mix_check.setChecked(self.settings.value("mix_in_title", True, type=bool))
        self.cover_check = QCheckBox("Cover einbetten")
        self.cover_check.setChecked(self.settings.value("embed_cover", True, type=bool))
        checks.addWidget(self.mix_check)
        checks.addWidget(self.cover_check)
        og.addRow(checks)

        mode = QHBoxLayout()
        self.copy_radio = QRadioButton("Kopieren (Originale bleiben)")
        self.move_radio = QRadioButton("Verschieben (Originale werden entfernt)")
        grp = QButtonGroup(self)
        grp.addButton(self.copy_radio)
        grp.addButton(self.move_radio)
        (self.move_radio if self.settings.value("move", False, type=bool) else self.copy_radio).setChecked(True)
        mode.addWidget(self.copy_radio)
        mode.addWidget(self.move_radio)
        og.addRow(mode)
        top.addWidget(opts, 4)

        bp = QGroupBox("Beatport")
        bl = QVBoxLayout(bp)
        self.login_label = QLabel("Nicht angemeldet")
        self.login_label.setWordWrap(True)
        self.login_btn = QPushButton("Anmelden")
        self.login_btn.clicked.connect(self.login)
        bl.addWidget(self.login_label)
        bl.addWidget(self.login_btn)
        bl.addStretch()
        top.addWidget(bp, 1)

        # --- Aktionen
        actions = QHBoxLayout()
        self.scan_btn = QPushButton("1. Scannen")
        self.match_btn = QPushButton("2. Bei Beatport abgleichen")
        self.apply_btn = QPushButton("3. Ausführen")
        self.cancel_btn = QPushButton("Abbrechen")
        self.cancel_btn.setEnabled(False)
        self.scan_btn.clicked.connect(self.start_scan)
        self.match_btn.clicked.connect(self.start_match)
        self.apply_btn.clicked.connect(self.start_apply)
        self.cancel_btn.clicked.connect(self.cancel)
        for b in (self.scan_btn, self.match_btn, self.apply_btn):
            b.setMinimumHeight(32)
            actions.addWidget(b)
        actions.addWidget(self.cancel_btn)
        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m")
        actions.addWidget(self.progress, 1)
        self.summary = QLabel("")
        actions.addWidget(self.summary)
        root.addLayout(actions)

        # --- Tabelle + Log
        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        for col, w in ((COL_CHECK, 28), (COL_STATUS, 100), (COL_FILE, 230), (COL_FMT, 50), (COL_LOCAL, 260),
                       (COL_BP, 300), (COL_SCORE, 55), (COL_GENRE, 110), (COL_BPM, 45), (COL_KEY, 70)):
            self.table.setColumnWidth(col, w)
        self.table.cellDoubleClicked.connect(self.edit_match)
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.setToolTip("Doppelklick: anderen Beatport-Treffer wählen oder manuell suchen")

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        split.addWidget(self.table)
        split.addWidget(self.log_view)
        split.setSizes([650, 150])
        root.addWidget(split, 1)

        m = self.menuBar().addMenu("Auswahl")
        for text, fn in (("Alle aktivieren", lambda: self.set_enabled(lambda i: True)),
                         ("Alle deaktivieren", lambda: self.set_enabled(lambda i: False)),
                         ("Nur sichere Treffer aktivieren", lambda: self.set_enabled(lambda i: i.status == MatchStatus.MATCHED)),
                         ("Unsichere Treffer übernehmen", self.accept_uncertain)):
            a = QAction(text, self)
            a.triggered.connect(fn)
            m.addAction(a)

        if self._username and self._password:
            self.login_label.setText(f"Zugangsdaten aus Umgebung: {self._username}")
        self.update_buttons()

    # ------------------------------------------------------------ helpers
    def pick_dir(self, edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Ordner wählen", edit.text() or str(Path.home()))
        if d:
            edit.setText(d)

    def append_log(self, msg: str) -> None:
        self.log_view.appendPlainText(msg)

    def client(self) -> BeatportClient:
        if self._client is None:
            if not (self._username and self._password):
                raise BeatportError("Bitte zuerst bei Beatport anmelden.")
            self._client = BeatportClient(self._username, self._password)
        return self._client

    def tag_options(self) -> TagOptions:
        return TagOptions(key_format=self.key_combo.currentData(), mix_in_title=self.mix_check.isChecked(),
                          embed_cover=self.cover_check.isChecked())

    def save_settings(self) -> None:
        s = self.settings
        s.setValue("source", self.src_edit.text())
        s.setValue("target", self.dst_edit.text())
        s.setValue("template", self.template_edit.text())
        s.setValue("key_format", self.key_combo.currentData())
        s.setValue("mix_in_title", self.mix_check.isChecked())
        s.setValue("embed_cover", self.cover_check.isChecked())
        s.setValue("move", self.move_radio.isChecked())

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
        self.scan_btn.setEnabled(not busy)
        self.match_btn.setEnabled(not busy and has_items)
        self.apply_btn.setEnabled(not busy and has_items)
        self.cancel_btn.setEnabled(busy)
        self.login_btn.setEnabled(not busy)
        counts = {s: 0 for s in MatchStatus}
        for i in self.items:
            counts[i.status] += 1
        if has_items:
            self.summary.setText(
                f"{len(self.items)} Dateien · {counts[MatchStatus.MATCHED]} gefunden · "
                f"{counts[MatchStatus.UNCERTAIN]} unsicher · {counts[MatchStatus.NOT_FOUND]} nicht gefunden · "
                f"{sum(i.local.needs_conversion for i in self.items)} zu konvertieren"
                + (f" · {counts[MatchStatus.DONE]} erledigt" if counts[MatchStatus.DONE] else ""))
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

    # ------------------------------------------------------------ table
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
        loc, bp = it.local, it.selected
        target_root = Path(self.dst_edit.text()) if self.dst_edit.text() else None
        target = ""
        if it.target:
            try:
                target = str(it.target.relative_to(target_root)) if target_root else str(it.target)
            except ValueError:
                target = str(it.target)
        values = {
            COL_STATUS: it.status.value,
            COL_FILE: loc.path.name,
            COL_FMT: loc.format + (" → mp3" if loc.needs_conversion else ""),
            COL_LOCAL: f"{loc.artist} – {loc.title}" + (f" ({loc.mix})" if loc.mix else ""),
            COL_BP: bp.display if bp else "",
            COL_SCORE: f"{it.score:.0%}" if it.candidates else "",
            COL_GENRE: bp.genre if bp else "",
            COL_BPM: str(bp.bpm or "") if bp else "",
            COL_KEY: (bp.key_camelot if self.key_combo.currentData() == "camelot" else bp.key_name) if bp else "",
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
            cell.setToolTip(it.message if col == COL_STATUS and it.message else str(loc.path) if col == COL_FILE else val)
            cell.setBackground(color if color is not None and col == COL_STATUS else QColor(0, 0, 0, 0))
        self._updating_table = False

    def on_item_changed(self, cell: QTableWidgetItem) -> None:
        if self._updating_table or cell.column() != COL_CHECK:
            return
        self.items[cell.row()].enabled = cell.checkState() == Qt.Checked
        self.refresh_targets()

    def set_enabled(self, pred: Callable[[LibraryItem], bool]) -> None:
        for i in self.items:
            i.enabled = pred(i)
        self.refresh_targets()

    def accept_uncertain(self) -> None:
        for i in self.items:
            if i.status == MatchStatus.UNCERTAIN:
                i.status = MatchStatus.MATCHED
        self.refresh_targets()

    def refresh_targets(self) -> None:
        if self.busy():
            return
        err = validate_template(self.template_edit.text())
        if err:
            self.statusBar().showMessage(err)
            return
        if self.items and self.dst_edit.text():
            assign_targets(self.items, Path(self.dst_edit.text()), self.template_edit.text(), self.key_combo.currentData())
        for row in range(len(self.items)):
            self.update_row(row)
        self.update_buttons()

    def edit_match(self, row: int, _col: int) -> None:
        if self.busy():
            return
        item = self.items[row]
        dlg = CandidateDialog(self, item, self.client)
        if dlg.exec() != QDialog.Accepted or dlg.choice is False:
            return
        if dlg.choice is None:
            item.selected, item.status, item.score = None, MatchStatus.NOT_FOUND, 0.0
        else:
            item.selected, item.score, item.status = dlg.choice.track, dlg.choice.score, MatchStatus.MATCHED
            if dlg.choice not in item.candidates:
                item.candidates = dlg.candidates
            item.message = "manuell gewählt"
        self.refresh_targets()

    # ------------------------------------------------------------ actions
    def login(self) -> None:
        if not (self._username and self._password):
            dlg = LoginDialog(self, self._username)
            if dlg.exec() != QDialog.Accepted:
                return
            self._username, self._password = dlg.user.text().strip(), dlg.pw.text()
        self._client = None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.client().ensure_token()
            self.login_label.setText(f"✔ Angemeldet als <b>{self._username}</b>")
            self.append_log(f"Beatport: angemeldet als {self._username}")
        except Exception as e:
            self._client = None
            self._password = ""
            self.login_label.setText("✘ Anmeldung fehlgeschlagen")
            QMessageBox.warning(self, "Beatport", str(e))
        finally:
            QApplication.restoreOverrideCursor()

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
        try:
            client = self.client()
            client.ensure_token()
        except Exception as e:
            QMessageBox.warning(self, "Beatport", str(e))
            return
        self.login_label.setText(f"✔ Angemeldet als <b>{self._username}</b>")
        todo = [i for i, it in enumerate(self.items)
                if it.status not in (MatchStatus.MATCHED, MatchStatus.DONE) or not it.selected]

        def job(w: Worker):
            for n, row in enumerate(todo, 1):
                if w.cancelled:
                    break
                it = self.items[row]
                w.progress.emit(n, len(todo), it.local.path.name)
                match_item(it, client)
                if it.status == MatchStatus.ERROR:
                    w.log.emit(f"Fehler bei {it.local.path.name}: {it.message}")
                w.item_done.emit(row)
            w.log.emit("Abgleich fertig.")

        self.run_worker(job, self.refresh_targets)

    def start_apply(self) -> None:
        dst = self.dst_edit.text()
        if not dst:
            QMessageBox.warning(self, "Ausführen", "Bitte einen Ziel-Ordner wählen.")
            return
        err = validate_template(self.template_edit.text())
        if err:
            QMessageBox.warning(self, "Ausführen", err)
            return
        self.save_settings()
        self.refresh_targets()
        todo = [i for i, it in enumerate(self.items) if it.enabled and it.target]
        if not todo:
            QMessageBox.information(self, "Ausführen", "Keine aktiven Einträge.")
            return
        move = self.move_radio.isChecked()
        n_conv = sum(self.items[i].local.needs_conversion for i in todo)
        n_unmatched = sum(self.items[i].selected is None for i in todo)
        msg = (f"{len(todo)} Dateien verarbeiten?\n\n"
               f"• {n_conv} werden zu MP3 320 kbit/s konvertiert\n"
               f"• {n_unmatched} ohne Beatport-Treffer (landen ohne neue Tags im Ziel)\n"
               f"• Modus: {'VERSCHIEBEN – Originale (auch FLAC/WAV) werden entfernt!' if move else 'Kopieren – Originale bleiben unverändert'}")
        if QMessageBox.question(self, "Ausführen", msg) != QMessageBox.Yes:
            return
        opts = ApplyOptions(move=move, tag=self.tag_options())
        cover_loader = make_cover_loader(self._client) if self._client else None

        def job(w: Worker):
            ok = fail = 0
            for n, row in enumerate(todo, 1):
                if w.cancelled:
                    break
                it = self.items[row]
                w.progress.emit(n, len(todo), it.local.path.name)
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

        self.run_worker(job, self.update_buttons)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MusicLibOrganizer")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
