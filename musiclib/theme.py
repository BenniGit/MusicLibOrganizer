"""Retro-Look im Stil von iTunes 5 (Mac OS X 10.4 Tiger, 2005).

Glatter, bläulicher Fensterverlauf statt gebürstetem Metall, glasige Aqua-Knöpfe in
Blau, eine gläserne LCD-Anzeige oben in der Mitte, weiß/hellblau gestreifte
Titelliste mit blauer Verlaufs-Auswahl und gläserne Spaltenköpfe. Gilt für alle
Fenster und Dialoge der App, unabhängig vom Hell-/Dunkelmodus des Systems.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QGradient, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPalette, QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

ICON_PATH = Path(__file__).resolve().parent / "resources" / "icon.png"

# Farben
WINDOW_TOP = "#E6EFFB"
WINDOW_BOTTOM = "#B4CDEE"
STRIPE = "#EDF3FE"
SELECT = "#3875D7"
INK = "#0E1E36"  # dunkles Marineblau statt Schwarz

FONT_FAMILIES = ["Lucida Grande", "Helvetica Neue", "Helvetica", "DejaVu Sans", "Arial"]


def _glass(top: str, upper: str, lower: str, bottom: str, horizontal: bool = False) -> str:
    """Aqua-Glas: heller oberer Teil, harte Kante in der Mitte, aufgehelltes unteres Ende."""
    x2, y2 = (1, 0) if horizontal else (0, 1)
    return (f"qlineargradient(x1:0, y1:0, x2:{x2}, y2:{y2}, "
            f"stop:0 {top}, stop:0.49 {upper}, stop:0.5 {lower}, stop:1 {bottom})")


GLASS = _glass("#F4F9FF", "#C4DDF8", "#9CC5F2", "#D9ECFD")           # normaler Knopf: hellblaues Glas
GLASS_STRONG = _glass("#D5E8FC", "#7FB4EE", "#4C91E3", "#A8D3FA")    # Standard-/Hauptknopf: kräftiges Blau
GLASS_PRESSED = _glass("#9CC6F2", "#4F8FE0", "#2B6FCF", "#7DB6F2")
GLASS_HEADER = _glass("#FFFFFF", "#E3EEFB", "#CFE1F7", "#EDF5FE")
GLASS_DISABLED = _glass("#F7FAFE", "#E7EEF7", "#DFE7F2", "#EEF3FA")
GLASS_SCROLL_V = _glass("#C8E2FB", "#6FA9EB", "#4C91E3", "#B9DCFB", horizontal=True)
GLASS_SCROLL_H = _glass("#C8E2FB", "#6FA9EB", "#4C91E3", "#B9DCFB")
LCD = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FBFDFF, stop:0.5 #E8F1FC, stop:1 #CADDF4)"
SELECTION = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6AA2EA, stop:1 #2E6BD0)"

STYLESHEET = f"""
* {{ color: {INK}; }}
QToolTip {{ background: #FFFFC7; color: #000; border: 1px solid #8C8C8C; padding: 2px 4px; }}

/* ---------- Glasknöpfe ---------- */
QPushButton, QToolButton {{
    border: 1px solid #4A78B8; border-radius: 11px; padding: 3px 14px; min-height: 18px; background: {GLASS};
}}
QPushButton:hover, QToolButton:hover {{ border-color: #23549C; }}
QPushButton:default, QPushButton[role="primary"] {{ border-color: #1F4E96; background: {GLASS_STRONG}; }}
QPushButton:pressed, QToolButton:pressed, QPushButton:checked, QPushButton:default:pressed,
QPushButton[role="primary"]:pressed {{ border-color: #173E7A; background: {GLASS_PRESSED}; color: #FFFFFF; }}
QPushButton:disabled, QToolButton:disabled {{ color: #8C9AAE; border-color: #A9BBD3; background: {GLASS_DISABLED}; }}
QPushButton::menu-indicator {{ subcontrol-origin: padding; subcontrol-position: center right; right: 6px; }}

/* Runde Knöpfe in der Kopfleiste (wie Zurück/Play/Vor) */
QPushButton[role="transport"] {{
    min-width: 42px; max-width: 42px; min-height: 42px; max-height: 42px;
    border-radius: 22px; padding: 0; font-size: 17px; font-weight: bold;
    border-color: #2D5FA6; background: {GLASS_STRONG};
}}
QPushButton[role="transport"]:pressed {{ background: {GLASS_PRESSED}; }}
QPushButton[role="transport"]:disabled {{ color: #93A6C2; border-color: #A9BBD3; background: {GLASS_DISABLED}; }}
QPushButton[role="transport"]::menu-indicator {{ image: none; width: 0; }}
QLabel#transportLabel {{ font-size: 10px; color: #23406B; }}

/* ---------- Gläserne LCD-Anzeige ---------- */
QFrame#lcd {{ border: 1px solid #5B7DAE; border-radius: 12px; background: {LCD}; }}
QFrame#lcd QLabel {{ color: {INK}; background: transparent; }}
QLabel#lcdTitle {{ font-weight: bold; }}
QLabel#lcdDetail {{ color: #3D5677; }}
QProgressBar#lcdProgress {{
    border: 1px solid #2D4F80; border-radius: 3px; background: #FFFFFF; max-height: 7px; min-height: 7px;
}}
QProgressBar#lcdProgress::chunk {{ border-radius: 2px; background: {GLASS_STRONG}; }}

/* ---------- Eingabefelder ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QListWidget, QTreeWidget, QListView, QTreeView {{
    background: #FFFFFF; border: 1px solid #7C98C0; border-top-color: #5A7AA8;
    selection-background-color: {SELECT}; selection-color: #FFFFFF;
}}
QLineEdit {{ border-radius: 4px; padding: 2px 4px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid #6FA3E8; padding: 1px 3px; }}
QLineEdit:disabled {{ background: #EEF2F8; color: #8C9AAE; }}

QComboBox {{
    border: 1px solid #4A78B8; border-radius: 10px; padding: 2px 24px 2px 10px; min-height: 18px;
    background: {GLASS};
}}
QComboBox::drop-down {{
    width: 20px; border-left: 1px solid #1F4E96;
    border-top-right-radius: 10px; border-bottom-right-radius: 10px; background: {GLASS_STRONG};
}}
QComboBox QAbstractItemView {{
    background: #FFFFFF; border: 1px solid #7C98C0;
    selection-background-color: {SELECT}; selection-color: #FFFFFF;
}}

QCheckBox, QRadioButton, QLabel {{ background: transparent; }}
QRadioButton::indicator {{
    width: 13px; height: 13px; border-radius: 7px; border: 1px solid #4A78B8; background: {GLASS};
}}
QRadioButton::indicator:checked {{
    border-color: #1F4E96;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 #10294F, stop:0.32 #10294F, stop:0.42 #6AA6EA, stop:1 #BFE0FB);
}}
QCheckBox::indicator, QTableView::indicator, QGroupBox::indicator {{
    width: 13px; height: 13px; border-radius: 3px; border: 1px solid #4A78B8; background: {GLASS};
}}
QCheckBox::indicator:checked, QTableView::indicator:checked, QGroupBox::indicator:checked {{
    border-color: #1F4E96; background: {GLASS_STRONG}; image: url({{check}});
}}
QCheckBox::indicator:disabled {{ border-color: #A9BBD3; background: {GLASS_DISABLED}; }}

QSpinBox, QDoubleSpinBox {{ border-radius: 4px; padding: 1px 18px 1px 4px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; width: 16px; border-left: 1px solid #4A78B8; background: {GLASS};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top right; border-top-right-radius: 4px; border-bottom: 1px solid #9DB6D8;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 4px; }}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{ background: {GLASS_PRESSED}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({{up}}); width: 8px; height: 5px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({{down}}); width: 8px; height: 5px; }}
QComboBox::down-arrow {{ image: url({{down_white}}); width: 9px; height: 6px; }}

QGroupBox {{
    border: 1px solid #8FAAD0; border-radius: 8px; margin-top: 14px; padding-top: 6px;
    background: rgba(255, 255, 255, 90);
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; font-weight: bold; }}

/* ---------- Titelliste ---------- */
QTableView, QTableWidget {{
    background: #FFFFFF; alternate-background-color: {STRIPE};
    border: 1px solid #5B7DAE; gridline-color: #D6E2F2;
    selection-background-color: {SELECTION}; selection-color: #FFFFFF;
}}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    border: none; border-right: 1px solid #A9C0DE; border-bottom: 1px solid #6F8FBC;
    padding: 2px 5px; font-weight: normal; background: {GLASS_HEADER};
}}
QHeaderView::section:checked, QHeaderView::section:pressed {{ background: {GLASS_STRONG}; }}
QTableCornerButton::section {{ background: {GLASS_HEADER}; border: none; border-bottom: 1px solid #6F8FBC; }}

/* ---------- Glas-Rollbalken ---------- */
QScrollBar:vertical {{ background: #EAF1FA; width: 15px; margin: 0; border-left: 1px solid #C3D3E8; }}
QScrollBar:horizontal {{ background: #EAF1FA; height: 15px; margin: 0; border-top: 1px solid #C3D3E8; }}
QScrollBar::handle:vertical {{
    min-height: 28px; margin: 1px 2px; border-radius: 6px; border: 1px solid #2A5DA8; background: {GLASS_SCROLL_V};
}}
QScrollBar::handle:horizontal {{
    min-width: 28px; margin: 2px 1px; border-radius: 6px; border: 1px solid #2A5DA8; background: {GLASS_SCROLL_H};
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- Fortschritt ---------- */
QProgressBar {{
    border: 1px solid #5B7DAE; border-radius: 6px; text-align: center; background: #F2F6FC; min-height: 14px;
}}
QProgressBar::chunk {{ border-radius: 5px; background: {GLASS_STRONG}; }}

/* ---------- Menüs, Reiter, Teiler ---------- */
QMenuBar {{ background: transparent; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {SELECTION}; color: #FFFFFF; }}
QMenu {{ background: #FAFCFF; border: 1px solid #8FAAD0; padding: 4px 0; }}
QMenu::item {{ padding: 3px 22px; }}
QMenu::separator {{ height: 1px; background: #D3DFEF; margin: 4px 0; }}

QTabWidget::pane {{ border: 1px solid #8FAAD0; border-radius: 8px; top: -12px; padding-top: 14px;
                    background: rgba(255, 255, 255, 90); }}
QTabWidget::tab-bar {{ alignment: center; }}
QTabBar::tab {{
    border: 1px solid #4A78B8; padding: 3px 14px; margin: 0 -1px 0 0; min-height: 16px; background: {GLASS};
}}
QTabBar::tab:first {{ border-top-left-radius: 10px; border-bottom-left-radius: 10px; }}
QTabBar::tab:last {{ border-top-right-radius: 10px; border-bottom-right-radius: 10px; }}
QTabBar::tab:selected {{ border-color: #1F4E96; background: {GLASS_STRONG}; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:vertical {{ height: 7px; }}
QStatusBar {{ background: transparent; }}
"""


def _write_glyphs() -> dict[str, str]:
    """Häkchen und Pfeile als kleine PNGs – Stylesheets können Symbole nur als Bild einbinden."""
    folder = Path(tempfile.gettempdir()) / "musiclib-theme"
    folder.mkdir(exist_ok=True)

    def draw(name: str, w: int, h: int, paint) -> str:
        img = QImage(w * 4, h * 4, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(4, 4)
        paint(p)
        p.end()
        path = folder / f"{name}.png"
        img.save(str(path))
        return path.as_posix()

    def check(p: QPainter) -> None:
        pen = QPen(QColor("#FFFFFF"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(2.5, 7), QPointF(5.5, 10), QPointF(10.5, 3)]))

    def arrow(color: str, up: bool):
        def paint(p: QPainter) -> None:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            pts = [QPointF(0, 5), QPointF(8, 5), QPointF(4, 0)] if up else [QPointF(0, 0), QPointF(8, 0), QPointF(4, 5)]
            p.drawPolygon(QPolygonF(pts))
        return paint

    return {
        "check": draw("check", 13, 13, check),
        "up": draw("up", 8, 5, arrow(INK, True)),
        "down": draw("down", 8, 5, arrow(INK, False)),
        "down_white": draw("down-white", 8, 5, arrow("#FFFFFF", False)),
    }


def window_brush() -> QBrush:
    """Glatter iTunes-5-Verlauf, der sich über jedes Fenster spannt."""
    g = QLinearGradient(0, 0, 0, 1)
    g.setCoordinateMode(QGradient.ObjectMode)
    g.setColorAt(0.0, QColor(WINDOW_TOP))
    g.setColorAt(0.08, QColor("#D7E5F8"))
    g.setColorAt(1.0, QColor(WINDOW_BOTTOM))
    return QBrush(g)


def app_icon() -> QIcon:
    return QIcon(str(ICON_PATH)) if ICON_PATH.exists() else QIcon()


def labeled(button: QPushButton, text: str) -> QVBoxLayout:
    """Runder Knopf mit kleiner Beschriftung darunter (wie „Durchsuchen“/„Brennen“ bei iTunes)."""
    lay = QVBoxLayout()
    lay.setSpacing(1)
    lay.addWidget(button, 0, Qt.AlignHCenter)
    lbl = QLabel(text)
    lbl.setObjectName("transportLabel")
    lbl.setAlignment(Qt.AlignHCenter)
    lay.addWidget(lbl, 0, Qt.AlignHCenter)
    return lay


def apply(app: QApplication) -> None:
    """iTunes-5-Look für die ganze App setzen."""
    app.setStyle("Fusion")
    pal = QPalette()
    window = window_brush()
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        pal.setBrush(group, QPalette.Window, window)
        pal.setColor(group, QPalette.Base, QColor("#FFFFFF"))
        pal.setColor(group, QPalette.AlternateBase, QColor(STRIPE))
        pal.setColor(group, QPalette.Button, QColor("#C4DDF8"))
        pal.setColor(group, QPalette.Highlight, QColor(SELECT))
        pal.setColor(group, QPalette.HighlightedText, QColor("#FFFFFF"))
        pal.setColor(group, QPalette.ToolTipBase, QColor("#FFFFC7"))
        pal.setColor(group, QPalette.ToolTipText, QColor("#000000"))
        pal.setColor(group, QPalette.Link, QColor("#1F4FA8"))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.PlaceholderText):
            pal.setColor(group, role, QColor("#8C9AAE" if group == QPalette.Disabled else INK))
    pal.setColor(QPalette.PlaceholderText, QColor("#8A8A8A"))
    app.setPalette(pal)

    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSize(13 if sys.platform == "darwin" else 10)
    app.setFont(font)
    try:
        glyphs = _write_glyphs()
    except OSError:
        glyphs = {"check": "", "up": "", "down": "", "down_white": ""}
    sheet = STYLESHEET
    for key, path in glyphs.items():
        sheet = sheet.replace(f"url({{{key}}})", f'url("{path}")' if path else "none")
    app.setStyleSheet(sheet)
    app.setWindowIcon(app_icon())


class LcdDisplay(QFrame):
    """Die gläserne Statusanzeige aus iTunes: zwei Textzeilen und ein dünner Fortschrittsbalken."""

    def __init__(self, idle_title: str, idle_detail: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("lcd")
        self.setMinimumWidth(360)
        self.setFixedHeight(64)
        self._idle = (idle_title, idle_detail)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 5, 18, 7)
        lay.setSpacing(2)
        self.title = QLabel(idle_title)
        self.title.setObjectName("lcdTitle")
        self.detail = QLabel(idle_detail)
        self.detail.setObjectName("lcdDetail")
        for lbl in (self.title, self.detail):
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setTextFormat(Qt.PlainText)
            lbl.setMinimumWidth(1)  # lange Texte nicht das Fenster verbreitern lassen
        self.progress = QProgressBar()
        self.progress.setObjectName("lcdProgress")
        self.progress.setTextVisible(False)
        lay.addWidget(self.title)
        lay.addWidget(self.detail)
        lay.addWidget(self.progress)
        self.progress.setVisible(False)

    def show_progress(self, i: int, n: int, text: str) -> None:
        self.title.setText(text or self._idle[0])
        self.detail.setText(f"{i} von {n}")
        self.progress.setMaximum(max(n, 1))
        self.progress.setValue(i)
        self.progress.setVisible(True)

    def show_message(self, title: str, detail: str = "") -> None:
        self.title.setText(title)
        self.detail.setText(detail)
        self.progress.setVisible(False)

    def idle(self) -> None:
        self.show_message(*self._idle)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        # Glanzlicht auf der oberen Hälfte und leichter Innenschatten wie beim echten LCD
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        path = QPainterPath()
        path.addRoundedRect(r, 11, 11)
        p.setClipPath(path)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), r.height() * 0.42), QColor(255, 255, 255, 70))
        p.setPen(QColor(14, 30, 54, 50))
        p.drawLine(r.topLeft(), r.topRight())
        p.end()
