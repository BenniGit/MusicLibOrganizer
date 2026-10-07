from pathlib import Path

from musiclib.models import Candidate, LibraryItem, LocalTrack, MatchStatus, TrackMeta
from musiclib.releases import CONFLICT, choose_release, groups, harmonize


def meta(title, source="Beatport", release="Deep EP", release_id="1", tid=None, artist="Artist"):
    return TrackMeta(id=tid or f"{source}-{release_id}-{title}", name=title, mix="Original Mix", artists=[artist],
                     remixers=[], release=release, label="Label", catalog_number="", genre="Tech House",
                     sub_genre="", bpm=125, key_name="", key_camelot="", isrc="", release_date="2024-01-01",
                     length_ms=0, image_url="", source=source, release_id=release_id, enriched=True)


def item(title, selected=None, status=MatchStatus.MATCHED, album="Deep EP", folder="Main", candidates=()):
    local = LocalTrack(Path(f"/lib/{folder}/{title}.mp3"), artist="Artist", title=title, album=album)
    return LibraryItem(local, status=status if selected else MatchStatus.NOT_FOUND, selected=selected,
                       score=0.95 if selected else 0.0, candidates=list(candidates))


class FakeSource:
    def __init__(self, name, tracks):
        self.name, self.tracks, self.calls = name, tracks, 0

    def release_tracks(self, release_id):
        self.calls += 1
        return [t for t in self.tracks if t.release_id == str(release_id)]


def test_track_from_other_source_is_moved_to_the_eps_beatport_release():
    a = item("Alpha", meta("Alpha"))
    b = item("Beta", meta("Beta"))
    c = item("Gamma", meta("Gamma", source="Discogs", release="Deep EP", release_id="99"))
    beatport = FakeSource("Beatport", [meta("Alpha"), meta("Beta"), meta("Gamma")])
    log = harmonize([a, b, c], [beatport])
    assert (c.selected.source, c.selected.release_id, c.status) == ("Beatport", "1", MatchStatus.MATCHED)
    assert "angeglichen" in c.message and log


def test_unmatched_ep_track_is_filled_from_the_release_tracklist():
    a = item("Alpha", meta("Alpha"))
    b = item("Beta", meta("Beta"))
    missing = item("Gamma")
    harmonize([a, b, missing], [FakeSource("Beatport", [meta("Alpha"), meta("Beta"), meta("Gamma")])])
    assert missing.selected is not None and missing.selected.name == "Gamma"


def test_conflict_is_flagged_when_track_is_not_on_the_chosen_release():
    a = item("Alpha", meta("Alpha"))
    b = item("Beta", meta("Beta"))
    c = item("Gamma", meta("Gamma", source="Bandcamp", release="Deep EP", release_id=""))
    harmonize([a, b, c], [FakeSource("Beatport", [meta("Alpha"), meta("Beta")])])
    assert c.status == MatchStatus.UNCERTAIN and c.message.startswith(CONFLICT)


def test_manual_choice_wins_and_is_never_changed():
    manual = item("Alpha", meta("Alpha", source="Discogs", release_id="7"), status=MatchStatus.MANUAL)
    b = item("Beta", meta("Beta"))
    discogs = FakeSource("Discogs", [meta("Alpha", "Discogs", release_id="7"), meta("Beta", "Discogs", release_id="7")])
    assert choose_release([manual, b]).source == "Discogs"
    harmonize([manual, b], [discogs, FakeSource("Beatport", [])])
    assert (b.selected.source, manual.selected.source, manual.status) == ("Discogs", "Discogs", MatchStatus.MANUAL)


def test_candidates_are_used_without_network():
    a = item("Alpha", meta("Alpha"))
    b = item("Beta", meta("Beta"))
    other = meta("Gamma", release="Deep EP (Remixes)", release_id="5")
    c = item("Gamma", other, album="Deep EP", candidates=[Candidate(other, 0.95), Candidate(meta("Gamma"), 0.9)])
    harmonize([a, b, c], [])
    assert c.selected.release_id == "1"


def test_unrelated_tracks_in_a_collection_folder_are_left_alone():
    # Sammelordner mit gleichem Album-Tag "Promo": Tracks gehören nicht zum selben Release
    a = item("Alpha", meta("Alpha"), album="Promo")
    b = item("Beta", meta("Beta"), album="Promo")
    c = item("Gamma", meta("Gamma", release="Other EP", release_id="2"), album="Promo")
    beatport = FakeSource("Beatport", [meta("Alpha"), meta("Beta")])
    assert harmonize([a, b, c], [beatport]) == []
    assert c.selected.release_id == "2" and c.status == MatchStatus.MATCHED


def test_done_tracks_anchor_the_group_and_unrelated_folders_dont_group():
    done = item("Alpha", meta("Alpha", source="Discogs", release_id="7"), status=MatchStatus.DONE)
    b = item("Beta", meta("Beta"))
    elsewhere = item("Beta", meta("Beta", release="X", release_id="3"), album="Deep EP", folder="Other")
    assert len(groups([done, b, elsewhere])) == 1  # nur done + b (gleicher Ordner + Album)
    harmonize([done, b], [FakeSource("Discogs", [meta("Alpha", "Discogs", release_id="7"),
                                                  meta("Beta", "Discogs", release_id="7")])])
    assert b.selected.source == "Discogs" and done.selected.source == "Discogs"
