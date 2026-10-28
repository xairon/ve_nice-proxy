import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import venice_pont as vp  # noqa: E402

OUTILS = [{"type": "function", "function": {"name": "get_time", "description": "Heure",
           "parameters": {"type": "object", "properties": {"ville": {"type": "string"}}}}}]


def test_jeton_mis_en_cache_puis_renouvele():
    appels = []

    def mint():
        appels.append(1)
        return f"jwt{len(appels)}", time.time() + 60

    j = vp.JetonClerk(mint, marge=15)
    assert j.obtenir() == "jwt1"
    assert j.obtenir() == "jwt1"
    j.invalider()
    assert j.obtenir() == "jwt2"
    assert len(appels) == 2


def test_jeton_proche_expiration_est_renouvele():
    seq = iter([("a", time.time() + 5), ("b", time.time() + 60)])
    j = vp.JetonClerk(lambda: next(seq), marge=15)
    assert j.obtenir() == "a"
    assert j.obtenir() == "b"


def test_cookie_mort_leve_cookie_expire():
    def mint():
        raise vp.CookieExpire("client 401")

    j = vp.JetonClerk(mint)
    with pytest.raises(vp.CookieExpire):
        j.obtenir()
    assert j.etat()["cookie_ok"] is False


def test_messages_sans_outils_passent_tels_quels():
    corps = vp.construire_corps_venice("qwen3-6-27b", [{"role": "user", "content": "Salut"}], None, {})
    assert corps["modelId"] == "qwen3-6-27b"
    assert corps["prompt"] == [{"role": "user", "content": "Salut"}]
    assert corps["systemPrompt"] == ""


def test_systeme_extrait_et_outils_injectes():
    msgs = [{"role": "system", "content": "Sois bref"}, {"role": "user", "content": "Heure ?"}]
    corps = vp.construire_corps_venice("m", msgs, OUTILS, {})
    assert "Sois bref" in corps["systemPrompt"]
    assert "get_time" in corps["systemPrompt"]
    assert "tool_calls" in corps["systemPrompt"]
    assert all(m["role"] != "system" for m in corps["prompt"])


