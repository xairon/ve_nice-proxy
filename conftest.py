"""Garde-fou : aucun test ne contacte le vrai Venice (un faux jeton envoyé là-bas ressemble à de l'abus)."""
import socket

import pytest

_connect = socket.socket.connect


@pytest.fixture(autouse=True)
def _aucune_connexion_sortante(monkeypatch):
    def connect(self, adresse):
        if isinstance(adresse, tuple) and adresse[0] not in ("127.0.0.1", "::1", "localhost"):
            raise OSError(f"test : connexion sortante interdite vers {adresse[0]}")
        return _connect(self, adresse)

    monkeypatch.setattr(socket.socket, "connect", connect)
