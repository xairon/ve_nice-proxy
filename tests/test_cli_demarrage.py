"""Démarrage sans friction : --version, run (sans systemd), quickstart (login, service, état, configuration du client)."""
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


@pytest.fixture
def cookie(tmp_path):
    f = tmp_path / "cookie.txt"
    f.write_text("x" * 60)
    return str(f)


def test_version(vs, capsys):
    with pytest.raises(SystemExit) as e:
        vs.main(["--version"])
    assert e.value.code == 0 and capsys.readouterr().out.startswith("venice-setup ")


def test_run_dry_run_affiche_la_commande_sans_lancer(vs, tmp_path, cookie, monkeypatch, capsys):
    vs.main(["login", "--cookie-fichier", cookie, "--sans-verification"])
    monkeypatch.setattr(vs.subprocess, "run", lambda *a, **k: pytest.fail("ne doit pas lancer le pont"))
    assert vs.main(["run", "--dry-run"]) == 0
    sortie = capsys.readouterr().out
    assert "venice_pont.py" in sortie and "127.0.0.1:8700" in sortie and "x" * 20 not in sortie


def test_run_lance_le_pont_avec_l_environnement_du_profil(vs, tmp_path, cookie, monkeypatch):
    vs.main(["login", "--cookie-fichier", cookie, "--sans-verification"])
    appels = []

    class _Fini:
        returncode = 0

    monkeypatch.setattr(vs.subprocess, "run", lambda cmd, env=None, **k: appels.append((cmd, env)) or _Fini())
    assert vs.main(["run"]) == 0
    cmd, env = appels[0]
    assert cmd[0] == vs.sys.executable and cmd[1].endswith("venice_pont.py")
    assert env["VENICE_PONT_ENV"].endswith("venice.env") and env["VENICE_PONT_ECOUTE"] == "127.0.0.1:8700"
    assert env["VENICE_PONT_CREDITS"].endswith("credits.json")


def test_run_sans_login_explique_quoi_faire(vs, capsys):
    assert vs.main(["run"]) == 2
    assert "login" in capsys.readouterr().err


def test_install_sans_systemd_oriente_vers_run(vs, tmp_path, cookie, monkeypatch, capsys):
    vs.main(["login", "--cookie-fichier", cookie, "--sans-verification"])
    monkeypatch.setattr(vs, "systemd_disponible", lambda: False)
    assert vs.main(["install"]) == 2
    assert "venice-setup run" in capsys.readouterr().err
    assert not (tmp_path / "systemd").exists()


def test_quickstart_enchaine_login_service_etat_et_client(vs, tmp_path, cookie, monkeypatch, capsys):
    monkeypatch.setattr(vs, "systemd_disponible", lambda: True)
    etapes = []
    monkeypatch.setattr(vs, "systemctl", lambda *a, simule=False: etapes.append(a) or 0)
    monkeypatch.setattr(vs.time, "sleep", lambda s: None)
    monkeypatch.setattr(vs, "appel", lambda p, chemin, delai=8: {"ok": True, "cookie_ok": True, "cookie_jours_restants": 300,
                                                                 "credits": {"courant": 285, "reference": 285, "alerte": False}})
    assert vs.main(["quickstart", "--cookie-fichier", cookie, "--sans-verification", "--harnais", "openai"]) == 0
    sortie = capsys.readouterr().out
    env = tmp_path / "cfg" / "defaut" / "venice.env"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600 and (tmp_path / "systemd" / "venice-pont.service").exists()
    assert ("enable", "--now", "venice-pont") in etapes
    assert "Pont defaut : OK" in sortie and "OPENAI_BASE_URL=http://127.0.0.1:8700/v1" in sortie
    assert "x" * 20 not in sortie


def test_quickstart_sans_systemd_indique_run_et_continue(vs, tmp_path, cookie, monkeypatch, capsys):
    monkeypatch.setattr(vs, "systemd_disponible", lambda: False)
    assert vs.main(["quickstart", "--cookie-fichier", cookie, "--sans-verification"]) == 0
    sortie = capsys.readouterr().out
    assert "venice-setup run" in sortie and "OPENAI_BASE_URL" in sortie


def test_quickstart_dry_run_n_ecrit_rien(vs, tmp_path, cookie, monkeypatch, capsys):
    monkeypatch.setattr(vs, "systemd_disponible", lambda: True)
    assert vs.main(["quickstart", "--cookie-fichier", cookie, "--sans-verification", "--dry-run"]) == 0
    assert not (tmp_path / "cfg" / "defaut").exists() and not (tmp_path / "systemd").exists()
    assert "[dry-run]" in capsys.readouterr().out


def test_quickstart_cookie_invalide_s_arrete_au_login(vs, tmp_path, monkeypatch, capsys):
    f = tmp_path / "c.txt"
    f.write_text("court")
    monkeypatch.setattr(vs, "systemd_disponible", lambda: True)
    assert vs.main(["quickstart", "--cookie-fichier", str(f), "--sans-verification"]) == 2
    assert not (tmp_path / "systemd").exists()


def test_profils_json_reste_valide_apres_quickstart(vs, tmp_path, cookie, monkeypatch):
    monkeypatch.setattr(vs, "systemd_disponible", lambda: False)
    vs.main(["quickstart", "--cookie-fichier", cookie, "--sans-verification"])
    assert json.loads((tmp_path / "cfg" / "profils.json").read_text())["defaut"]["port"] == 8700
