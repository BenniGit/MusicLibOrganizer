import json
import os
import time
from pathlib import Path

from musiclib.manual import as_unofficial
from musiclib.models import LocalTrack, TrackMeta
from musiclib.soundcloud import SoundCloudClient, parse_page, split_artist_title
from musiclib.urlimport import detect, load_url

SOUND = {
    "id": 123, "title": "Fisher - Losing It (Someone Bootleg)", "genre": "Tech House",
    "created_at": "2023-05-02T10:00:00Z", "release_date": None, "duration": 301000,
    "permalink_url": "https://soundcloud.com/someone/losing-it-bootleg",
    "artwork_url": "https://i1.sndcdn.com/artworks-abc-large.jpg",
    "user": {"username": "Someone", "avatar_url": "https://i1.sndcdn.com/avatars-x-large.jpg"},
    "label_name": None, "publisher_metadata": {"id": 123},
}


def page(*entries):
    return f"<html><script>window.__sc_hydration = {json.dumps(list(entries))};</script></html>"


def test_split_artist_title():
    assert split_artist_title("Fisher - Losing It (Edit)", "uploader") == ("Fisher", "Losing It (Edit)")
    assert split_artist_title("Losing It (Edit)", "uploader") == ("uploader", "Losing It (Edit)")


def test_parse_sound():
    [t] = parse_page(page({"hydratable": "sound", "data": SOUND}), "u", default_label="Bootleg")
    assert (t.artist, t.name, t.mix, t.genre) == ("Fisher", "Losing It", "Someone Bootleg", "Tech House")
    assert (t.release, t.album_artist, t.track_number, t.track_total) == ("Losing It (Someone Bootleg)", "Fisher", 1, 1)
    assert (t.label, t.release_date, t.length_ms, t.source) == ("Bootleg", "2023-05-02", 301000, "SoundCloud")
    assert t.image_url == "https://i1.sndcdn.com/artworks-abc-t500x500.jpg"


def test_parse_sound_with_publisher_metadata():
    sound = dict(SOUND, title="Losing It (Extended)", label_name="Catch & Release",
                 publisher_metadata={"artist": "FISHER", "album_title": "Losing It", "isrc": "CA5KR1821203"})
    [t] = parse_page(page({"hydratable": "sound", "data": sound}), "u", default_label="Bootleg")
    assert (t.artist, t.release, t.label, t.isrc) == ("FISHER", "Losing It", "Catch & Release", "CA5KR1821203")


def test_parse_set():
    data = {"title": "Edits Vol. 1", "user": {"username": "Someone"}, "track_count": 3,
            "tracks": [SOUND, {"id": 2}, dict(SOUND, id=3, title="A - B")]}
    tracks = parse_page(page({"hydratable": "playlist", "data": data}), "u")
    assert [(t.name, t.release, t.track_number, t.track_total, t.album_artist) for t in tracks] == [
        ("Losing It", "Edits Vol. 1", 1, 3, "Someone"), ("B", "Edits Vol. 1", 2, 3, "Someone")]


def test_open_graph_fallback():
    html = '<meta property="og:title" content="Artist - Song (VIP)"><meta property="og:image" content="https://i/x.jpg">'
    [t] = parse_page(html, "u", default_label="Bootleg")
    assert (t.artist, t.name, t.mix, t.label, t.image_url) == ("Artist", "Song", "VIP", "Bootleg", "https://i/x.jpg")


def test_detect_and_load():
    assert detect("https://soundcloud.com/someone/losing-it-bootleg?si=x") == (
        "SoundCloud", "track", "https://soundcloud.com/someone/losing-it-bootleg?si=x")
    assert detect("https://soundcloud.com/someone/sets/edits")[1] == "set"

    class Resp:
        status_code, headers, url = 200, {}, "https://soundcloud.com/someone/losing-it-bootleg"
        text = page({"hydratable": "sound", "data": SOUND})

    class S:
        def get(self, url, **kw):
            assert "?" not in url
            return Resp()

    tracks = load_url("https://soundcloud.com/someone/losing-it-bootleg?si=x",
                      {"SoundCloud": SoundCloudClient(session=S(), default_label="Bootleg", backoff=0)})
    assert tracks[0].mix == "Someone Bootleg"


def test_as_unofficial_fills_required_fields(tmp_path):
    f = tmp_path / "Fisher - Losing It (Someone Bootleg).mp3"
    f.write_bytes(b"x")
    ts = time.mktime((2022, 3, 4, 12, 0, 0, 0, 0, -1))
    os.utime(f, (ts, ts))
    local = LocalTrack(f, artist="Fisher", title="Losing It", mix="Someone Bootleg", old={"genre": "House"})
    m = as_unofficial(local, None, "Bootleg")
    assert (m.release, m.album_artist, m.track_number, m.track_total) == ("Losing It (Someone Bootleg)", "Fisher", 1, 1)
    assert (m.label, m.release_date, m.genre, m.source) == ("Bootleg", "2022-03-04", "House", "Manuell")


def test_as_unofficial_keeps_existing_values(tmp_path):
    base = TrackMeta(id=1, name="Song", mix="", artists=["A"], release="EP", label="Real Label",
                     release_date="2020-01-01", track_number=3, track_total=4)
    m = as_unofficial(LocalTrack(tmp_path / "x.mp3"), base, "Bootleg")
    assert (m.release, m.label, m.release_date, m.track_number, m.track_total) == ("EP", "Real Label", "2020-01-01", 3, 4)
