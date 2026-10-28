"""Le garde-fou de conftest.py doit bloquer toute connexion sortante : aucun test n'atteint le vrai Venice."""
import socket

import pytest


def test_connexion_exterieure_refusee():
    with socket.socket() as s, pytest.raises(OSError, match="interdite"):
        s.connect(("93.184.216.34", 80))
