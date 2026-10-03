"""Live-Tests gegen Bandcamp und SoundCloud – werden übersprungen, wenn die Seiten nicht erreichbar sind."""
import pytest
import requests

from musiclib.bandcamp import BandcampClient
from musiclib.soundcloud import SoundCloudClient


def reachable(url: str) -> bool:
    try:
        return requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}).status_code < 500
    except requests.RequestException:
        return False


@pytest.mark.live
def test_live_bandcamp_search():
    if not reachable("https://bandcamp.com/"):
        pytest.skip("bandcamp.com nicht erreichbar")
    results = BandcampClient().search_text("Bonobo Kerala")
    assert results and all(t.source == "Bandcamp" and t.url for t in results)


@pytest.mark.live
def test_live_soundcloud_url():
    if not reachable("https://soundcloud.com/"):
        pytest.skip("soundcloud.com nicht erreichbar")
    [t] = SoundCloudClient(default_label="Bootleg").from_url("https://soundcloud.com/forss/flickermood")
    assert t.name and t.artists and t.release_date[:4].isdigit()
