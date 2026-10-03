import os

import pytest

from musiclib.beatport import BeatportClient
from musiclib.models import TrackMeta

API_TRACK = {
    "id": 1, "name": "One More Time", "mix_name": "12 Mix", "artists": [{"name": "Daft Punk"}],
    "remixers": [], "bpm": 123, "isrc": "GBDUW0000051", "catalog_number": "X",
    "key": {"name": "D Major", "camelot_number": 10, "camelot_letter": "B"},
    "genre": {"name": "House"}, "sub_genre": None, "length_ms": 480040, "new_release_date": "2000-12-08",
    "release": {"name": "One More Time", "label": {"name": "Daft Life"},
                "image": {"dynamic_uri": "https://img/{w}x{h}.jpg"}},
}


def test_from_api():
    t = TrackMeta.from_api(API_TRACK)
    assert t.display == "Daft Punk - One More Time (12 Mix)"
    assert (t.key_camelot, t.genre, t.label, t.sub_genre) == ("10B", "House", "Daft Life", "")
    assert t.image_url == "https://img/{w}x{h}.jpg"


class Resp:
    def __init__(self, status=200, data=None, headers=None, text=""):
        self.status_code, self._data, self.headers, self.text = status, data, headers or {}, text
        self.content = b"img"

    def json(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kw):
        self.calls.append(("POST", url))
        if url.endswith("/auth/login/"):
            return Resp(data={"username": "u"})
        if url.endswith("/auth/o/token/"):
            return Resp(data={"access_token": "tok", "refresh_token": "r", "expires_in": 36000})
        raise AssertionError(url)

    def get(self, url, **kw):
        self.calls.append(("GET", url))
        if url.endswith("/auth/o/authorize/"):
            assert kw["params"]["redirect_uri"].endswith("/auth/o/post-message/")
            return Resp(302, headers={"Location": "https://x/?code=abc"})
        if url.endswith("/catalog/search/"):
            assert kw["headers"]["Authorization"] == "Bearer tok"
            return Resp(data={"tracks": [API_TRACK]})
        if url.endswith("/catalog/tracks/"):
            return Resp(data={"results": [API_TRACK]})
        raise AssertionError(url)


def test_login_and_search_with_token_cache(tmp_path):
    cache = tmp_path / "tok.json"
    s = FakeSession()
    c = BeatportClient("u", "p", client_id="cid", token_cache=cache, session=s)
    assert c.search_tracks("daft punk")[0].name == "One More Time"
    assert c.tracks_by_isrc("GBDUW0000051")[0].id == 1
    assert cache.exists()
    assert [m for m, _ in s.calls].count("POST") == 2  # Login + Token nur einmal

    # Zweiter Client nutzt das gecachte Token ohne erneuten Login
    s2 = FakeSession()
    c2 = BeatportClient("u", "p", client_id="cid", token_cache=cache, session=s2)
    c2.search_tracks("x")
    assert not any(m == "POST" for m, _ in s2.calls)


def test_unwritable_token_cache_does_not_break_login(tmp_path):
    blocker = tmp_path / ".cache"
    blocker.write_text("ich bin eine Datei, kein Ordner")
    c = BeatportClient("u", "p", client_id="cid", token_cache=blocker / "musiclib" / "tok.json", session=FakeSession())
    assert c.search_tracks("x")[0].id == 1


@pytest.mark.live
@pytest.mark.skipif(not (os.environ.get("BEATPORT_USERNAME") and os.environ.get("BEATPORT_PASSWORD")),
                    reason="BEATPORT_USERNAME/BEATPORT_PASSWORD nicht gesetzt")
def test_live_login_and_search(tmp_path):
    c = BeatportClient(token_cache=tmp_path / "tok.json")
    results = c.search_tracks("Daft Punk One More Time")
    assert any("One More Time" in t.name for t in results)
