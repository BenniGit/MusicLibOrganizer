"""Energie-Schätzung für House/Techno auf einer Skala 1–5 (experimentell).

Gemessen werden Eigenschaften, die bei elektronischer Tanzmusik mit "Energie" zusammenhängen:
rhythmische Dichte, Hi-Hat-/Percussion-Aktivität, Helligkeit, Bewegung im Spektrum, Bass-Anteil, BPM.
Die Lautstärke allein taugt kaum, weil fast alles gleich laut gemastert ist.

Zwei Verfahren:
* **ungelernt**: gewichtete Summe der (standardisierten) Merkmale; ★1–5 nach Quintilen der eigenen Bibliothek
* **kalibriert**: lineare Regression auf die eigenen Sterne (Ridge), ausgewertet per Kreuzvalidierung
"""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass

import numpy as np

from .converter import ffmpeg_path

SR = 22050
N_FFT = 2048
HOP = 512
SEGMENT_S = 20.0
SEGMENT_POS = (0.3, 0.5, 0.7)  # Ausschnitte aus dem Hauptteil (Intro/Outro auslassen)

FEATURES = ["hf_flux", "flux", "onset_rate", "centroid", "high_ratio", "low_ratio", "dynamics", "bpm"]
# Gewichte für das ungelernte Verfahren (Vorzeichen: mehr = energiegeladener)
DEFAULT_WEIGHTS = {"hf_flux": 1.0, "flux": 1.0, "onset_rate": 0.8, "centroid": 0.6, "high_ratio": 0.6,
                   "low_ratio": 0.2, "dynamics": -0.3, "bpm": 0.6}
FEATURE_LABELS = {
    "hf_flux": "Hi-Hat/Percussion-Aktivität", "flux": "Bewegung im Spektrum", "onset_rate": "Anschläge pro Sekunde",
    "centroid": "Helligkeit", "high_ratio": "Höhen-Anteil", "low_ratio": "Bass-Anteil",
    "dynamics": "Dynamik (Lautstärke-Schwankung)", "bpm": "BPM",
}


@dataclass
class Features:
    hf_flux: float
    flux: float
    onset_rate: float
    centroid: float
    high_ratio: float
    low_ratio: float
    dynamics: float
    bpm: float

    def vector(self) -> np.ndarray:
        return np.array([getattr(self, f) for f in FEATURES], dtype=float)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------- Audio
