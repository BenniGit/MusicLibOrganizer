from pathlib import Path

from musiclib.matcher import build_query, canonical_mix, match_item, normalize, rank, score
from musiclib.models import TrackMeta, LibraryItem, LocalTrack, MatchStatus


def bt(id, name, mix, artists, isrc="", length_ms=None):
    return TrackMeta(id=id, name=name, mix=mix, artists=artists, isrc=isrc, length_ms=length_ms)


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
    loc = LocalTrack(Path("x.mp3"), artist="A", title="Song")
    comp = bt(1, "Song", "Original Mix", ["A"]); comp.release_date = "2021-05-01"
    orig = bt(2, "Song", "Original Mix", ["A"]); orig.release_date = "2018-03-01"
    assert [c.track.id for c in rank(loc, [comp, orig])] == [2, 1]


def test_build_query_strips_feat_and_original_mix():
    loc = LocalTrack(Path("x.mp3"), artist="A feat. B", title="Song", mix="Original Mix")
    assert build_query(loc) == "A Song"


class FakeSource:
    def __init__(self, results, name="Beatport"):
        self.results = results
        self.name = name
        self.calls = 0

    def search(self, local):
        self.calls += 1
        return self.results


def test_match_item_statuses():
    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="Song"))
    match_item(item, FakeSource([bt(2, "Other", "Original Mix", ["Z"]), bt(1, "Song", "Original Mix", ["A"])]))
    assert item.status == MatchStatus.MATCHED and item.selected.id == 1

    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="Song"))
    match_item(item, FakeSource([]))
    assert item.status == MatchStatus.NOT_FOUND and item.selected is None

    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="Song"))
    match_item(item, FakeSource([bt(3, "Totally Different", "Original Mix", ["Nobody"])]))
    assert item.status == MatchStatus.NOT_FOUND


def test_match_item_handles_errors():
    class Broken(FakeSource):
        def search(self, local):
            raise RuntimeError("boom")

    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="Song"))
    match_item(item, Broken([]))
    assert item.status == MatchStatus.ERROR and "boom" in item.message


def _other(id, name, mix, artists, source):
    t = bt(id, name, mix, artists)
    t.source = source
    return t


def test_beatport_match_skips_other_sources():
    beatport = FakeSource([bt(1, "Song", "Original Mix", ["A"])])
    discogs = FakeSource([_other(2, "Song", "", ["A"], "Discogs")], name="Discogs")
    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="Song"))
    match_item(item, [beatport, discogs])
    assert item.selected.source == "Beatport" and discogs.calls == 0


def test_fallback_to_discogs_when_beatport_has_nothing():
    beatport = FakeSource([bt(1, "Different", "Original Mix", ["Z"])])
    discogs = FakeSource([_other(2, "Song", "Original", ["A"], "Discogs")], name="Discogs")
    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="Song"))
    match_item(item, [beatport, discogs])
    assert item.status == MatchStatus.MATCHED and item.selected.source == "Discogs"


def test_failing_fallback_source_does_not_hide_results():
    class Broken(FakeSource):
        def search(self, local):
            raise RuntimeError("offline")

    beatport = FakeSource([bt(1, "Song", "Radio Edit", ["A"])])
    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="A", title="Song", mix="Extended Mix"))
    match_item(item, [beatport, Broken([], name="Bandcamp")])
    assert item.candidates and item.status == MatchStatus.UNCERTAIN and "offline" in item.message


def test_rank_prefers_sure_beatport_over_other_sources():
    loc = LocalTrack(Path("x.mp3"), artist="A", title="Song", mix="Extended Mix")
    bp = bt(1, "Song", "Extended", ["A"])          # ~ 0.9x
    dc = _other(2, "Song", "Extended Mix", ["A"], "Discogs")  # 1.0
    ranked = rank(loc, [dc, bp])
    assert ranked[0].track.source == "Beatport"


def test_unknown_local_mix_vs_remix_is_uncertain():
    item = LibraryItem(LocalTrack(Path("x.mp3"), artist="Bicep", title="Glue"))
    match_item(item, FakeSource([bt(1, "Glue", "Oao Edit", ["Bicep"])]))
    assert item.status == MatchStatus.UNCERTAIN


def test_canonical_mix():
    assert canonical_mix("") == canonical_mix("Original") == canonical_mix("Original Mix") == "original"
    assert canonical_mix("Extended Mix") == canonical_mix("Extended") == "extended"
