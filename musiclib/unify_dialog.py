"""Dialog: Schreibweisen vereinheitlichen – pro gefundener Variante eine Schreibweise wählen."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .tagger import clean_text
from .unify import Rule


class UnifyDialog(QDialog):
    def __init__(self, parent, rules: list[Rule]):
        super().__init__(parent)
        self.rules = rules
        self.setWindowTitle("Schreibweisen vereinheitlichen")
        self.setSizeGripEnabled(True)
        self.resize(1000, 600)
        lay = QVBoxLayout(self)
        info = QLabel(
            f"{len(rules)} Namen kommen in verschiedenen Schreibweisen vor. Wähle pro Zeile die richtige "
            "(oder tippe eine eigene). Tags werden neu geschrieben, Ordner und Dateinamen angepasst; "
            "danach werden die Pfade in Rekordbox umgestellt – Sterne, Cues und Playlists bleiben erhalten.")
        info.setWordWrap(True)
        lay.addWidget(info)

        self.table = QTableWidget(len(rules), 4)
        self.table.setHorizontalHeaderLabels(["", "Feld", "Vorkommende Schreibweisen (Anzahl Dateien)", "Neue Schreibweise"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(3, 280)
        self.checks: list[QCheckBox] = []
        self.combos: list[QComboBox] = []
        for row, rule in enumerate(rules):
            check = QCheckBox()
            check.setChecked(rule.enabled)
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(6, 0, 6, 0)
            hl.addWidget(check)
            self.table.setCellWidget(row, 0, holder)
            self.table.setItem(row, 1, QTableWidgetItem(rule.label))
            shown = "   |   ".join(f"{_visible(s)} ({n})" for s, n in rule.spellings.items())
            item = QTableWidgetItem(shown)
            item.setToolTip(shown)
            self.table.setItem(row, 2, item)
            combo = QComboBox()
            combo.setEditable(rule.field != "mix")  # „(Original Mix)“ kann nur wegfallen
            options = list(dict.fromkeys([rule.target] + [clean_text(s) for s in rule.spellings]))
            combo.addItems(options)
            combo.setCurrentText(rule.target)
            self.table.setCellWidget(row, 3, combo)
            self.checks.append(check)
            self.combos.append(combo)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        for text, state in (("Alle an", True), ("Alle aus", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=state: [c.setChecked(s) for c in self.checks])
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Weiter (Vorschau)")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def result_rules(self) -> list[Rule]:
        for rule, check, combo in zip(self.rules, self.checks, self.combos):
            rule.enabled = check.isChecked()
            rule.target = clean_text(combo.currentText())
        return self.rules


def _visible(s: str) -> str:
    """Unsichtbare Zeichen sichtbar machen, damit man die Varianten unterscheiden kann."""
    import unicodedata

    out = s.replace("\ufeff", "⟨BOM⟩").replace("\u200b", "⟨ZWSP⟩")
    if unicodedata.normalize("NFC", out) != out:
        out = unicodedata.normalize("NFC", out) + " ⟨zerlegte Umlaute⟩"
    return out