def test_historique_outils_replie_en_texte():
    msgs = [
        {"role": "user", "content": "Heure ?"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "get_time", "arguments": "{\"ville\":\"Paris\"}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "14h"},
    ]
    corps = vp.construire_corps_venice("m", msgs, OUTILS, {})
    roles = [m["role"] for m in corps["prompt"]]
    assert roles == ["user", "assistant", "user"]
    assert "get_time" in corps["prompt"][1]["content"]
    assert "14h" in corps["prompt"][2]["content"]


def test_extraction_appel_outil_json_pur():
    texte = '{"tool_calls":[{"name":"get_time","arguments":{"ville":"Paris"}}]}'
    contenu, appels = vp.extraire_appels(texte, OUTILS)
    assert contenu is None
    assert appels[0]["function"]["name"] == "get_time"
    assert json.loads(appels[0]["function"]["arguments"]) == {"ville": "Paris"}
    assert appels[0]["id"].startswith("call_")


def test_extraction_dans_bloc_markdown_et_avec_pensee():
    texte = "<think>je réfléchis</think>\n```json\n{\"tool_calls\":[{\"name\":\"get_time\",\"arguments\":{}}]}\n```"
    contenu, appels = vp.extraire_appels(texte, OUTILS)
    assert appels and appels[0]["function"]["name"] == "get_time"


def test_outil_inconnu_ou_texte_simple_reste_du_texte():
    c, a = vp.extraire_appels('{"tool_calls":[{"name":"inconnu","arguments":{}}]}', OUTILS)
    assert a is None and c
    c, a = vp.extraire_appels("Il est 14h.", OUTILS)
    assert a is None and c == "Il est 14h."


def test_sans_outils_aucune_extraction():
    c, a = vp.extraire_appels('{"tool_calls":[]}', None)
    assert a is None and c == '{"tool_calls":[]}'


def test_lecture_flux_ndjson_ne_garde_que_le_contenu():
    lignes = [
        '{"kind":"meta","references":[]}',
        '{"content":"Bon","kind":"content"}',
        '{"kind":"meta","thinking":true}',
        '{"content":"jour","kind":"content"}',
        "",
        "pas du json",
    ]
    assert list(vp.morceaux_contenu(lignes)) == ["Bon", "jour"]


def test_reponse_openai_avec_appels():
    rep = vp.reponse_openai("m", None, [{"id": "call_1", "type": "function",
                                          "function": {"name": "x", "arguments": "{}"}}])
    ch = rep["choices"][0]
    assert ch["finish_reason"] == "tool_calls"
    assert ch["message"]["tool_calls"][0]["function"]["name"] == "x"
    assert ch["message"]["content"] is None


def test_reponse_openai_texte():
    rep = vp.reponse_openai("m", "ok", None)
    assert rep["choices"][0]["finish_reason"] == "stop"
    assert rep["choices"][0]["message"]["content"] == "ok"


def test_authentification_cle_pont():
    assert vp.cle_valide("Bearer secret", "secret")
    assert not vp.cle_valide("Bearer autre", "secret")
    assert not vp.cle_valide(None, "secret")
    assert not vp.cle_valide("Bearer x", "")


# --- source Clerk : rotation éventuelle du cookie, touche, métadonnées ---

class _Entetes:
    def __init__(self, cookies):
        self._c = cookies

    def get_all(self, nom):
        return [f"{k}={v}; Path=/; Secure; HttpOnly" for k, v in self._c] if nom == "Set-Cookie" else []


class _Raw:
    def __init__(self, cookies):
        self.headers = _Entetes(cookies)


class _Rep:
    def __init__(self, code=200, corps=None, cookies=()):
        self.status_code, self._corps = code, corps or {}
        self.raw = _Raw(list(cookies))

    def json(self):
        return self._corps

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Session:
    """Double de requests.Session : réponses scriptées par (méthode, fin d'URL)."""
    def __init__(self, scripts):
        self.scripts, self.appels = scripts, []
        self.headers, self.nouveau_cookie = {}, None

    def _rep(self, methode, url):
        self.appels.append((methode, url.rsplit("/", 1)[-1]))
        return self.scripts[(methode, url.rsplit("/", 1)[-1])]

    def get(self, url, **kw):
        return self._rep("GET", url)

    def post(self, url, **kw):
        return self._rep("POST", url)


def _jwt(exp):
    import base64
    p = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"h.{p}.s"


def _scripts(set_cookie_client=None):
    cookies = [("__client", set_cookie_client)] if set_cookie_client else []
    return {
        ("GET", "client"): _Rep(corps={"response": {"last_active_session_id": "sess_1", "created_at": 1_000_000,
                                                    "cookie_expires_at": 9_000_000_000_000,
                                                    "sessions": [{"id": "sess_1", "expire_at": 9_100_000_000_000}]}},
                                cookies=cookies),
        ("POST", "tokens"): _Rep(corps={"jwt": _jwt(int(time.time()) + 60)}),
        ("POST", "touch"): _Rep(),
    }


def test_source_sans_rotation_garde_le_cookie_et_expose_les_dates(tmp_path):
    f = tmp_path / "venice.env"
    f.write_text("VENICE_CLERK_CLIENT=ancien\nVENICE_PONT_CLE=k\n")
    src = vp.SourceClerk("ancien", str(f), session_factory=lambda: _Session(_scripts()))
    jwt, exp = src.mint()
    assert jwt.startswith("h.") and exp > time.time()
    e = src.etat()
    assert e["cookie_cree_le"] == 1000.0
    assert e["cookie_expire_le"] == 9_000_000_000.0
    assert e["dernier_renouvellement"] is None
    assert "ancien" in f.read_text()


def test_nouveau_cookie_ecrit_atomiquement_en_memoire_et_dans_le_fichier(tmp_path):
    f = tmp_path / "venice.env"
    f.write_text("# note\nVENICE_CLERK_CLIENT=ancien\nVENICE_PONT_CLE=k\n")
    f.chmod(0o600)
    src = vp.SourceClerk("ancien", str(f), session_factory=lambda: _Session(_scripts("nouveau")))
    src.mint()
    assert src.cookie == "nouveau"
    texte = f.read_text()
    assert "VENICE_CLERK_CLIENT=nouveau" in texte and "VENICE_PONT_CLE=k" in texte and "# note" in texte
    assert "ancien" not in texte
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert src.etat()["dernier_renouvellement"] is not None
    assert not list(tmp_path.glob("*.tmp"))


def test_touche_appelle_touch_et_enregistre_la_date(tmp_path):
    f = tmp_path / "venice.env"
    f.write_text("VENICE_CLERK_CLIENT=c\n")
    sess = _Session(_scripts())
    src = vp.SourceClerk("c", str(f), session_factory=lambda: sess)
    src.toucher()
    assert ("POST", "touch") in sess.appels
    assert src.etat()["derniere_touche"] is not None


def test_cookie_mort_pendant_la_touche_leve_cookie_expire(tmp_path):
    f = tmp_path / "venice.env"
    f.write_text("VENICE_CLERK_CLIENT=c\n")
    s = _scripts()
    s[("GET", "client")] = _Rep(code=401)
    src = vp.SourceClerk("c", str(f), session_factory=lambda: _Session(s))
    with pytest.raises(vp.CookieExpire):
        src.toucher()


def test_deux_rotations_simultanees_ne_corrompent_pas_le_fichier(tmp_path):
    import threading
    f = tmp_path / "venice.env"
    f.write_text("VENICE_CLERK_CLIENT=a\nVENICE_PONT_CLE=k\n")
    src = vp.SourceClerk("a", str(f), session_factory=lambda: _Session(_scripts("n")))
    ts = [threading.Thread(target=src.mint) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert f.read_text().count("VENICE_CLERK_CLIENT=") == 1
    assert "VENICE_PONT_CLE=k" in f.read_text()


def test_alerte_quand_le_cookie_expire_bientot(tmp_path):
    f = tmp_path / "venice.env"
    f.write_text("VENICE_CLERK_CLIENT=c\n")
    s = _scripts()
    s[("GET", "client")] = _Rep(corps={"response": {"last_active_session_id": "s", "created_at": 1,
        "cookie_expires_at": int((time.time() + 10 * 86400) * 1000), "sessions": []}})
    src = vp.SourceClerk("c", str(f), session_factory=lambda: _Session(s))
    src.mint()
    assert src.etat()["cookie_jours_restants"] == pytest.approx(10, abs=0.1)
    assert src.etat()["cookie_bientot_expire"] is True


def test_flux_venice_decode_en_utf8_malgre_le_content_type_html(monkeypatch):
    """Venice répond text/html sans charset : requests supposait ISO-8859-1 et 'é' sortait 'Ã©' (mesuré le 28/10/2026)."""
    import types

    class _Rep:
        status_code = 200
        encoding = "ISO-8859-1"

        def iter_lines(self, decode_unicode=False):
            octets = '{"content":"été","kind":"content"}'.encode("utf-8")
            assert decode_unicode and self.encoding == "utf-8"
            yield octets.decode(self.encoding)

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(post=lambda *a, **k: _Rep()))

    class _Jeton:
        def obtenir(self):
            return "j"

    assert "".join(vp.morceaux_contenu(vp.discuter(_Jeton(), {}))) == "été"


def test_serveur_accepte_une_rafale_de_16_connexions():
    """File d'écoute par défaut de 5 : une rafale de 16 requêtes simultanées perdait des connexions (banc du 28/10/2026)."""
    assert vp.ServeurPont.request_queue_size >= 64
    assert vp.ServeurPont.daemon_threads is True


FLUX_AGENT = [
    "event: response.created", 'data: {"response":{"id":"r"}}', "",
    ": keepalive", "",
    "event: response.output_text.delta", 'data: {"item_id":"agent-node:llm:0","delta":"o"}', "",
    "event: response.output_text.delta", 'data: {"item_id":"agent-node:llm:0","delta":"k é"}', "",
    "event: response.output_text.done",
    'data: {"text":"ok é","context_metadata":{"total_tokens":15024,"max_context_length":524288}}', "",
    "event: response.completed", 'data: {"response":{"status":"completed"}}', "",
]


def test_messages_agent_met_le_systeme_en_premier_message_utilisateur():
    corps = {"systemPrompt": "Sois bref.", "prompt": [{"role": "user", "content": "salut"},
                                                      {"role": "assistant", "content": "bonjour"}]}
    msgs = vp.messages_agent(corps)
    assert [m["role"] for m in msgs] == ["user", "user", "assistant"]
    assert msgs[0]["content"][0]["text"] == "[System]\nSois bref."
    assert msgs[1]["content"][0] == {"type": "output_text", "text": "salut", "annotations": []}
    assert all(m["type"] == "message" and m["status"] == "completed" for m in msgs)


def test_lire_flux_agent_assemble_le_texte_et_les_jetons():
    texte, jetons = vp.lire_flux_agent(FLUX_AGENT)
    assert texte == "ok é"
    assert jetons == 15024


def test_lire_flux_agent_leve_sur_echec():
    with pytest.raises(RuntimeError, match="boom"):
        vp.lire_flux_agent(["event: response.failed", 'data: {"response":{"error":{"message":"boom"}}}', ""])


def test_modele_agent_reconnu_et_route(monkeypatch):
    assert vp.est_agent("deepseek-v4-1-flash-uncensored")
    assert vp.est_agent("kimi-k2-5")
    assert not vp.est_agent("qwen-3-8-27b")




def test_lire_flux_agent_ignore_le_raisonnement():
    """Le raisonnement arrive en output_text.delta sur un item rs_… ; il ne doit pas se mêler à la réponse."""
    flux = ["event: response.output_text.delta", 'data: {"item_id":"rs_agent-node:llm:0","delta":"je réfléchis"}', "",
            "event: response.output_text.delta", 'data: {"item_id":"agent-node:llm:0","delta":"51"}', ""]
    assert vp.lire_flux_agent(flux)[0] == "51"


def test_champs_extra_du_chat_classique_transmis_a_venice():
    corps = vp.construire_corps_venice("m", [{"role": "user", "content": "x"}], None, {
        "web_search": True, "web_scrape": True, "x_search": True, "include_venice_system_prompt": True,
        "reasoning_effort": "none"})
    assert corps["webEnabled"] and corps["webScrapeEnabled"] and corps["xSearchEnabled"]
    assert corps["includeVeniceSystemPrompt"] is True
    assert corps["reasoning"] is False


def test_champs_extra_absents_gardent_les_defauts_prudents():
    corps = vp.construire_corps_venice("m", [{"role": "user", "content": "x"}], None, {})
    assert corps["webEnabled"] is False and corps["includeVeniceSystemPrompt"] is False
    assert "reasoning" not in corps


def test_sse_appel_outil_en_format_canonique_openai():
    appels = [{"id": "call_a", "type": "function", "function": {"name": "get_time", "arguments": '{"ville":"Paris"}'}}]
    rep = vp.reponse_openai("m", None, appels)
    morceaux = vp.morceaux_sse(rep)
    premier = morceaux[0]["choices"][0]["delta"]["tool_calls"][0]
    assert premier["id"] == "call_a" and premier["function"]["name"] == "get_time"
    assert premier["function"]["arguments"] == ""
    suite = morceaux[1]["choices"][0]["delta"]["tool_calls"][0]
    assert suite["index"] == 0 and "id" not in suite
    assert suite["function"]["arguments"] == '{"ville":"Paris"}'
    assert morceaux[-1]["choices"][0]["finish_reason"] == "tool_calls"
    # les arguments concaténés par un client ne doivent apparaître qu'une fois
    tout = "".join(c["choices"][0]["delta"]["tool_calls"][0]["function"].get("arguments", "")
                   for c in morceaux if c["choices"][0]["delta"].get("tool_calls"))
    assert json.loads(tout) == {"ville": "Paris"}


def test_sse_texte_simple_inchange():
    morceaux = vp.morceaux_sse(vp.reponse_openai("m", "Salut", None))
    assert morceaux[0]["choices"][0]["delta"]["content"] == "Salut"
    assert morceaux[-1]["choices"][0]["finish_reason"] == "stop"


def test_extraction_ignore_le_texte_apres_l_appel():
    texte = '{"tool_calls":[{"name":"get_time","arguments":{"ville":"Paris"}}]}Résumé de la session. Tool not found.'
    contenu, appels = vp.extraire_appels(texte, OUTILS)
    assert contenu is None
    assert json.loads(appels[0]["function"]["arguments"]) == {"ville": "Paris"}


def test_texte_qui_ne_commence_pas_par_un_appel_reste_du_texte():
    texte = 'Voici un exemple : {"tool_calls":[{"name":"get_time","arguments":{}}]}'
    contenu, appels = vp.extraire_appels(texte, OUTILS)
    assert appels is None and contenu == texte


# --- Consigne d'outils, liste blanche, limiteur, suivi des crédits (28/10/2026) -------------------------------------------

def test_consigne_nomme_les_seuls_outils_disponibles():
    """Kimi K2.5 (route agents) répondait 0/4 « je n'ai pas l'outil write » : il se croit limité aux outils Venice (essai du 28/10/2026)."""
    corps = vp.construire_corps_venice("kimi-k2-5", [{"role": "user", "content": "x"}], OUTILS, {})
    assert "seuls outils" in corps["systemPrompt"].lower()
    assert "get_time" in corps["systemPrompt"].split("seuls outils")[1]


def test_modele_gratuit_autorise_modele_a_pieces_refuse():
    assert vp.modele_autorise("qwen-3-8-27b", {})
    assert vp.modele_autorise("kimi-k2-5", {})
    assert not vp.modele_autorise("zai-org-glm-5-2", {})
    assert not vp.modele_autorise("kimi-k2-7-code", {})


def test_debit_volontaire_autorise_un_modele_a_pieces():
    assert vp.modele_autorise("zai-org-glm-5-2", {"autoriser_debit": True})
    assert not vp.modele_autorise("zai-org-glm-5-2", {"autoriser_debit": "oui"})  # booléen vrai seulement


def test_limiteur_refuse_au_dela_du_plafond_puis_rouvre():
    horloge = [1000.0]
    lim = vp.LimiteurDebit(3, fenetre=60, horloge=lambda: horloge[0])
    assert [lim.essayer()[0] for _ in range(3)] == [True, True, True]
    ok, attente = lim.essayer()
    assert ok is False and 0 < attente <= 60
    horloge[0] += 61
    assert lim.essayer()[0] is True


def _jwt_solde(charge):
    import base64
    b = base64.urlsafe_b64encode(json.dumps(charge).encode()).decode().rstrip("=")
    return f"e30.{b}.sig"


def test_decoder_solde_lit_veniceCredits():
    assert vp.decoder_solde(_jwt_solde({"veniceCredits": 545, "bundledCreditsUsage": {"availableCredits": 45}})) == 545


def test_suivi_credits_alerte_quand_le_solde_baisse(tmp_path):
    soldes = iter([545, 545, 506])
    suivi = vp.SuiviCredits(lambda: next(soldes), fichier=tmp_path / "credits.json")
    assert suivi.rafraichir()["alerte"] is False
    assert suivi.rafraichir()["alerte"] is False
    e = suivi.rafraichir()
    assert e["alerte"] is True and e["debit"] == 39 and e["reference"] == 545 and e["courant"] == 506


def test_suivi_credits_acquittement_et_recharge(tmp_path):
    soldes = iter([100, 90, 90, 500])
    suivi = vp.SuiviCredits(lambda: next(soldes), fichier=tmp_path / "credits.json")
    suivi.rafraichir()
    assert suivi.rafraichir()["alerte"] is True
    assert suivi.acquitter()["alerte"] is False
    assert suivi.rafraichir()["alerte"] is False      # 90, référence remise à 90
    e = suivi.rafraichir()                            # recharge mensuelle : la référence suit
    assert e["reference"] == 500 and e["alerte"] is False


def test_suivi_credits_garde_la_reference_apres_redemarrage(tmp_path):
    f = tmp_path / "credits.json"
    vp.SuiviCredits(lambda: 545, fichier=f).rafraichir()
    e = vp.SuiviCredits(lambda: 500, fichier=f).rafraichir()
    assert e["reference"] == 545 and e["alerte"] is True


def test_suivi_credits_erreur_de_lecture_ne_leve_pas(tmp_path):
    def casse():
        raise RuntimeError("venice injoignable")
    e = vp.SuiviCredits(casse, fichier=tmp_path / "c.json").rafraichir()
    assert e["alerte"] is False and "injoignable" in e["erreur"]


@pytest.fixture
def serveur(monkeypatch, tmp_path):
    import threading
    import urllib.request

    class _Jeton:
        def obtenir(self):
            return "j"

        def etat(self):
            return {"cookie_ok": True}

    appels = []

    def faux_discuter(jeton, corps):
        appels.append(corps["modelId"])
        return iter(['{"kind":"content","content":"ok"}'])

    monkeypatch.setattr(vp, "discuter", faux_discuter)
    soldes = [545]
    suivi = vp.SuiviCredits(lambda: soldes[0], fichier=tmp_path / "c.json")
    suivi.rafraichir()
    lim = vp.LimiteurDebit(2, fenetre=60)
    srv = vp.ServeurPont(("127.0.0.1", 0), vp.fabriquer_handler(_Jeton(), "cle", None, limiteur=lim, suivi=suivi))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def requete(chemin, corps=None, cle="cle"):
        req = urllib.request.Request(base + chemin, data=None if corps is None else json.dumps(corps).encode(),
                                     method="GET" if corps is None else "POST", headers={"Authorization": "Bearer " + cle})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read()), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read()), dict(e.headers)

    yield requete, appels, soldes, suivi
    srv.shutdown()


