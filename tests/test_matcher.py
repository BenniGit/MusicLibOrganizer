from pathlib import Path

from musiclib.matcher import build_query, match_item, normalize, score
from musiclib.models import BeatportTrack, LibraryItem, LocalTrack, MatchStatus


def bt(id, name, mix, artists, isrc="", length_ms=None):
    return BeatportTrack(id=id, name=name, mix=mix, artists=artists, isrc=isrc, length_ms=length_ms)


def test_normalize():
    assert normalize("Beyoncé & Jay-Z") == "beyonce and jay z"


def test_exact_match_scores_high():
    loc = LocalTrack(Path("x.mp3"), artist="Daft Punk", title="One More Time", mix="Extended Mix")
    assert score(loc, bt(1, "One More Time", "Extended Mix", ["Daft Punk"])) > 0.95


def test_missing_mix_prefers_original_mix():
    loc = LocalTrack(Path("x.mp3"), artist="A", title="Song")
    orig = score(loc, bt(1, "Song", "Original Mix", ["A"]))
    remix = score(loc, bt(2, "Song", "B Remix", ["A"]))
    assert orig > remix


def test_wrong_mix_is_penalised():
    loc = LocalTrack(Path("x.mp3"), artist="A", title="Song", mix="Extended Mix")
    assert score(loc, bt(1, "Song", "Extended Mix", ["A"])) > score(loc, bt(2, "Song", "Radio Edit", ["A"]))


def test_isrc_match_wins():
    loc = LocalTrack(Path("x.mp3"), artist="Unknown", title="track01", isrc="GB123")
    assert score(loc, bt(1, "Real Name", "Original Mix", ["Real Artist"], isrc="gb123")) >= 0.95


def test_duration_mismatch_lowers_score():
    loc = LocalTrack(Path("x.mp3"), artist="A", title="Song", duration_s=200)
    close = score(loc, bt(1, "Song", "Original Mix", ["A"], length_ms=201000))
    far = score(loc, bt(2, "Song", "Original Mix", ["A"], length_ms=400000))
    assert close > far


def test_rank_prefers_earliest_release_on_tie():
    from musiclib.matcher import rank
    loc = LocalTrack(Path("x.mp3"), artist="A", title="Song")
    comp = bt(1, "Song", "Original Mix", ["A"]); comp.release_date = "2021-05-01"
    orig = bt(2, "Song", "Original Mix", ["A"]); orig.release_date = "2018-03-01"
    assert [c.track.id for c in rank(loc, [comp, orig])] == [2, 1]


def test_build_query_strips_feat_and_original_mix():
    loc = LocalTrack(Path("x.mp3"), artist="A feat. B", title="Song", mix="Original Mix")
    assert build_query(loc) == "A Song"


class FakeClient:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def search_tracks(self, q, per_page=10):
        self.queries.append(q)
        return self.results

    def tracks_by_isrc(self, isrc):
        return []


def test_match_item_statuses():
    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="Song"))
    match_item(item, FakeClient([bt(2, "Other", "Original Mix", ["Z"]), bt(1, "Song", "Original Mix", ["A"])]))
    assert item.status == MatchStatus.MATCHED and item.selected.id == 1

    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="Song"))
    match_item(item, FakeClient([]))
    assert item.status == MatchStatus.NOT_FOUND and item.selected is None

    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="Song"))
    match_item(item, FakeClient([bt(3, "Totally Different", "Original Mix", ["Nobody"])]))
    assert item.status == MatchStatus.NOT_FOUND


def test_match_item_handles_errors():
    class Broken(FakeClient):
        def search_tracks(self, q, per_page=10):
            raise RuntimeError("boom")

    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="Song"))
    match_item(item, Broken([]))
    assert item.status == MatchStatus.ERROR and "boom" in item.message
