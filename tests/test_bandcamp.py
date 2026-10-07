import html
import json

from musiclib.bandcamp import (
    BandcampClient, album_url_of, parse_autocomplete, parse_date, parse_duration, parse_search, parse_track_page,
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


# --- Aufbau echter Bandcamp-Seiten: Die Track-Seite eines Album-Tracks hat oft weder Datum noch Tracknummer
#     (track_num ist null), beides steht aber auf der Album-Seite.
ALBUM_URL = "https://somelabel.bandcamp.com/album/deep-ep"
TRACK_URL = "https://somelabel.bandcamp.com/track/second-song"


def real_track_page(tralbum=None, ld_extra=None, text=""):
    ld = {"@type": "MusicRecording", "@id": TRACK_URL, "name": "Second Song",
          "byArtist": {"@type": "MusicGroup", "name": "Some Artist"},
          "publisher": {"@type": "MusicGroup", "name": "Some Label"},
          "inAlbum": {"@id": ALBUM_URL, "@type": "MusicAlbum", "name": "Deep EP", "numTracks": 3,
                      "albumReleaseType": "AlbumRelease"},
          **(ld_extra or {})}
    tralbum = tralbum if tralbum is not None else {"album_url": "/album/deep-ep", "trackinfo": [{"track_num": None}]}
    attr = html.escape(json.dumps(tralbum), quote=True)
    return (f'<html><script type="application/ld+json">{json.dumps(ld)}</script>'
            f'<script data-tralbum="{attr}"></script>{text}</html>')


def real_album_page():
    ld = {"@type": "MusicAlbum", "@id": ALBUM_URL, "name": "Deep EP", "numTracks": 3,
          "datePublished": "16 Feb 2024 00:00:00 GMT",
          "byArtist": {"@type": "MusicGroup", "name": "Some Artist"},
          "publisher": {"@type": "MusicGroup", "name": "Some Label"},
          "track": {"itemListElement": [
              {"position": i, "item": {"@id": f"https://somelabel.bandcamp.com/track/{slug}", "name": name}}
              for i, (slug, name) in enumerate((("first-song", "First Song"), ("second-song", "Second Song"),
                                                 ("third-song", "Third Song")), 1)]}}
    return f'<html><script type="application/ld+json">{json.dumps(ld)}</script></html>'


class AlbumSession:
    def __init__(self):
        self.calls = []
        self.track_page = real_track_page()

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        return Resp(real_album_page() if url == ALBUM_URL else self.track_page)


def test_single_track_gets_number_and_date_from_album_page():
    s = AlbumSession()
    [t] = BandcampClient(session=s, backoff=0).from_url(TRACK_URL + "?from=search")
    assert (t.name, t.track_number, t.track_total, t.release_date) == ("Second Song", 2, 3, "2024-02-16")
    assert (t.release, t.label, t.album_artist) == ("Deep EP", "Some Label", "Some Artist")
    assert s.calls == [TRACK_URL, ALBUM_URL]


def test_album_page_wins_and_is_loaded_once():
    """Auch wenn die Track-Seite schon Daten hat, gelten die der Album-Seite – geladen nur einmal pro Album."""
    s = AlbumSession()
    s.track_page = real_track_page(tralbum={"album_release_date": "1 Jan 2020 00:00:00 GMT",
                                            "trackinfo": [{"track_num": 7}]})
    c = BandcampClient(session=s, backoff=0)
    [t] = c.from_url(TRACK_URL)
    [t2] = c.from_url(TRACK_URL)
    assert (t.track_number, t.release_date) == (2, "2024-02-16") == (t2.track_number, t2.release_date)
    assert s.calls.count(ALBUM_URL) == 1


def test_album_url_from_page_data_when_json_ld_has_no_id():
    page = real_track_page(ld_extra={"inAlbum": {"@type": "MusicAlbum", "name": "Deep EP"}})
    assert album_url_of(page, TRACK_URL) == ALBUM_URL


def test_track_page_data_used_without_extra_request():
    page = real_track_page(tralbum={"album_release_date": "16 Feb 2024 00:00:00 GMT", "trackinfo": [{"track_num": 2}]})
    t = parse_track_page(page, TRACK_URL)
    assert (t.track_number, t.track_total, t.release_date) == (2, 3, "2024-02-16")


def test_tracknum_from_json_ld_additional_property():
    page = real_track_page(ld_extra={"additionalProperty": [{"@type": "PropertyValue", "name": "tracknum", "value": 2}]})
    assert parse_track_page(page, TRACK_URL).track_number == 2


def test_release_date_from_visible_text():
    page = real_track_page(tralbum={}, text='<div class="tralbum-credits">released February 16, 2024</div>')
    assert parse_track_page(page, TRACK_URL).release_date == "2024-02-16"


def test_standalone_single_is_track_one_of_one():
    page = real_track_page(tralbum={}, ld_extra={"inAlbum": {"@type": "MusicAlbum", "name": "Second Song",
                                                             "albumReleaseType": "SingleRelease"}})
    t = parse_track_page(page, TRACK_URL)
    assert (t.track_number, t.track_total) == (1, 1)


def test_more_date_formats():
    assert parse_date("2024-02-16T00:00:00Z") == "2024-02-16"
    assert parse_date("February 16, 2024") == "2024-02-16"
    assert parse_date("16 Feb 2024 00:00:00 UTC") == "2024-02-16"
