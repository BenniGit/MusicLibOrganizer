from musiclib.check_sources import run


def test_missing_credentials_are_reported_without_network(monkeypatch):
    for name in ("DISCOGS_TOKEN", "BEATPORT_USERNAME", "BEATPORT_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    checks = run()
    assert [c.ok for c in checks] == [False, False]
    assert "DISCOGS_TOKEN" in checks[0].detail
    assert "BEATPORT_USERNAME, BEATPORT_PASSWORD" in checks[1].detail
