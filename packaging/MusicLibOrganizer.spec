# PyInstaller-Rezept:  pyinstaller --noconfirm packaging/MusicLibOrganizer.spec
# Ergebnis: dist/MusicLibOrganizer.app (macOS) bzw. dist/MusicLibOrganizer/ (Linux/Windows)
# App-Icon: packaging/build/icon.icns, erzeugt von packaging/make_icns.sh (macOS); fehlt es, bleibt das Standard-Icon.
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "musiclib" / "__init__.py").read_text()).group(1)

# Große Qt-Module, die die App nicht braucht, weglassen (spart ~200 MB)
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml",
    "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
    "PySide6.QtBluetooth", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "essentia", "tensorflow", "tkinter", "pytest",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "musiclib" / "resources"), "musiclib/resources")],  # Fenster-/Dock-Icon zur Laufzeit
    hiddenimports=["keyring.backends.macOS", "keyring.backends.Windows", "keyring.backends.SecretService",
                   "sqlcipher3", "pyrekordbox.db6"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MusicLibOrganizer", console=False,
          argv_emulation=False, target_arch=None)
coll = COLLECT(exe, a.binaries, a.datas, name="MusicLibOrganizer")

if sys.platform == "darwin":
    ICNS = ROOT / "packaging" / "build" / "icon.icns"
    app = BUNDLE(
        coll,
        name="MusicLibOrganizer.app",
        icon=str(ICNS) if ICNS.exists() else None,
        bundle_identifier="de.bennigit.musiclib-organizer",
        version=VERSION,
        info_plist={
            "CFBundleName": "MusicLibOrganizer",
            "CFBundleDisplayName": "MusicLibOrganizer",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
