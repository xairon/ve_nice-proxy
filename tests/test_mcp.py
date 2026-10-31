"""venice-mcp : protocole MCP (stdio) et outils deepseek_coder / deepseek_demander. Faux pont local, aucun réseau."""
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent


@pytest.fixture
def vm():
    loader = importlib.machinery.SourceFileLoader("venice_mcp", str(RACINE / "venice-mcp"))
    spec = importlib.util.spec_from_loader("venice_mcp", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture
def faux_pont(monkeypatch, tmp_path):
    etat = {"reponses": [], "corps": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            etat["corps"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            assert self.headers["Authorization"] == "Bearer cle-fichier"
            data = json.dumps({"choices": [{"message": {"content": etat["reponses"].pop(0)}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = tmp_path / "venice.env"
    env.write_text("VENICE_CLERK_CLIENT=x\nVENICE_PONT_CLE=cle-fichier\n")
    monkeypatch.delenv("VENICE_PONT_CLE", raising=False)
    monkeypatch.setenv("VENICE_PONT_ENV", str(env))
    monkeypatch.setenv("VENICE_PONT_URL", f"http://127.0.0.1:{srv.server_address[1]}/v1")
    yield etat
    srv.shutdown()


def rpc(vm, *messages):
    sortie = io.StringIO()
    vm.main(io.StringIO("".join(json.dumps(m) + "\n" for m in messages)), sortie)
    return [json.loads(ligne) for ligne in sortie.getvalue().splitlines()]


def test_poignee_de_main_et_liste(vm):
    reps = rpc(vm, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
               {"jsonrpc": "2.0", "method": "notifications/initialized"},
               {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
               {"jsonrpc": "2.0", "id": 3, "method": "inconnue"})
    assert [r["id"] for r in reps] == [1, 2, 3]  # la notification n'a pas de réponse
    assert reps[0]["result"]["protocolVersion"] == "2025-06-18" and "tools" in reps[0]["result"]["capabilities"]
    assert {o["name"] for o in reps[1]["result"]["tools"]} == {"deepseek_coder", "deepseek_demander"}
    assert reps[2]["error"]["code"] == -32601


def test_coder_applique_teste_et_ne_declare_aucun_outil(vm, faux_pont, tmp_path):
    (tmp_path / "calc.py").write_text("def double(x):\n    return x * 3\n")
    faux_pont["reponses"] = ["calc.py\n<<<<<<< SEARCH\n    return x * 3\n=======\n    return x * 2\n>>>>>>> REPLACE\n"]
    test = f"{sys.executable} -c \"import calc; assert calc.double(2) == 4\""
    [rep] = rpc(vm, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "deepseek_coder", "arguments": {
        "consigne": "corrige double", "fichiers": ["calc.py"], "test": test, "racine": str(tmp_path)}}})
    res = rep["result"]
    assert res["isError"] is False and "calc.py" in res["content"][0]["text"]
    assert (tmp_path / "calc.py").read_text().endswith("x * 2\n")
    corps = faux_pont["corps"][0]
    assert corps["model"] == "deepseek-v4-1-flash-uncensored" and "tools" not in corps
    assert "return x * 3" in corps["messages"][1]["content"]


def test_coder_en_echec_renvoie_la_sortie_du_test(vm, faux_pont, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    faux_pont["reponses"] = ["a.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n"]
    texte, erreur = vm.appeler("deepseek_coder", {"consigne": "c", "fichiers": ["a.py"], "tours": 1,
                                                  "test": f"{sys.executable} -c \"print('RATE'); raise SystemExit(1)\"",
                                                  "racine": str(tmp_path)})
    assert erreur and "RATE" in texte


def test_demander_ne_modifie_rien(vm, faux_pont, tmp_path):
    (tmp_path / "m.py").write_text("def f():\n    pass\n")
    faux_pont["reponses"] = ["<think>…</think>f ne fait rien."]
    texte, erreur = vm.appeler("deepseek_demander", {"question": "que fait f ?", "fichiers": ["m.py"],
                                                     "racine": str(tmp_path)})
    assert not erreur and texte == "f ne fait rien."
    assert (tmp_path / "m.py").read_text() == "def f():\n    pass\n"


def test_erreurs_lisibles_sans_cle_ni_chemin_hors_racine(vm, faux_pont, tmp_path, monkeypatch):
    texte, erreur = vm.appeler("deepseek_coder", {"consigne": "c", "fichiers": ["../hors.py"], "racine": str(tmp_path)})
    assert erreur and texte.startswith("Erreur")
    monkeypatch.delenv("VENICE_PONT_ENV")
    texte, erreur = vm.appeler("deepseek_demander", {"question": "q", "racine": str(tmp_path)})
    assert erreur and "VENICE_PONT_CLE manquante" in texte and "cle-fichier" not in texte
    assert vm.appeler("rm", {})[1]


def test_processus_reel_en_stdio():
    r = subprocess.run([sys.executable, str(RACINE / "venice-mcp")], capture_output=True, text=True, timeout=30,
                       input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
    assert r.returncode == 0 and json.loads(r.stdout)["result"]["tools"]


def test_harness_claude_code_branche_deepseek(tmp_path, monkeypatch, capsys):
    loader = importlib.machinery.SourceFileLoader("vs_mcp", str(RACINE / "venice-setup"))
    spec = importlib.util.spec_from_loader("vs_mcp", loader)
    vs = importlib.util.module_from_spec(spec)
    monkeypatch.setenv("VENICE_SETUP_HOME", str(tmp_path / "cfg"))
    loader.exec_module(vs)
    f = tmp_path / "cookie.txt"
    f.write_text("x" * 60)
    assert vs.main(["login", "--cookie-fichier", str(f), "--sans-verification"]) == 0
    capsys.readouterr()
    assert vs.main(["harness", "claude-code"]) == 0
    sortie = capsys.readouterr().out
    assert "claude mcp add" in sortie and "venice-mcp" in sortie and "CLAUDE.deepseek.md" in sortie
    assert (RACINE / "gabarits" / "claude-code" / "CLAUDE.deepseek.md").exists()
