"""Erzeugt packaging/icon.png (1024 px) aus packaging/icon.svg.

Die macOS-Icon-Datei (.icns) baut packaging/build_macos.sh daraus mit iconutil.

    pip install cairosvg && python packaging/make_icon.py
"""

from pathlib import Path

import cairosvg

HERE = Path(__file__).parent

if __name__ == "__main__":
    cairosvg.svg2png(url=str(HERE / "icon.svg"), write_to=str(HERE / "icon.png"),
                     output_width=1024, output_height=1024)
    print("icon.png geschrieben")
