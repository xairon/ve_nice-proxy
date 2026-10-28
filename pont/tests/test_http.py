"""Client HTTP minimal du pont (bibliothèque standard seule, sans `requests`), essayé contre un vrai serveur local."""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import venice_pont as vp  # noqa: E402


class _H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _rep(self, code, corps=b"", type_="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        if self.path.startswith("/json"):
            self._rep(200, json.dumps({"q": self.path, "ua": self.headers.get("User-Agent")}).encode())
        elif self.path == "/redir":
            self._rep(302, b"", extra=[("Location", "/json")])
        elif self.path == "/404":
            self._rep(404, b'{"error":"absent"}')
        elif self.path == "/cookie":
            self._rep(200, b"{}", extra=[("Set-Cookie", "__client=neuf; Path=/; HttpOnly"), ("Set-Cookie", "autre=1; Path=/")])
        elif self.path == "/efface":
            self._rep(200, b"{}", extra=[("Set-Cookie", "autre=; Max-Age=0; Path=/")])
        elif self.path == "/qui":
            self._rep(200, json.dumps({"cookie": self.headers.get("Cookie")}).encode())
        elif self.path == "/lent":
            time.sleep(1.5)
            self._rep(200, b"{}")
        elif self.path == "/accents":
            self._rep(200, "voilà, é à ü".encode(), type_="text/html")
        elif self.path == "/flux":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write("ligne é\n\nsuite\r\n".encode())
            self.close_connection = True
        else:
            self._rep(404)

    def do_POST(self):
        corps = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._rep(200, json.dumps({"type": self.headers.get("Content-Type", ""), "taille": len(corps),
                                   "debut": corps[:200].decode("latin-1")}).encode())


@pytest.fixture(scope="module")
def base():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_get_json_avec_parametres_et_entetes(base):
    r = vp.requete("GET", base + "/json", params={"a": "é b"}, headers={"User-Agent": "essai"})
    assert r.status_code == 200 and r.json()["ua"] == "essai" and "a=%C3%A9+b" in r.json()["q"]


def test_post_json(base):
    r = vp.requete("POST", base + "/x", corps_json={"k": "é"})
    d = r.json()
    assert d["type"] == "application/json" and json.loads(d["debut"].encode("latin-1"))["k"] == "é"


def test_erreur_http_est_une_reponse_pas_une_exception(base):
    r = vp.requete("GET", base + "/404")
    assert r.status_code == 404 and r.json() == {"error": "absent"}
    with pytest.raises(vp.ErreurHTTP):
        r.raise_for_status()


def test_redirection_suivie_ou_non(base):
    assert vp.requete("GET", base + "/redir").status_code == 200
    r = vp.requete("GET", base + "/redir", suivre_redirections=False)
    assert r.status_code == 302 and r.headers["Location"] == "/json"


def test_multipart_champs_et_fichier(base):
    r = vp.requete("POST", base + "/up", files={"file": ("a.bin", b"\x00\xff" * 100, "audio/mpeg")}, data={"model": "m"})
    d = r.json()
    assert d["type"].startswith("multipart/form-data; boundary=") and d["taille"] > 200
    assert 'name="model"' in d["debut"] or 'name="file"' in d["debut"]


def test_session_garde_et_met_a_jour_les_cookies(base):
    s = vp.Session()
    s.cookies["__client"] = "ancien"
    assert s.get(base + "/qui").json()["cookie"] == "__client=ancien"
    s.get(base + "/cookie")
    envoye = s.get(base + "/qui").json()["cookie"]
    assert "__client=neuf" in envoye and "autre=1" in envoye
    s.get(base + "/efface")
    assert s.get(base + "/qui").json()["cookie"] == "__client=neuf"


def test_nouveau_cookie_se_lit_dans_raw_headers(base):
    s = vp.Session()
    r = s.get(base + "/cookie")
    assert vp._nouveau_cookie(r) == "neuf"


def test_delai_depasse(base):
    with pytest.raises(vp.DelaiDepasse):
        vp.requete("GET", base + "/lent", timeout=0.3)


def test_hote_injoignable_leve_erreur_reseau():
    with pytest.raises(vp.ErreurReseau):
        vp.requete("GET", "http://127.0.0.1:1/", timeout=2)


def test_texte_decode_en_utf8_malgre_l_absence_de_charset(base):
    assert vp.requete("GET", base + "/accents").text == "voilà, é à ü"


def test_iter_lignes_et_contenu_en_flux(base):
    r = vp.requete("GET", base + "/flux", stream=True)
    assert list(r.iter_lines(decode_unicode=True)) == ["ligne é", "", "suite"]
    r = vp.requete("GET", base + "/flux", stream=True)
    assert b"".join(r.iter_content(4)).decode() == "ligne é\n\nsuite\r\n"


def test_le_pont_n_importe_pas_requests():
    source = Path(vp.__file__).read_text()
    assert "import requests" not in source and "requests." not in source.replace("# requests", "")
