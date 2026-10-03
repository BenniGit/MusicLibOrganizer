import keyring
from keyring.backend import KeyringBackend

from musiclib import credentials


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


def test_password_roundtrip_and_env_priority(monkeypatch):
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    try:
        monkeypatch.delenv("BEATPORT_USERNAME", raising=False)
        monkeypatch.delenv("BEATPORT_PASSWORD", raising=False)
        assert credentials.keyring_available()
        assert credentials.save_password("bongoben", "geheim")
        assert credentials.initial_credentials("bongoben") == ("bongoben", "geheim", "Schlüsselbund")
        credentials.save_password("bongoben", "")  # löschen
        assert credentials.initial_credentials("bongoben") == ("bongoben", "", "")
        monkeypatch.setenv("BEATPORT_USERNAME", "env")
        monkeypatch.setenv("BEATPORT_PASSWORD", "pw")
        assert credentials.initial_credentials("bongoben") == ("env", "pw", "Umgebung")
    finally:
        keyring.set_keyring(previous)
