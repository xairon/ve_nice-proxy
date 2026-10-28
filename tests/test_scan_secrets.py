"""tools/scan_secrets.py : détecte secrets et données personnelles, n'affiche jamais une valeur en entier."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("scan_secrets", RACINE / "tools" / "scan_secrets.py")
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)

JWT = "eyJ" + "a" * 30 + "." + "b" * 20 + "." + "c" * 10


def _depot(tmp_path, contenu, nom="a.txt"):
    git = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)  # noqa: E731
    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (tmp_path / nom).write_text(contenu)
    git("add", ".")
    git("commit", "-qm", "c")
    return git


@pytest.mark.parametrize("contenu,nom", [
    (f"x {JWT}", "jeton JWT"),
    ("c = __client=" + "A" * 40, "cookie __client"),
    ("VENICE_CLERK_CLIENT=" + "B" * 50, "cookie Clerk dans un fichier d'environnement"),
    ("Authorization: Bearer " + "d" * 40, "jeton Bearer"),
    ("cle = sk-" + "e" * 30, "clé d'API"),
    ("/home/alice/projet", "chemin personnel"),
    ("hote 100.99.82.37", "adresse tailnet"),
    ("machine.tail1234.ts.net", "nom de réseau privé"),
    ("écrire à jean.dupont@gmail.com", "adresse électronique"),
])
def test_motifs_detectes(contenu, nom):
    assert nom in {n for n, _ in scan.trouver(contenu)}


@pytest.mark.parametrize("contenu", [
    "VENICE_CLERK_CLIENT=ancien", "Bearer cle", "/home/user/.local", "100.64.0.1", "noreply@example.invalid",
    "http://127.0.0.1:8700/v1", "contact@example.org",
])
def test_valeurs_d_exemple_acceptees(contenu):
    assert list(scan.trouver(contenu)) == []


def test_valeur_masquee():
    assert scan.masque(JWT).startswith("eyJa") and JWT not in scan.masque(JWT)


def test_arbre_propre_et_sale(tmp_path):
    _depot(tmp_path, "rien à signaler")
    assert scan.main(["--racine", str(tmp_path)]) == 0
    sale = tmp_path / "sale"
    sale.mkdir()
    _depot(sale, f"jeton {JWT}")
    assert scan.main(["--racine", str(sale)]) == 1


def test_historique_voit_un_secret_supprime_depuis(tmp_path, capsys):
    git = _depot(tmp_path, f"jeton {JWT}")
    (tmp_path / "a.txt").write_text("propre")
    git("commit", "-qam", "nettoyage")
    assert scan.main(["--racine", str(tmp_path)]) == 0
    assert scan.main(["--racine", str(tmp_path), "--historique"]) == 1
    assert JWT not in capsys.readouterr().err


def test_ce_depot_est_propre():
    assert scan.main(["--racine", str(RACINE), "--historique"]) == 0
