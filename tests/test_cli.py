"""Tests du CLI venice-setup : tout dans tmp_path, aucun appel réseau, aucune écriture hors du dossier de test."""
import importlib.machinery
import importlib.util
import json
import stat
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent


@pytest.fixture
def vs(tmp_path, monkeypatch):
    monkeypatch.setenv("VENICE_SETUP_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("VENICE_SETUP_SYSTEMD", str(tmp_path / "systemd"))
    monkeypatch.setenv("VENICE_SETUP_OPENCODE", str(tmp_path / "oc" / "opencode.json"))
    loader = importlib.machinery.SourceFileLoader("venice_setup_cli", str(RACINE / "venice-setup"))
    spec = importlib.util.spec_from_loader("venice_setup_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def login(vs, tmp_path, nom="defaut"):
    f = tmp_path / "cookie.txt"
    f.write_text("x" * 60)
    return vs.main(["login", "--profil", nom, "--cookie-fichier", str(f), "--sans-verification"])


def test_login_ecrit_en_600_et_conserve_la_cle(vs, tmp_path):
    assert login(vs, tmp_path) == 0
    env = tmp_path / "cfg" / "defaut" / "venice.env"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    cle = vs.lire_env(env)["VENICE_PONT_CLE"]
    assert login(vs, tmp_path) == 0
    assert vs.lire_env(env)["VENICE_PONT_CLE"] == cle
    assert list(env.parent.glob("venice.env.bak-*"))


def test_login_dry_run_n_ecrit_rien(vs, tmp_path):
    f = tmp_path / "c.txt"; f.write_text("y" * 60)
    assert vs.main(["login", "--cookie-fichier", str(f), "--sans-verification", "--dry-run"]) == 0
    assert not (tmp_path / "cfg" / "defaut" / "venice.env").exists()


def test_cookie_trop_court_refuse(vs, tmp_path):
    f = tmp_path / "c.txt"; f.write_text("court")
    assert vs.main(["login", "--cookie-fichier", str(f), "--sans-verification"]) == 2


def test_deux_profils_deux_ports(vs, tmp_path):
    login(vs, tmp_path, "a"); login(vs, tmp_path, "b")
    p = json.loads((tmp_path / "cfg" / "profils.json").read_text())
    assert p["a"]["port"] != p["b"]["port"]


def test_unite_sans_variable_non_remplacee(vs, tmp_path):
    login(vs, tmp_path)
    texte = vs.unite(vs.profil("defaut"), RACINE / "pont" / "venice_pont.py")
    assert "@@" not in texte and "127.0.0.1:8700" in texte


def test_install_dry_run_n_ecrit_pas_l_unite(vs, tmp_path, capsys):
    login(vs, tmp_path)
    assert vs.main(["install", "--dry-run"]) == 0
    assert not (tmp_path / "systemd").exists()
    assert "[dry-run]" in capsys.readouterr().out


def test_uninstall_purger_ne_touche_que_le_profil(vs, tmp_path):
    login(vs, tmp_path, "a"); login(vs, tmp_path, "b")
    assert vs.main(["uninstall", "--profil", "a", "--purger", "--dry-run"]) == 0
    assert (tmp_path / "cfg" / "a").exists()  # dry-run
    vs.systemctl = lambda *a, **k: 0
    assert vs.main(["uninstall", "--profil", "a", "--purger"]) == 0
    assert not (tmp_path / "cfg" / "a").exists() and (tmp_path / "cfg" / "b").exists()


def test_harness_opencode_fusionne_sans_ecraser(vs, tmp_path):
    login(vs, tmp_path)
    oc = tmp_path / "oc" / "opencode.json"
    oc.parent.mkdir(); oc.write_text(json.dumps({"model": "autre/modele", "provider": {"autre": {"x": 1}}}))
    assert vs.main(["harness", "opencode", "--appliquer"]) == 0
    cfg = json.loads(oc.read_text())
    assert cfg["model"] == "autre/modele" and "autre" in cfg["provider"] and "venice-direct" in cfg["provider"]
    assert list(oc.parent.glob("opencode.json.bak-*"))


def test_harness_opencode_refuse_jsonc(vs, tmp_path):
    login(vs, tmp_path)
    oc = tmp_path / "oc" / "opencode.jsonc"
    oc.parent.mkdir(); oc.write_text("{ // commentaire\n}")
    assert vs.main(["harness", "opencode", "--appliquer"]) == 2
    assert oc.read_text() == "{ // commentaire\n}"


def test_aucun_secret_dans_la_sortie_des_harnais(vs, tmp_path, capsys):
    login(vs, tmp_path)
    cle = vs.lire_env(tmp_path / "cfg" / "defaut" / "venice.env")["VENICE_PONT_CLE"]
    for nom in vs.HARNAIS:
        vs.main(["harness", nom])
    sortie = capsys.readouterr().out
    assert cle not in sortie and "x" * 60 not in sortie


def test_harnais_non_testes_marques(vs):
    assert all(v[0].startswith(("TESTÉ", "NON TESTÉ")) for v in vs.HARNAIS.values())
    assert vs.HARNAIS["aider"][0].startswith("NON TESTÉ")
    # Codex CLI et Claude Code ne passent que par OmniRoute (/v1/responses, /v1/messages) : l'état doit le dire
    assert "OmniRoute" in vs.HARNAIS["codex"][0] and "OmniRoute" in vs.HARNAIS["claude-code"][0]


def test_codex_et_claude_code_pointent_sur_omniroute(vs, tmp_path, capsys):
    login(vs, tmp_path)
    vs.main(["harness", "codex", "--modele", "ven-kimi"])
    vs.main(["harness", "claude-code", "--modele", "ven-kimi"])
    sortie = capsys.readouterr().out
    assert 'wire_api = "responses"' in sortie and "http://127.0.0.1:20128/v1" in sortie
    assert "ANTHROPIC_BASE_URL=http://127.0.0.1:20128" in sortie and "ANTHROPIC_API_KEY" in sortie


# --- login : validation du cookie et effets de bord (trouvés à la campagne de tests du 28/10/2026) ---

class _Entetes:
    def __init__(self, cookies):
        self._c = cookies

    def get_all(self, nom):
        return [f"{k}={v}; Path=/" for k, v in self._c] if nom == "Set-Cookie" else []


class _Rep:
    def __init__(self, code=200, corps=None, cookies=()):
        self.status_code, self._corps = code, corps or {}
        self.raw = type("Raw", (), {"headers": _Entetes(list(cookies))})()

    def json(self):
        return self._corps

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _session_clerk(client, cookies=()):
    """Double de requests.Session : GET /client renvoie `client`, POST /tokens un JWT qui expire dans une minute."""
    import base64
    import time
    charge = base64.urlsafe_b64encode(json.dumps({"exp": time.time() + 60}).encode()).decode().rstrip("=")

    class S:
        headers = {}

        def get(self, url, **kw):
            return _Rep(corps={"response": client}, cookies=cookies)

        def post(self, url, **kw):
            return _Rep(corps={"jwt": f"h.{charge}.s"})
    return S()


def test_cookie_sans_session_refuse_proprement(vs):
    with pytest.raises(vs.Erreur):
        vs.valider_cookie("z" * 60, session_factory=lambda: _session_clerk({}, cookies=[("__client", "anonyme")]))


def test_cookie_renouvele_par_clerk_est_celui_qui_est_ecrit(vs, tmp_path, monkeypatch):
    # Clerk peut renvoyer un __client neuf pendant la validation : l'ancien serait mort au prochain démarrage.
    def faux(cookie, session_factory=None):
        return {"solde": 1.0, "cookie": "renouvele" + "r" * 50}
    monkeypatch.setattr(vs, "valider_cookie", faux)
    f = tmp_path / "c.txt"; f.write_text("a" * 60)
    assert vs.main(["login", "--cookie-fichier", str(f)]) == 0
    assert "VENICE_CLERK_CLIENT=renouveler" in (tmp_path / "cfg" / "defaut" / "venice.env").read_text()


def test_valider_cookie_renvoie_le_cookie_renouvele_sans_ecrire_ailleurs(vs):
    client = {"last_active_session_id": "s1"}
    res = vs.valider_cookie("a" * 60, session_factory=lambda: _session_clerk(client, cookies=[("__client", "neuf" * 15)]))
    assert res["cookie"] == "neuf" * 15


def test_login_dry_run_ne_cree_pas_le_profil(vs, tmp_path):
    f = tmp_path / "c.txt"; f.write_text("y" * 60)
    assert vs.main(["login", "--profil", "p", "--cookie-fichier", str(f), "--sans-verification", "--dry-run"]) == 0
    assert not (tmp_path / "cfg" / "profils.json").exists()


def test_login_refuse_ne_cree_pas_le_profil(vs, tmp_path, monkeypatch):
    def refuse(cookie, session_factory=None):
        raise vs.Erreur("refusé")
    monkeypatch.setattr(vs, "valider_cookie", refuse)
    f = tmp_path / "c.txt"; f.write_text("y" * 60)
    assert vs.main(["login", "--profil", "p", "--cookie-fichier", str(f)]) == 2
    assert not (tmp_path / "cfg" / "profils.json").exists()


def test_dossier_de_profil_en_700(vs, tmp_path):
    login(vs, tmp_path)
    assert stat.S_IMODE((tmp_path / "cfg" / "defaut").stat().st_mode) == 0o700


@pytest.mark.parametrize("nom", ["..", "../x", "a/b", ".caché", "", "A B", "x" * 40])
def test_nom_de_profil_invalide_refuse(vs, tmp_path, nom):
    f = tmp_path / "c.txt"; f.write_text("y" * 60)
    assert vs.main(["login", "--profil", nom, "--cookie-fichier", str(f), "--sans-verification"]) == 2
    assert not (tmp_path / "cfg" / "profils.json").exists()


def test_purger_retire_le_profil_de_la_liste(vs, tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "systemctl", lambda *a, simule=False: 0)
    login(vs, tmp_path, "a"); login(vs, tmp_path, "b")
    assert vs.main(["uninstall", "--profil", "a", "--purger"]) == 0
    assert list(json.loads((tmp_path / "cfg" / "profils.json").read_text())) == ["b"]
    assert (tmp_path / "cfg" / "b" / "venice.env").exists()


def test_uninstall_sans_unite_ne_lance_pas_systemctl(vs, tmp_path, monkeypatch):
    login(vs, tmp_path)
    appels = []
    monkeypatch.setattr(vs, "systemctl", lambda *a, simule=False: appels.append(a) or 0)
    vs.main(["uninstall"])
    assert ("disable", "--now", "venice-pont") not in appels