def _chat(modele, **extra):
    return {"model": modele, "messages": [{"role": "user", "content": "salut"}], **extra}


def test_serveur_refuse_un_modele_a_pieces_sans_appeler_venice(serveur):
    requete, appels, *_ = serveur
    st, rep, _ = requete("/v1/chat/completions", _chat("zai-org-glm-5-2"))
    assert st == 403 and rep["error"]["code"] == "modele_payant_refuse" and appels == []


def test_serveur_laisse_passer_un_debit_volontaire(serveur):
    requete, appels, *_ = serveur
    st, _, _ = requete("/v1/chat/completions", _chat("zai-org-glm-5-2", autoriser_debit=True))
    assert st == 200 and appels == ["zai-org-glm-5-2"]


def test_serveur_limite_le_debit_avec_retry_after(serveur):
    requete, appels, *_ = serveur
    assert requete("/v1/chat/completions", _chat("qwen-3-8-27b"))[0] == 200
    assert requete("/v1/chat/completions", _chat("qwen-3-8-27b"))[0] == 200
    st, rep, entetes = requete("/v1/chat/completions", _chat("qwen-3-8-27b"))
    assert st == 429 and int(entetes["Retry-After"]) >= 1 and len(appels) == 2


def test_refus_de_modele_ne_consomme_pas_le_plafond(serveur):
    requete, appels, *_ = serveur
    for _ in range(5):
        assert requete("/v1/chat/completions", _chat("zai-org-glm-5-2"))[0] == 403
    assert requete("/v1/chat/completions", _chat("qwen-3-8-27b"))[0] == 200


