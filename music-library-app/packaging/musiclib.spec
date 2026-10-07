# PyInstaller-Spezifikation für "MusicLib Organizer.app" – aufgerufen von build_macos.sh
import re
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "src/musiclib/__init__.py").read_text()).group(1)
NAME = "MusicLib Organizer"

a = Analysis(
    [str(ROOT / "packaging/launcher.py")],
    pathex=[str(ROOT / "src")],
    hiddenimports=["keyring.backends.macOS"],
    excludes=["pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False,
          icon=str(ROOT / "packaging/build/icon.icns"))
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)
app = BUNDLE(
    coll,
    name=f"{NAME}.app",
    icon=str(ROOT / "packaging/build/icon.icns"),
    bundle_identifier="de.bennigit.musiclib",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": NAME,
        "CFBundleShortVersionString": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        "NSHumanReadableCopyright": "Benjamin",
    },
)