def decode(path: str, start: float, duration: float, sr: int = SR) -> np.ndarray:
    """Mono-Ausschnitt als float32 über ffmpeg."""
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{duration:.2f}",
           "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def _stft_mag(x: np.ndarray) -> np.ndarray:
    if len(x) < N_FFT:
        x = np.pad(x, (0, N_FFT - len(x)))
    n_frames = 1 + (len(x) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    frames = x[idx] * np.hanning(N_FFT)[None, :]
    return np.abs(np.fft.rfft(frames, axis=1))  # (Frames, Bins)


def _flux(logmag: np.ndarray) -> np.ndarray:
    d = np.diff(logmag, axis=0)
    return np.maximum(d, 0).sum(axis=1)


def _onset_rate(env: np.ndarray, seconds: float) -> float:
    if len(env) < 3 or seconds <= 0:
        return 0.0
    med = np.median(env)
    mad = np.median(np.abs(env - med)) + 1e-9
    peaks = (env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & (env[1:-1] > med + 2 * mad)
    return float(peaks.sum()) / seconds


def estimate_bpm(env: np.ndarray, lo: float = 100, hi: float = 160) -> float:
    """Tempo aus der Autokorrelation der Onset-Kurve (für Tracks ohne BPM-Angabe)."""
    if len(env) < 10:
        return 0.0
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    fps = SR / HOP
    lags = np.arange(len(ac))
    valid = (lags >= fps * 60 / hi) & (lags <= fps * 60 / lo)
    if not valid.any():
        return 0.0
    lag = lags[valid][np.argmax(ac[valid])]
    return float(60 * fps / lag)


def segment_features(x: np.ndarray) -> dict[str, float]:
    mag = _stft_mag(x)
    freqs = np.fft.rfftfreq(N_FFT, 1 / SR)
    power = mag ** 2
    total = power.sum(axis=1) + 1e-12
    logmag = np.log1p(10 * mag)
    hf = freqs >= 5000
    env = _flux(logmag)
    rms_db = 10 * np.log10(power.mean(axis=1) + 1e-12)
    seconds = len(x) / SR
    return {
        "hf_flux": float(_flux(logmag[:, hf]).mean() / hf.sum()),
        "flux": float(env.mean() / mag.shape[1]),
        "onset_rate": _onset_rate(env, seconds),
        "centroid": float(((power * freqs).sum(axis=1) / total).mean()),
        "high_ratio": float((power[:, hf].sum(axis=1) / total).mean()),
        "low_ratio": float((power[:, freqs < 150].sum(axis=1) / total).mean()),
        "dynamics": float(np.std(rms_db[rms_db > rms_db.max() - 40])) if len(rms_db) else 0.0,
        "bpm": estimate_bpm(env),
    }


def analyze(path: str, duration_s: float | None, known_bpm: float | None = None) -> Features:
    """Misst die Merkmale an mehreren Ausschnitten aus dem Hauptteil des Tracks."""
    if duration_s and duration_s > SEGMENT_S * 2:
        starts = [max(0.0, duration_s * p - SEGMENT_S / 2) for p in SEGMENT_POS]
    else:
        starts = [0.0]
    segs = [segment_features(x) for x in (decode(path, s, SEGMENT_S) for s in starts) if len(x) > SR]
    if not segs:
        raise ValueError("kein Audio dekodiert")
    feats = {k: float(np.mean([s[k] for s in segs])) for k in FEATURES}
    if known_bpm:
        feats["bpm"] = float(known_bpm)
    return Features(**feats)


# ---------------------------------------------------------------------------- Bewertung
def standardize(X: np.ndarray, mean: np.ndarray | None = None, std: np.ndarray | None = None):
    mean = X.mean(axis=0) if mean is None else mean
    std = X.std(axis=0) if std is None else std
    std = np.where(std < 1e-12, 1.0, std)
    return (X - mean) / std, mean, std


def unsupervised_scores(X: np.ndarray, weights: dict[str, float] = DEFAULT_WEIGHTS) -> np.ndarray:
    Z, _, _ = standardize(X)
    w = np.array([weights.get(f, 0.0) for f in FEATURES])
    return Z @ w


def to_stars_by_quantile(scores: np.ndarray, reference: np.ndarray | None = None) -> np.ndarray:
    """Ruhigste 20 % = ★1 … energiegeladenste 20 % = ★5 (relativ zur Bibliothek)."""
    ref = scores if reference is None else reference
    edges = np.quantile(ref, [0.2, 0.4, 0.6, 0.8])
    return 1 + np.searchsorted(edges, scores, side="right")


def ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float = 1.0):
    Z, mean, std = standardize(X)
    A = np.c_[np.ones(len(Z)), Z]
    reg = alpha * np.eye(A.shape[1])
    reg[0, 0] = 0  # Achsenabschnitt nicht bestrafen
    coef = np.linalg.solve(A.T @ A + reg, A.T @ y)
    return coef, mean, std


def ridge_predict(model, X: np.ndarray) -> np.ndarray:
    coef, mean, std = model
    Z, _, _ = standardize(X, mean, std)
    return np.c_[np.ones(len(Z)), Z] @ coef


def cross_val_predict(X: np.ndarray, y: np.ndarray, folds: int = 5, alpha: float = 1.0, seed: int = 0) -> np.ndarray:
    """Vorhersage für jeden Track von einem Modell, das diesen Track nicht gesehen hat."""
    n = len(y)
    folds = max(2, min(folds, n))
    order = np.random.default_rng(seed).permutation(n)
    pred = np.zeros(n)
    for k in range(folds):
        test = order[k::folds]
        train = np.setdiff1d(order, test)
        pred[test] = ridge_predict(ridge_fit(X[train], y[train], alpha), X[test])
    return pred


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    def ranks(v):
        order = np.argsort(v, kind="mergesort")
        r = np.empty(len(v))
        r[order] = np.arange(len(v))
        # Gleichstände mitteln
        for val in np.unique(v):
            m = v == val
            r[m] = r[m].mean()
        return r
    if len(a) < 3:
        return float("nan")
    ra, rb = ranks(np.asarray(a, float)), ranks(np.asarray(b, float))
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


@dataclass
class Evaluation:
    name: str
    exact: float
    within_one: float
    mae: float
    spearman: float


def evaluate(name: str, stars: np.ndarray, pred: np.ndarray) -> Evaluation:
    """Trefferquoten auf gerundeten Sternen; die Rangkorrelation auf den ungerundeten Schätzungen,
    damit feine Unterschiede (3,1 vs. 3,4) zählen."""
    raw = np.asarray(pred, float)
    rounded = np.clip(np.rint(raw), 1, 5)
    return Evaluation(name, float((rounded == stars).mean()), float((np.abs(rounded - stars) <= 1).mean()),
                      float(np.abs(rounded - stars).mean()), spearman(raw, stars))


def cross_val_predict_tuned(X: np.ndarray, y: np.ndarray, alphas=(0.1, 1, 10, 100, 1000, 10000),
                            folds: int = 5, seed: int = 0) -> np.ndarray:
    """Wie cross_val_predict, wählt die Regularisierung aber in jedem Durchgang nur auf den Trainingsdaten
    (verschachtelte Kreuzvalidierung) – nötig bei vielen Merkmalen wie dem 1280er KI-Fingerabdruck."""
    n = len(y)
    folds = max(2, min(folds, n))
    order = np.random.default_rng(seed).permutation(n)
    pred = np.zeros(n)
    for k in range(folds):
        test = order[k::folds]
        train = np.setdiff1d(order, test)
        best = min(alphas, key=lambda a: np.abs(cross_val_predict(X[train], y[train], 3, a, seed + 1) - y[train]).mean())
        pred[test] = ridge_predict(ridge_fit(X[train], y[train], best), X[test])
    return pred