def test_health_expose_les_credits_et_l_alerte(serveur):
    requete, _, soldes, suivi = serveur
    st, rep, _ = requete("/health")
    assert st == 200 and rep["credits"]["courant"] == 545 and rep["credits"]["alerte"] is False
    soldes[0] = 500
    suivi.rafraichir()
    assert requete("/health")[1]["credits"]["alerte"] is True


def test_acquittement_exige_la_cle_du_pont(serveur):
    requete, _, soldes, suivi = serveur
    soldes[0] = 500
    suivi.rafraichir()
    assert requete("/credits/acquitter", {}, cle="mauvaise")[0] == 401
    st, rep, _ = requete("/credits/acquitter", {})
    assert st == 200 and rep["alerte"] is False



def test_liste_des_modeles_gratuits_sans_doublon_et_sans_modele_a_pieces():
    ids = [m["id"] for m in vp.lister_modeles()]
    assert len(ids) == len(set(ids))
    assert {"qwen-3-8-27b", "kimi-k2-5", "deepseek-v4-1-flash-uncensored", "gemma4-uncensored"} <= set(ids)
    assert "zai-org-glm-5-2" not in ids
    assert {m["id"]: m["owned_by"] for m in vp.lister_modeles()}["kimi-k2-5"] == "venice-agent"
