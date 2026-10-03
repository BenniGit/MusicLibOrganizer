import json
from pathlib import Path

import pytest

from musiclib.bandcamp import BandcampClient, parse_album_page
from musiclib.models import LibraryItem, LocalTrack, TrackMeta
from musiclib.urlimport import UrlImportError, assign_release, detect, load_url, looks_like_url


@pytest.mark.parametrize("url,expected", [
    ("https://www.beatport.com/track/losing-it/10766349", ("Beatport", "track", "10766349")),
    ("https://www.beatport.com/de/release/formula-ep/3355093?x=1", ("Beatport", "release", "3355093")),
    ("https://www.discogs.com/release/12266286-Fisher-Losing-It", ("Discogs", "release", "12266286")),
    ("https://www.discogs.com/de/master/1427366-Fisher-Losing-It", ("Discogs", "master", "1427366")),
    ("https://someartist.bandcamp.com/track/deep-song", ("Bandcamp", "track", "https://someartist.bandcamp.com/track/deep-song")),
    ("https://music.customdomain.com/album/deep-ep", ("Bandcamp", "album", "https://music.customdomain.com/album/deep-ep")),
])
def test_detect(url, expected):
    assert detect(url) == expected


def test_detect_unknown():
    with pytest.raises(UrlImportError):
        detect("https://example.com/foo")
    assert looks_like_url(" https://x.y/z ") and not looks_like_url("Fisher Losing It")


def test_load_url_requires_client():
    with pytest.raises(UrlImportError, match="Beatport-Zugangsdaten"):
        load_url("https://www.beatport.com/track/x/1", {})


class FakeBeatport:
    def track(self, ident):
        return TrackMeta(id=ident, name="T", mix="", artists=["A"])

    def release_tracks(self, ident):
        return [TrackMeta(id=i, name=f"T{i}", mix="", artists=["A"]) for i in (1, 2)]


def test_load_url_dispatch():
    assert [t.id for t in load_url("https://www.beatport.com/track/x/7", {"Beatport": FakeBeatport()})] == ["7"]
    assert len(load_url("https://www.beatport.com/release/x/7", {"Beatport": FakeBeatport()})) == 2


ALBUM_LD = {
    "@type": "MusicAlbum", "name": "Deep EP", "byArtist": {"name": "Some Artist"},
    "publisher": {"name": "Some Label"}, "datePublished": "01 Mar 2022 00:00:00 GMT",
    "keywords": ["techno", "electronic"], "numTracks": 2, "image": "https://img/a.jpg",
    "track": {"@type": "ItemList", "itemListElement": [
        {"position": 1, "item": {"@id": "https://x.bandcamp.com/track/one", "name": "One (Original Mix)", "duration": "P00H06M00S"}},
        {"position": 2, "item": {"@id": "https://x.bandcamp.com/track/two", "name": "Two", "byArtist": {"name": "Guest"}}},
    ]},
}


def test_parse_album_page():
    tracks = parse_album_page(f'<script type="application/ld+json">{json.dumps(ALBUM_LD)}</script>', "u")
    assert [(t.name, t.mix, t.artist, t.track_number, t.track_total) for t in tracks] == [
        ("One", "Original Mix", "Some Artist", 1, 2), ("Two", "", "Guest", 2, 2)]
    assert tracks[0].label == "Some Label" and tracks[0].album_artist == "Some Artist"
    assert tracks[0].release_date == "2022-03-01" and tracks[0].genre == "Techno"


def test_bandcamp_from_url_album():
    class Resp:
        status_code, headers = 200, {}
        text = f'<script type="application/ld+json">{json.dumps(ALBUM_LD)}</script>'

    class S:
        def get(self, url, **kw):
            return Resp()

    assert len(BandcampClient(session=S(), backoff=0).from_url("https://x.bandcamp.com/album/deep-ep?from=x")) == 2


def _item(name, **old):
    artist, title = name.split(" - ") if " - " in name else ("", name)
    return LibraryItem(LocalTrack(Path(name + ".mp3"), artist=artist, title=title, old=old))


def test_assign_release_by_title_and_track_number():
    tracks = [TrackMeta(id=i, name=n, mix="", artists=["A"], track_number=i, track_total=3)
              for i, n in ((1, "Formula"), (2, "Doppler"), (3, "RPM"))]
    items = [_item("A - Doppler"), _item("A - Formula"), _item("03 track")]
    result = {it.local.path.name: t.name for it, t, _ in assign_release(items, tracks)}
    assert result == {"A - Doppler.mp3": "Doppler", "A - Formula.mp3": "Formula", "03 track.mp3": "RPM"}


def test_assign_release_never_uses_a_track_twice():
    tracks = [TrackMeta(id=1, name="Song", mix="", artists=["A"])]
    result = assign_release([_item("A - Song"), _item("A - Song")], tracks)
    assert len(result) == 1
