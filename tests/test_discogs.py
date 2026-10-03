import os
from pathlib import Path

import pytest

from musiclib.discogs import DiscogsClient, clean_label, clean_name, parse_duration, tracks_from_release
from musiclib.matcher import match_item
from musiclib.models import LibraryItem, LocalTrack, MatchStatus

RELEASE = {
    "id": 12266286, "title": "Losing It", "released": "2018-07-13", "uri": "https://www.discogs.com/release/12266286",
    "artists": [{"name": "Fisher (16)", "anv": ""}],
    "labels": [{"name": "Catch & Release", "catno": "CR001B"}],
    "genres": ["Electronic"], "styles": ["Tech House", "House"],
    "images": [{"uri": "https://i.discogs.com/cover.jpg"}],
    "tracklist": [
        {"position": "", "type_": "heading", "title": "Digital"},
        {"position": "1", "type_": "track", "title": "Losing It (Original)", "duration": "6:40"},
        {"position": "2", "type_": "track", "title": "Losing It (Someone Remix)", "duration": "",
         "extraartists": [{"name": "Someone (3)", "role": "Remix"}]},
    ],
}


def test_helpers():
    assert clean_name("Fisher (16)") == "Fisher"
    assert clean_name("Artist*") == "Artist"
    assert clean_label("Not On Label (Fisher Self-released)") == ""
    assert clean_label("Catch & Release") == "Catch & Release"
    assert parse_duration("6:40") == 400000
    assert parse_duration("1:02:03") == 3723000
    assert parse_duration("") is None


def test_tracks_from_release():
    tracks = tracks_from_release(RELEASE)
    assert len(tracks) == 2
    t = tracks[0]
    assert (t.name, t.mix, t.artists, t.label, t.catalog_number) == ("Losing It", "Original", ["Fisher"], "Catch & Release", "CR001B")
    assert (t.genre, t.sub_genre, t.release_date, t.length_ms, t.source) == ("Tech House", "House", "2018-07-13", 400000, "Discogs")
    assert tracks[1].remixers == ["Someone"]


def test_self_released_has_no_label():
    rel = dict(RELEASE, labels=[{"name": "Not On Label (Fisher Self-released)", "catno": "none"}])
    t = tracks_from_release(rel)[0]
    assert t.label == "" and t.catalog_number == ""


class Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.headers, self.text = data, status, {}, ""

    def json(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.urls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        assert headers["Authorization"] == "Discogs token=tok"
        if url.endswith("/database/search"):
            return Resp({"results": [{"id": 12266286, "format": ["File"]}]})
        if url.endswith("/releases/12266286"):
            return Resp(RELEASE)
        raise AssertionError(url)


def test_client_search_and_match():
    client = DiscogsClient(token="tok", session=FakeSession())
    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="Fisher", title="Losing It"))
    match_item(item, client)
    assert item.status == MatchStatus.MATCHED
    assert item.selected.mix == "Original" and item.selected.source == "Discogs"


def test_missing_token(monkeypatch):
    monkeypatch.delenv("DISCOGS_TOKEN", raising=False)
    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="B"))
    match_item(item, DiscogsClient(token="", session=FakeSession()))
    assert item.status == MatchStatus.ERROR and "Token" in item.message


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("DISCOGS_TOKEN"), reason="DISCOGS_TOKEN nicht gesetzt")
def test_live_discogs():
    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="Fisher", title="Losing It"))
    match_item(item, DiscogsClient())
    assert item.selected and item.selected.name == "Losing It" and item.selected.genre == "Tech House"
