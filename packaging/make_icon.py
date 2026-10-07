"""Erzeugt musiclib/resources/icon.png (1024 px) aus packaging/icon.svg.

Das PNG nutzt die App als Fenster-/Dock-Icon; die macOS-Icon-Datei (.icns) baut
packaging/make_icns.sh daraus beim DMG-Build.

    pip install cairosvg && python packaging/make_icon.py
"""

from pathlib import Path

import cairosvg

HERE = Path(__file__).parent
OUT = HERE.parent / "musiclib" / "resources" / "icon.png"

if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(url=str(HERE / "icon.svg"), write_to=str(OUT), output_width=1024, output_height=1024)
    print(f"{OUT} geschrieben")
