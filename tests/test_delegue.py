"""venice-delegue : blocs de modification, garde de chemin, boucle avec tests. Faux pont local, aucun appel réseau."""
import importlib.machinery
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent


@pytest.fixture
def vd():
    loader = importlib.machinery.SourceFileLoader("venice_delegue", str(RACINE / "venice-delegue"))
    spec = importlib.util.spec_from_loader("venice_delegue", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture
def faux_pont(monkeypatch):
    """Pont factice : renvoie les réponses fournies dans l'ordre et garde les corps reçus."""
    etat = {"reponses": [], "corps": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            etat["corps"].append(corps)
            assert self.headers["Authorization"] == "Bearer cle-test"
            texte = etat["reponses"].pop(0)
            data = json.dumps({"choices": [{"message": {"role": "assistant", "content": texte}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("VENICE_PONT_URL", f"http://127.0.0.1:{srv.server_address[1]}/v1")
    monkeypatch.setenv("VENICE_PONT_CLE", "cle-test")
    yield etat
    srv.shutdown()


BLOC = """Voici la correction.

calc.py
```python
<<<<<<< SEARCH
def moyenne(v):
    return sum(v) / (len(v) + 1)
=======
def moyenne(v):
    return sum(v) / len(v)
>>>>>>> REPLACE
```
"""


def test_extraire_blocs(vd):
    assert vd.extraire_blocs(BLOC) == [("calc.py", "def moyenne(v):\n    return sum(v) / (len(v) + 1)\n",
                                        "def moyenne(v):\n    return sum(v) / len(v)\n")]


def test_extraire_ignore_la_reflexion_et_le_prefixe_fichier(vd):
    texte = "<think>calc.py\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE</think>\nFICHIER: a.py\n" \
            "<<<<<<< SEARCH\n=======\nnouveau\n>>>>>>> REPLACE\n"
    assert vd.extraire_blocs(texte) == [("a.py", "", "nouveau\n")]


def test_appliquer_remplace_cree_et_tolere_les_espaces_de_fin(vd, tmp_path):
    (tmp_path / "a.py").write_text("x = 1   \ny = 2\n")
    modifies, echecs = vd.appliquer(tmp_path, [("a.py", "x = 1\n", "x = 10\n"), ("neuf/b.py", "", "z = 3\n")])
    assert echecs == [] and modifies == ["a.py", "neuf/b.py"]
    assert (tmp_path / "a.py").read_text() == "x = 10\ny = 2\n"
    assert (tmp_path / "neuf" / "b.py").read_text() == "z = 3\n"


def test_appliquer_signale_ce_qui_manque_sans_ecrire(vd, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    modifies, echecs = vd.appliquer(tmp_path, [("a.py", "absent\n", "y\n"), ("b.py", "z\n", "w\n")])
    assert modifies == [] and len(echecs) == 2
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


def test_chemin_hors_du_dossier_refuse(vd, tmp_path):
    (tmp_path / "w").mkdir()
    _, echecs = vd.appliquer(tmp_path / "w", [("../evade.py", "", "x\n"), ("/tmp/abs.py", "", "x\n")])
    assert len(echecs) == 2 and not (tmp_path / "evade.py").exists()


def test_essai_n_ecrit_rien(vd, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    vd.appliquer(tmp_path, [("a.py", "x = 1\n", "x = 2\n")], essai=True)
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


def _projet(tmp_path):
    (tmp_path / "calc.py").write_text("def moyenne(v):\n    return sum(v) / (len(v) + 1)\n")
    (tmp_path / "test_calc.py").write_text("from calc import moyenne\n\n\ndef test_m():\n    assert moyenne([2, 4]) == 3\n")
    return f'"{sys.executable}" -m pytest -q -p no:cacheprovider'


def test_boucle_applique_puis_teste_sans_outil(vd, faux_pont, tmp_path):
    test = _projet(tmp_path)
    faux_pont["reponses"] = [BLOC]
    code = vd.main(["Corrige moyenne", "-f", "calc.py", "-f", "test_calc.py", "--test", test, "--racine", str(tmp_path)])
    assert code == 0
    assert "len(v)\n" in (tmp_path / "calc.py").read_text()
    corps = faux_pont["corps"][0]
    assert "tools" not in corps and corps["model"] == "deepseek-v4-1-flash-uncensored"
    assert "return sum(v) / (len(v) + 1)" in corps["messages"][1]["content"]


def test_boucle_renvoie_l_echec_des_tests_au_modele(vd, faux_pont, tmp_path):
    test = _projet(tmp_path)
    mauvais = BLOC.replace("return sum(v) / len(v)", "return sum(v)")
    faux_pont["reponses"] = [mauvais, BLOC.replace("return sum(v) / (len(v) + 1)", "return sum(v)")]
    code = vd.main(["Corrige", "-f", "calc.py", "--test", test, "--racine", str(tmp_path)])
    assert code == 0 and len(faux_pont["corps"]) == 2
    relance = faux_pont["corps"][1]["messages"][-1]["content"]
    assert "Les tests échouent" in relance and "return sum(v)" in relance


def test_abandon_apres_les_tours(vd, faux_pont, tmp_path):
    test = _projet(tmp_path)
    faux_pont["reponses"] = ["je ne sais pas", "toujours pas"]
    assert vd.main(["Corrige", "-f", "calc.py", "--test", test, "--tours", "2", "--racine", str(tmp_path)]) == 1


def test_format_json_relance_si_invalide(vd, faux_pont, tmp_path, capsys):
    faux_pont["reponses"] = ["pas du json", '```json\n{"ok": true}\n```']
    assert vd.main(["Donne ok", "--format", "json", "--racine", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_cle_absente(vd, monkeypatch, tmp_path):
    monkeypatch.delenv("VENICE_PONT_CLE", raising=False)
    assert vd.main(["x", "--racine", str(tmp_path)]) == 2
