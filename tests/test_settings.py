import json

from musiclib.models import TrackMeta
from musiclib.organizer import validate_template
from musiclib.settings import TEMPLATE_PRESETS, AppSettings, effective_meta, missing_fields


def meta(**kw):
    base = dict(id=1, name="Song", mix="", artists=["A"], genre="House", label="", release_date="2020-01-01")
    base.update(kw)
    return TrackMeta(**base)


def test_presets_are_valid():
    for name, tpl in TEMPLATE_PRESETS.items():
        assert validate_template(tpl) is None, name


def test_label_fallback():
    s = AppSettings(label_fallback="Self-Released")
    assert effective_meta(meta(), s).label == "Self-Released"
    assert effective_meta(meta(label="Drumcode"), s).label == "Drumcode"
    assert missing_fields(meta(), s) == []
    assert missing_fields(meta(), AppSettings(label_fallback="")) == ["Label"]


def test_missing_fields():
    s = AppSettings(required_fields=["artist", "genre", "bpm", "cover"])
    assert missing_fields(meta(genre=""), s) == ["Genre", "BPM", "Cover"]
    assert missing_fields(None, s) == ["Artist", "Genre", "BPM", "Cover"]


def test_settings_roundtrip_ignores_unknown_keys():
    s = AppSettings(template="{artist}", use_bandcamp=False)
    data = json.loads(s.to_json())
    data["obsolete"] = 1
    s2 = AppSettings.from_json(json.dumps(data))
    assert s2 == s
    assert AppSettings.from_json("kaputt") == AppSettings()
