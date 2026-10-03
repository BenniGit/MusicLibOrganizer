"""Beatport-Zugangsdaten: Benutzername in den Einstellungen, Passwort im System-Schlüsselbund.

macOS: Schlüsselbund, Windows: Anmeldeinformationsverwaltung, Linux: Secret Service (falls vorhanden).
Umgebungsvariablen (BEATPORT_USERNAME / BEATPORT_PASSWORD) haben Vorrang.
"""
from __future__ import annotations

import os

SERVICE = "MusicLibOrganizer Beatport"


def _keyring():
    try:
        import keyring

        return keyring
    except Exception:
        return None


def keyring_available() -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        from keyring.backends import fail

        return not isinstance(kr.get_keyring(), fail.Keyring)
    except Exception:
        return False


def load_password(username: str) -> str:
    kr = _keyring()
    if not username or kr is None:
        return ""
    try:
        return kr.get_password(SERVICE, username) or ""
    except Exception:
        return ""


def save_password(username: str, password: str) -> bool:
    kr = _keyring()
    if not username or kr is None:
        return False
    try:
        if password:
            kr.set_password(SERVICE, username, password)
        else:
            try:
                kr.delete_password(SERVICE, username)
            except Exception:
                pass
        return True
    except Exception:
        return False


def initial_credentials(saved_username: str) -> tuple[str, str, str]:
    """-> (Benutzername, Passwort, Herkunft) – Umgebung vor Schlüsselbund."""
    env_user, env_pw = os.environ.get("BEATPORT_USERNAME", ""), os.environ.get("BEATPORT_PASSWORD", "")
    if env_user and env_pw:
        return env_user, env_pw, "Umgebung"
    pw = load_password(saved_username)
    return saved_username, pw, "Schlüsselbund" if pw else ""
