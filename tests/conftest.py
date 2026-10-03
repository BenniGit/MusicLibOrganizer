import shutil
import subprocess
from pathlib import Path

import pytest

from musiclib.models import BeatportTrack

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg nicht installiert")


def make_audio(path: Path, seconds: float = 1.0, **tags) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = []
    for k, v in tags.items():
        meta += ["-metadata", f"{k}={v}"]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
           "-i", f"sine=frequency=440:duration={seconds}", *meta]
    if path.suffix == ".mp3":
        cmd += ["-codec:a", "libmp3lame", "-b:a", "128k", "-id3v2_version", "4"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture
def bp_track():
    return BeatportTrack(
        id=123, name="One More Time", mix="Extended Mix", artists=["Daft Punk"], remixers=[],
        release="One More Time", label="Daft Life", catalog_number="CAT001", genre="House",
        sub_genre="", bpm=123, key_name="D Major", key_camelot="10B", isrc="GBDUW0000051",
        release_date="2000-12-08", length_ms=480040, image_url="",
    )
