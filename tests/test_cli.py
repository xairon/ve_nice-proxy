"""Tests du CLI venice-setup : tout dans tmp_path, aucun appel réseau, aucune écriture hors du dossier de test."""
import importlib.machinery
import importlib.util
import json
import os
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
    try:
        import requests  # noqa: F401
    except ImportError:
        pytest.skip("requests absent")
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
    assert vs.HARNAIS["codex"][0].startswith("NON TESTÉ") and vs.HARNAIS["claude-code"][0].startswith("NON TESTÉ")
