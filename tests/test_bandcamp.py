import json

from musiclib.bandcamp import (
    BandcampClient, parse_autocomplete, parse_date, parse_duration, parse_search, parse_track_page,
)

SEARCH_HTML = """
<ul class="result-items">
<li class="searchresult data-search">
  <div class="result-info">
    <div class="itemtype">TRACK</div>
    <div class="heading"><a href="https://someartist.bandcamp.com/track/deep-song?from=search&amp;search_item_id=1">Deep Song</a></div>
    <div class="subhead">from Deep EP by Some Artist</div>
    <div class="itemurl"><a href="https://someartist.bandcamp.com/track/deep-song?from=search&amp;search_item_id=1">https://someartist.bandcamp.com/track/deep-song</a></div>
  </div>
</li>
<li class="searchresult data-search">
  <div class="result-info">
    <div class="itemtype">ALBUM</div>
    <div class="itemurl"><a href="https://somelabel.bandcamp.com/album/x?from=search">x</a></div>
  </div>
</li>
</ul>"""


def track_page(publisher="Some Label", artist="Some Artist"):
    ld = {
        "@type": "MusicRecording", "name": "Deep Song (Extended Mix)",
        "byArtist": {"@type": "MusicGroup", "name": artist},
        "publisher": {"@type": "MusicGroup", "name": publisher},
        "inAlbum": {"@type": "MusicAlbum", "name": "Deep EP"},
        "datePublished": "13 Jul 2018 00:00:00 GMT", "duration": "P00H06M12S",
        "keywords": ["deep house", "electronic", "Berlin"], "image": "https://f4.bcbits.com/img/a1_10.jpg",
    }
    return f'<html><script type="application/ld+json">{json.dumps(ld)}</script></html>'


def test_parse_search_only_tracks_without_query():
    assert parse_search(SEARCH_HTML) == ["https://someartist.bandcamp.com/track/deep-song"]


def test_helpers():
    assert parse_duration("P00H06M12S") == 372000
    assert parse_duration("") is None
    assert parse_date("13 Jul 2018 00:00:00 GMT") == "2018-07-13"


def test_parse_track_page():
    t = parse_track_page(track_page(), "https://x.bandcamp.com/track/deep-song")
    assert (t.name, t.mix, t.artists, t.release, t.label) == ("Deep Song", "Extended Mix", ["Some Artist"], "Deep EP", "Some Label")
    assert (t.genre, t.release_date, t.length_ms, t.source) == ("Deep House", "2018-07-13", 372000, "Bandcamp")


def test_self_release_has_no_label():
    t = parse_track_page(track_page(publisher="Some Artist"), "u")
    assert t.label == ""


class Resp:
    def __init__(self, text="", status=200, data=None):
        self.text, self.status_code, self._data, self.headers = text, status, data, {}

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


AUTOCOMPLETE = {"auto": {"results": [
    {"type": "b", "name": "Some Artist", "item_url_root": "https://someartist.bandcamp.com"},
    {"type": "t", "name": "Deep Song", "band_name": "Some Artist", "album_name": "Deep EP",
     "item_url_path": "https://someartist.bandcamp.com/track/deep-song?from=search", "img": "https://img/1.jpg"},
]}}


class FakeSession:
    def __init__(self, autocomplete_status=200, track_status=200):
        self.autocomplete_status, self.track_status = autocomplete_status, track_status
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url))
        assert "Mozilla" in headers["User-Agent"]
        assert json["search_filter"] == "t"
        return Resp(status=self.autocomplete_status, data=AUTOCOMPLETE)

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url))
        if url == "https://bandcamp.com/search":
            assert params["item_type"] == "t"
            return Resp(SEARCH_HTML)
        return Resp(track_page(), status=self.track_status)


def test_parse_autocomplete():
    assert parse_autocomplete(AUTOCOMPLETE) == [{"url": "https://someartist.bandcamp.com/track/deep-song",
                                                 "name": "Deep Song", "artist": "Some Artist", "album": "Deep EP",
                                                 "image": "https://img/1.jpg"}]


def test_client_search_text_via_json_api():
    s = FakeSession()
    results = BandcampClient(session=s, backoff=0).search_text("some artist deep song")
    assert [(t.name, t.mix, t.label) for t in results] == [("Deep Song", "Extended Mix", "Some Label")]
    assert ("GET", "https://bandcamp.com/search") not in s.calls


def test_falls_back_to_search_page_when_api_blocked():
    s = FakeSession(autocomplete_status=403)
    results = BandcampClient(session=s, backoff=0).search_text("x")
    assert [t.name for t in results] == ["Deep Song"]
    assert ("GET", "https://bandcamp.com/search") in s.calls


def test_unreadable_track_page_uses_search_data():
    results = BandcampClient(session=FakeSession(track_status=403), backoff=0).search_text("x")
    assert [(t.name, t.artist, t.release) for t in results] == [("Deep Song", "Some Artist", "Deep EP")]
