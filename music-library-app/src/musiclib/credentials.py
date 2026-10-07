"""Zugangsdaten: zuerst Umgebungsvariable, sonst macOS-Schlüsselbund (Dienst "musiclib")."""

from __future__ import annotations

import os

SERVICE = "musiclib"
NAMES = ("DISCOGS_TOKEN", "BEATPORT_USERNAME", "BEATPORT_PASSWORD")


def _keyring():
    try:
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:  # kein Schlüsselbund verfügbar (z. B. Linux-Server)
        return None


def get(name: str) -> str | None:
    if value := os.environ.get(name):
        return value
    if kr := _keyring():
        try:
            return kr.get_password(SERVICE, name) or None
        except Exception:
            return None
    return None


def set(name: str, value: str) -> None:  # noqa: A001 - bewusst analog zu get
    kr = _keyring()
    if kr is None:
        raise RuntimeError("Kein Schlüsselbund verfügbar.")
    if value:
        kr.set_password(SERVICE, name, value)
    else:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass


def keychain_available() -> bool:
    return _keyring() is not None
