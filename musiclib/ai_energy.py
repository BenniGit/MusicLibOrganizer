"""KI-Merkmale mit Essentia (Discogs-EffNet): Klang-Fingerabdruck + fertige Einschätzungen.

Benötigt ``pip install essentia-tensorflow``. Die Modelle (~20 MB) werden beim ersten Aufruf von
essentia.upf.edu in den App-Datenordner geladen. Alles läuft lokal.
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import numpy as np

from .backup import data_dir
from .energy import SEGMENT_POS, decode

AI_SR = 16000
AI_SEGMENT_S = 30.0
BASE = "https://essentia.upf.edu/models"
EMBEDDING_MODEL = ("feature-extractors/discogs-effnet/discogs-effnet-bs64-1.pb", "PartitionedCall:1")
# Name -> (Modelldatei, Ausgang, Index der "positiven" Klasse oder None bei Regression)
HEADS = {
    "engagement": ("classification-heads/engagement/engagement_regression-discogs-effnet-1.pb", "model/Identity", None),
    "danceability": ("classification-heads/danceability/danceability-discogs-effnet-1.pb", "model/Softmax", 0),
    "aggressive": ("classification-heads/mood_aggressive/mood_aggressive-discogs-effnet-1.pb", "model/Softmax", 0),
    "party": ("classification-heads/mood_party/mood_party-discogs-effnet-1.pb", "model/Softmax", 0),
    "vocal": ("classification-heads/voice_instrumental/voice_instrumental-discogs-effnet-1.pb", "model/Softmax", 1),
}
HEAD_LABELS = {
    "engagement": "KI: Engagement (mitreißend)", "danceability": "KI: Tanzbarkeit",
    "aggressive": "KI: Aggressiv", "party": "KI: Party-Stimmung", "vocal": "KI: Vocal-Anteil",
}


class AIUnavailable(RuntimeError):
    pass


def models_dir() -> Path:
    return data_dir() / "models"


def ensure_models(progress=print) -> None:
    """Lädt fehlende Modelldateien herunter."""
    files = [EMBEDDING_MODEL[0]] + [h[0] for h in HEADS.values()]
    for rel in files:
        dst = models_dir() / Path(rel).name
        if dst.exists() and dst.stat().st_size > 0:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        progress(f"Lade KI-Modell {dst.name} …")
        tmp = dst.with_suffix(".part")
        try:
            urllib.request.urlretrieve(f"{BASE}/{rel}", tmp)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            raise AIUnavailable(f"Modell konnte nicht geladen werden ({e}). Ist essentia.upf.edu erreichbar?") from e
        tmp.replace(dst)


def check_available() -> None:
    # Nur prüfen, nicht importieren: TensorFlow im Hauptprozess würde parallele Arbeitsprozesse blockieren
    import importlib.util

    if importlib.util.find_spec("essentia") is None:
        raise AIUnavailable("Für --ki wird Essentia benötigt:  pip install essentia-tensorflow")


_MODELS: dict = {}


def _models():
    """Modelle einmal pro Prozess laden."""
    if not _MODELS:
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")  # TensorFlow-Meldungen unterdrücken
        import essentia

        essentia.log.infoActive = False
        essentia.log.warningActive = False
        import essentia.standard as es

        _MODELS["embed"] = es.TensorflowPredictEffnetDiscogs(
            graphFilename=str(models_dir() / Path(EMBEDDING_MODEL[0]).name), output=EMBEDDING_MODEL[1])
        for name, (rel, output, _) in HEADS.items():
            _MODELS[name] = es.TensorflowPredict2D(graphFilename=str(models_dir() / Path(rel).name), output=output)
    return _MODELS


def analyze(path: str, duration_s: float | None) -> dict:
    """-> {"embedding": [1280 Werte], "engagement": …, "danceability": …, …} (Mittel über die Ausschnitte)."""
    if duration_s and duration_s > AI_SEGMENT_S * 2:
        starts = [max(0.0, duration_s * p - AI_SEGMENT_S / 2) for p in SEGMENT_POS]
    else:
        starts = [0.0]
    audio = np.concatenate([decode(path, s, AI_SEGMENT_S, AI_SR) for s in starts]).astype(np.float32)
    if len(audio) < AI_SR * 3:
        raise ValueError("zu wenig Audio")
    m = _models()
    emb = np.asarray(m["embed"](audio))  # (Frames, 1280)
    out = {"embedding": [round(float(v), 5) for v in emb.mean(axis=0)]}
    for name, (_, _, idx) in HEADS.items():
        pred = np.asarray(m[name](emb))
        out[name] = float(pred.mean(axis=0)[0 if idx is None else idx])
    return out
