"""Dialog: gemeinsame Release-Felder und Cover für mehrere Tracks auf einmal."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from . import covers
from .models import LibraryItem
from .release_edit import RELEASE_FIELDS, base_meta, common_values, parse_changes

MAX_EDGE = 1400        # größere Bilder werden verkleinert (Rekordbox braucht keine riesigen Cover)
MAX_KEEP_BYTES = 2_000_000
VARIES = "‹verschieden – leer lassen = unverändert›"


def normalize_cover(data: bytes) -> bytes:
    """Zu große Bilder verkleinern und als JPEG speichern; kleine Bilder unverändert lassen."""
    img = QImage.fromData(data)
    if img.isNull():
        raise covers.CoverError("Bild konnte nicht gelesen werden")
    if max(img.width(), img.height()) <= MAX_EDGE and len(data) <= MAX_KEEP_BYTES and covers.image_mime(data):
        return data
    if max(img.width(), img.height()) > MAX_EDGE:
        img = img.scaled(MAX_EDGE, MAX_EDGE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    buf = QByteArray()
    dev = QBuffer(buf)
    dev.open(QIODevice.WriteOnly)
    img.convertToFormat(QImage.Format_RGB32).save(dev, "JPG", 90)
    return bytes(buf.data())


class CoverDrop(QLabel):
    """Vorschau; nimmt Bilder per Drag & Drop an (Datei, Bild aus dem Browser oder Bild-URL)."""

    def __init__(self, on_image):
        super().__init__()
        self.on_image = on_image
        self.setAcceptDrops(True)
        self.setFixedSize(180, 180)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet("QLabel { border: 1px dashed gray; color: gray; }")

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasImage() or md.hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        try:
            if md.hasUrls() and md.urls()[0].isLocalFile():
                data = covers.load_file(Path(md.urls()[0].toLocalFile()))
            elif md.hasImage():
                img = QImage(md.imageData())
                buf = QByteArray()
                dev = QBuffer(buf)
                dev.open(QIODevice.WriteOnly)
                img.save(dev, "PNG")
                data = bytes(buf.data())
            elif md.hasUrls():
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    data = covers.load_url(md.urls()[0].toString())
                finally:
                    QApplication.restoreOverrideCursor()
            else:
                return
            self.on_image(data)
        except (covers.CoverError, OSError) as err:
            QMessageBox.warning(self, "Cover", str(err))


class ReleaseDialog(QDialog):
    def __init__(self, parent, items: list[LibraryItem]):
        super().__init__(parent)
        self.items = items
        self.setWindowTitle(f"Release bearbeiten – {len(items)} Track" + ("s" if len(items) != 1 else ""))
        self.setSizeGripEnabled(True)
        self.cover: bytes | None = None
        self.cover_changed = False
        lay = QVBoxLayout(self)

        names = [it.local.path.name for it in items]
        info = QLabel("<br>".join(names[:8]) + (f"<br>… und {len(names) - 8} weitere" if len(names) > 8 else ""))
        info.setStyleSheet("color: gray")
        lay.addWidget(info)

        row = QHBoxLayout()
        lay.addLayout(row)

        # --- Felder
        box = QGroupBox("Gemeinsame Felder – nur geänderte Felder werden übernommen")
        form = QFormLayout(box)
        common = self.common = common_values([base_meta(it) for it in items])
        self.edits: dict[str, QLineEdit] = {}
        self.touched: set[str] = set()
        for name, label, _num in RELEASE_FIELDS:
            e = QLineEdit(common[name] or "")
            if common[name] is None:
                e.setPlaceholderText(VARIES)
            e.textEdited.connect(lambda _t, n=name: self._touch(n))
            self.edits[name] = e
            form.addRow(label, e)
        self.renumber = QCheckBox("Tracknummern 1 … n neu vergeben (Trackanzahl = Anzahl der Tracks)")
        self.renumber.setToolTip("Reihenfolge: bisherige Tracknummer, sonst Reihenfolge in der Liste")
        form.addRow(self.renumber)
        row.addWidget(box, 1)

        # --- Cover
        cbox = QGroupBox("Cover")
        cl = QVBoxLayout(cbox)
        self.preview = CoverDrop(self.set_cover)
        cl.addWidget(self.preview)
        self.cover_info = QLabel()
        self.cover_info.setWordWrap(True)
        cl.addWidget(self.cover_info)
        for text, fn in (("Bild wählen…", self.pick_file), ("Bild-URL…", self.pick_url),
                         ("Eigenes Cover entfernen", self.clear_cover)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            cl.addWidget(b)
        cl.addStretch(1)
        row.addWidget(cbox)

        own = {it.cover for it in items}
        if len(own) == 1 and None not in own:
            self.cover = own.pop()
        self._show_cover()

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _touch(self, name: str) -> None:
        self.touched.add(name)
        self.edits[name].setStyleSheet("QLineEdit { background: rgba(46,160,67,40); }")

    # --- Cover
    def _show_cover(self) -> None:
        n = len(self.items)
        if self.cover:
            pm = QPixmap()
            pm.loadFromData(self.cover)
            self.preview.setPixmap(pm.scaled(176, 176, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.cover_info.setText("Eigenes Cover – wird bei allen Tracks eingebettet.")
            return
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Bild hierher ziehen\n(Datei, Bild oder Link aus dem Browser)")
        from_source = sum(bool(it.selected and it.selected.image_url) for it in self.items)
        from_file = sum(bool(not (it.selected and it.selected.image_url) and it.local.has_cover) for it in self.items)
        none = n - from_source - from_file
        parts = [f"{from_source}× von der Quelle"] if from_source else []
        parts += [f"{from_file}× bisheriges Cover der Datei"] if from_file else []
        parts += [f"<b>{none}× ohne Cover</b>"] if none else []
        self.cover_info.setText("Aktuell: " + ", ".join(parts))

    def set_cover(self, data: bytes) -> None:
        try:
            self.cover = normalize_cover(data)
        except covers.CoverError as e:
            QMessageBox.warning(self, "Cover", str(e))
            return
        self.cover_changed = True
        self._show_cover()

    def pick_file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Cover wählen", str(self.items[0].local.path.parent),
                                           "Bilder (*.jpg *.jpeg *.png)")
        if f:
            try:
                self.set_cover(covers.load_file(Path(f)))
            except (covers.CoverError, OSError) as e:
                QMessageBox.warning(self, "Cover", str(e))

    def pick_url(self) -> None:
        url, ok = QInputDialog.getText(self, "Cover von URL", "Bild-Adresse (Rechtsklick auf ein Bild → Bildadresse kopieren):")
        if not ok or not url.strip():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data = covers.load_url(url.strip())
        except covers.CoverError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Cover", str(e))
            return
        QApplication.restoreOverrideCursor()
        self.set_cover(data)

    def clear_cover(self) -> None:
        self.cover = None
        self.cover_changed = True
        self._show_cover()

    # --- Ergebnis
    def _accept(self) -> None:
        try:
            self.changes()
        except ValueError as e:
            QMessageBox.warning(self, "Release bearbeiten", str(e))
            return
        self.accept()

    def changes(self) -> dict[str, object]:
        # Ein „verschieden“-Feld, das wieder leer ist, bleibt unverändert
        names = [n for n in self.touched if self.common[n] is not None or self.edits[n].text().strip()]
        return parse_changes({n: self.edits[n].text() for n in names})
