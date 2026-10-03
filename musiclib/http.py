"""HTTP-Hilfen: Wiederholen bei vorübergehenden Fehlern und lesbare Fehlermeldungen."""
from __future__ import annotations

import re
import time

import requests

RETRY_STATUS = {500, 502, 503, 504, 520, 521, 522, 524}
STATUS_TEXT = {
    401: "Zugang abgelehnt",
    403: "Zugriff verweigert (evtl. Bot-Schutz)",
    404: "nicht gefunden",
    429: "zu viele Anfragen",
    500: "Serverfehler",
    502: "Server vorübergehend nicht erreichbar",
    503: "Dienst vorübergehend nicht verfügbar",
    504: "Zeitüberschreitung beim Server",
}


def describe(status: int, text: str = "") -> str:
    """Kurze Meldung statt einer ganzen HTML-Fehlerseite."""
    msg = STATUS_TEXT.get(status, "unerwartete Antwort")
    body = (text or "").strip()
    if body and not body.lstrip().startswith("<"):
        msg += ": " + re.sub(r"\s+", " ", body)[:150]
    return f"{msg} (HTTP {status})"


def request(session: requests.Session, method: str, url: str, retries: int = 3, backoff: float = 1.0,
            **kwargs) -> requests.Response:
    """Wie session.request, wiederholt aber bei 5xx, 429 und Verbindungsfehlern (mit wachsender Pause)."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = getattr(session, method.lower())(url, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
        else:
            if r.status_code not in RETRY_STATUS and r.status_code != 429:
                return r
            if attempt == retries:
                return r
            if r.status_code == 429:
                try:
                    time.sleep(min(float(r.headers.get("Retry-After", 0)) or backoff * 2 ** attempt, 60))
                except ValueError:
                    time.sleep(backoff * 2 ** attempt)
                continue
        if attempt == retries:
            raise last_exc  # type: ignore[misc]
        time.sleep(backoff * 2 ** attempt)
    raise RuntimeError("unreachable")


class SourceDown(RuntimeError):
    pass


class CircuitBreaker:
    """Überspringt eine Quelle eine Weile, wenn sie mehrfach hintereinander ausfällt."""

    def __init__(self, name: str, threshold: int = 2, pause: float = 300):
        self.name, self.threshold, self.pause = name, threshold, pause
        self.failures = 0
        self.down_until = 0.0

    def check(self) -> None:
        if time.time() < self.down_until:
            mins = max(1, round((self.down_until - time.time()) / 60))
            raise SourceDown(f"vorübergehend nicht erreichbar – wird ca. {mins} Min. übersprungen")

    def success(self) -> None:
        self.failures = 0

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.down_until = time.time() + self.pause
            self.failures = 0
