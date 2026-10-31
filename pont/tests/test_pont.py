import json
import os
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


def test_usage_repartit_le_total_connu_entre_entree_et_sortie():
    """Venice donne le total du contexte (route agents) mais pas la sortie : la sortie est estimée, le reste est l'entrée."""
    rep = vp.reponse_openai("m", "x" * 400, None, jetons=1000)
    u = rep["usage"]
    assert u["completion_tokens"] == 100
    assert u["prompt_tokens"] == 900
    assert u["total_tokens"] == 1000


def test_usage_estime_l_entree_quand_venice_ne_donne_aucun_total():
    corps = {"systemPrompt": "s" * 400, "prompt": [{"role": "user", "content": "u" * 400}]}
    u = vp.reponse_openai("m", "ok", None, 0, corps)["usage"]
    assert u["prompt_tokens"] >= 200
    assert u["completion_tokens"] >= 1
    assert u["total_tokens"] == u["prompt_tokens"] + u["completion_tokens"]


class _ReponseFactice:
    def __init__(self, code, lignes=()):
        self.status_code, self._lignes, self.ferme = code, list(lignes), False
        self.text = ""

    def iter_lines(self, decode_unicode=False):
        return iter(self._lignes)

    def close(self):
        self.ferme = True


class _JetonFactice:
    def __init__(self):
        self.invalide = 0

    def obtenir(self):
        return "j"

    def invalider(self):
        self.invalide += 1


def test_discuter_reessaie_apres_une_surcharge_500(monkeypatch):
    appels = []

    def faux_requete(*a, **k):
        appels.append(1)
        return _ReponseFactice(500 if len(appels) == 1 else 200, ['{"content":"ok","kind":"content"}'])

    monkeypatch.setattr(vp, "requete", faux_requete)
    monkeypatch.setattr(vp.time, "sleep", lambda s: None)
    assert "".join(vp.morceaux_contenu(vp.discuter(_JetonFactice(), {}))) == "ok"
    assert len(appels) == 2


def test_discuter_abandonne_apres_trois_echecs(monkeypatch):
    monkeypatch.setattr(vp, "requete", lambda *a, **k: _ReponseFactice(503))
    monkeypatch.setattr(vp.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="503"):
        vp.discuter(_JetonFactice(), {})


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
    if os.name == "posix":   # Windows n'a pas de permissions 600
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
    """Venice répond text/html sans charset : un client qui suppose ISO-8859-1 sort 'Ã©' pour 'é' (mesuré le 28/10/2026)."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Venice(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            corps = '{"content":"été","kind":"content"}\n'.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

    srv = HTTPServer(("127.0.0.1", 0), _Venice)  # serveur local : un test n'appelle jamais le vrai Venice
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(vp, "OUTERFACE", f"http://127.0.0.1:{srv.server_address[1]}/chat")

    class _Jeton:
        def obtenir(self):
            return "j"

    try:
        assert "".join(vp.morceaux_contenu(vp.discuter(_Jeton(), {}))) == "été"
    finally:
        srv.shutdown()


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


def test_sse_porte_l_usage_sur_le_dernier_morceau_seulement():
    """Sans usage dans le flux, opencode compte 0 jeton : la compaction automatique ne se déclenche plus."""
    morceaux = vp.morceaux_sse(vp.reponse_openai("m", "Salut", None, jetons=1000))
    assert morceaux[-1]["usage"]["total_tokens"] == 1000
    assert all("usage" not in m for m in morceaux[:-1])
    appels = [{"id": "call_a", "type": "function", "function": {"name": "get_time", "arguments": "{}"}}]
    appel = vp.morceaux_sse(vp.reponse_openai("m", None, appels, jetons=800))
    assert appel[-1]["usage"]["total_tokens"] == 800


def test_extraction_ignore_le_texte_apres_l_appel():
    texte = '{"tool_calls":[{"name":"get_time","arguments":{"ville":"Paris"}}]}Résumé de la session. Tool not found.'
    contenu, appels = vp.extraire_appels(texte, OUTILS)
    assert contenu is None
    assert json.loads(appels[0]["function"]["arguments"]) == {"ville": "Paris"}


def test_prose_avant_l_appel_devient_le_contenu():
    """Le modèle annonce souvent son geste avant le JSON : la prose est gardée, l'appel exécuté."""
    texte = 'Je vais lire le fichier :\n{"tool_calls":[{"name":"get_time","arguments":{}}]}'
    contenu, appels = vp.extraire_appels(texte, OUTILS)
    assert contenu == "Je vais lire le fichier :"
    assert appels[0]["function"]["name"] == "get_time"


def test_exemple_cite_avec_outil_inconnu_reste_du_texte():
    texte = 'Voici un exemple : {"tool_calls":[{"name":"inconnu","arguments":{}}]}'
    contenu, appels = vp.extraire_appels(texte, OUTILS)
    assert appels is None and contenu == texte


def test_refus_outils_reconnait_tool_not_found():
    assert vp.refus_outils("Résumé : tous répondent « Tool not found ».")
    assert vp.refus_outils("Il n'y a pas d'outil bash dans cette conversation.")
    assert vp.refus_outils("No tool available here.")
    assert not vp.refus_outils("Voici le résultat : 3 lignes.")


def test_rappeler_correction_ajoute_la_consigne_sans_muter():
    corps = vp.construire_corps_venice("kimi-k2-5", [{"role": "user", "content": "x"}], OUTILS, {})
    corrige = vp.rappeler_correction(corps, OUTILS)
    assert "CORRECTION" in corrige["systemPrompt"]
    assert "get_time" in corrige["systemPrompt"]
    assert "CORRECTION" in corrige["prompt"][-1]["content"]
    assert "CORRECTION" not in corps["systemPrompt"]


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


# --- Flux au fil de l'eau (29/10/2026) -----------------------------------------------------------------------------------

class _JetonVide:
    def obtenir(self):
        return "j"

    def etat(self):
        return {"cookie_ok": True}


def test_deltas_agent_omet_le_raisonnement_et_rend_les_jetons():
    etat = {"jetons": 0}
    assert list(vp.deltas_agent(FLUX_AGENT, etat)) == ["o", "k é"]
    assert etat["jetons"] == 15024


def test_flux_sse_relaie_un_morceau_avant_la_fin(monkeypatch):
    """Preuve du vrai flux : le client lit le premier morceau alors que Venice n'a pas fini."""
    import threading
    import urllib.request
    suite = threading.Event()

    def faux_discuter(jeton, corps):
        def lignes():
            yield '{"kind":"content","content":"premier"}'
            assert suite.wait(5), "le client n'a rien reçu avant la fin du flux"
            yield '{"kind":"content","content":"second"}'
        return lignes()

    monkeypatch.setattr(vp, "discuter", faux_discuter)
    srv = vp.ServeurPont(("127.0.0.1", 0), vp.fabriquer_handler(_JetonVide(), "cle"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        corps = json.dumps({"model": "qwen-3-8-27b", "messages": [{"role": "user", "content": "x"}],
                            "stream": True}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions",
                                     data=corps, headers={"Authorization": "Bearer cle",
                                                          "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            debut = b""
            for _ in range(3):  # le premier morceau arrive dans les 3 premières lignes (rôle puis contenu)
                debut += r.readline()
                if b"premier" in debut:
                    break
            assert b"premier" in debut
            suite.set()
            reste = r.read()
        assert b"second" in reste and b"[DONE]" in reste
    finally:
        srv.shutdown()


def test_flux_sse_garde_l_analyse_des_outils(monkeypatch):
    """Avec des outils, la réponse reste mise en tampon : le JSON d'appel doit être parsé avant l'envoi."""
    import threading
    import urllib.request
    appel = json.dumps({"tool_calls": [{"name": "get_time", "arguments": {}}]})

    def faux_discuter(jeton, corps):
        return iter([json.dumps({"kind": "content", "content": appel})])

    monkeypatch.setattr(vp, "discuter", faux_discuter)
    srv = vp.ServeurPont(("127.0.0.1", 0), vp.fabriquer_handler(_JetonVide(), "cle"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        corps = json.dumps({"model": "qwen-3-8-27b", "messages": [{"role": "user", "content": "heure ?"}],
                            "tools": OUTILS, "stream": True}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions",
                                     data=corps, headers={"Authorization": "Bearer cle",
                                                          "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            brut = r.read().decode()
        assert '"tool_calls"' in brut and "get_time" in brut
    finally:
        srv.shutdown()


def test_relance_corrective_quand_le_modele_croit_n_avoir_aucun_outil(monkeypatch):
    """La route agents fait parfois appeler les outils natifs de Venice (« Tool not found ») : on relance une fois."""
    import threading
    import urllib.request
    reponses = iter([("Il n'y a pas d'outil disponible. Tool not found.", 10),
                     ('{"tool_calls":[{"name":"get_time","arguments":{}}]}', 20)])
    corps_envoyes = []

    def faux_discuter_agent(jeton, modele, corps, couper_natif=False):
        corps_envoyes.append(corps)
        return next(reponses)

    monkeypatch.setattr(vp, "discuter_agent", faux_discuter_agent)
    srv = vp.ServeurPont(("127.0.0.1", 0), vp.fabriquer_handler(_JetonVide(), "cle"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        corps = json.dumps({"model": "kimi-k2-5", "messages": [{"role": "user", "content": "heure ?"}],
                            "tools": OUTILS}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions",
                                     data=corps, headers={"Authorization": "Bearer cle",
                                                          "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            rep = json.loads(r.read())
        assert rep["choices"][0]["finish_reason"] == "tool_calls"
        assert rep["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_time"
        assert len(corps_envoyes) == 2
        assert "CORRECTION" in corps_envoyes[1]["systemPrompt"]
    finally:
        srv.shutdown()


def test_journal_une_ligne_par_requete_sans_parametres(serveur, capsys):
    requete, *_ = serveur
    requete("/health")
    requete("/v1/models?jeton=secret")
    err = capsys.readouterr().err
    assert "GET /health 200" in err
    assert "GET /v1/models " in err
    assert "secret" not in err


def test_journal_desactivable(serveur, capsys, monkeypatch):
    monkeypatch.setattr(vp, "JOURNAL", False)
    requete, *_ = serveur
    requete("/health")
    assert "/health" not in capsys.readouterr().err


# --- Appels d'outils natifs de la route agents (DeepSeek V4.1 Flash, 31/10/2026) ---------------------------------

FLUX_NATIF = [
    "event: response.output_item.added",
    'data: {"item":{"id":"tcg_agent-node:llm:0","type":"veniceai:tool_call_generation"}}', "",
    "event: veniceai:tool_call_generation.in_progress",
    'data: {"item_id":"tcg_agent-node:llm:0","detected_tools":[{"type":"Unrecognized","name":"Bash"}]}', "",
    "event: response.output_text.delta", 'data: {"item_id":"agent-node:llm:wrap_up","delta":"Tout a échoué"}', "",
]


def test_flux_agent_coupe_au_premier_appel_natif():
    with pytest.raises(vp.OutilNatifTente) as e:
        vp.lire_flux_agent(FLUX_NATIF, couper_natif=True)
    assert e.value.noms == [] or "Bash" in e.value.noms


def test_flux_agent_sans_coupure_garde_l_ancien_comportement():
    assert vp.lire_flux_agent(FLUX_NATIF)[0] == "Tout a échoué"


def _appel_chat(monkeypatch, sequence, flux=False):
    """Fait passer une requête outillée sur la route agents ; `sequence` : liste de FLUX SSE (un par appel)."""
    restants = iter(sequence)
    corps_envoyes = []

    def fausse_reponse_agent(jeton, modele, corps):
        corps_envoyes.append(corps)
        return iter(next(restants))

    monkeypatch.setattr(vp, "reponse_agent", fausse_reponse_agent)
    req = {"model": "deepseek-v4-1-flash-uncensored", "messages": [{"role": "user", "content": "heure ?"}],
           "tools": OUTILS}
    return vp.collecter(vp.evenements_chat(_JetonVide(), req, flux=flux)), corps_envoyes


def _flux_texte(texte):
    return ["event: response.output_text.delta",
            "data: " + json.dumps({"item_id": "agent-node:llm:0", "delta": texte}), ""]


@pytest.mark.parametrize("flux", [False, True])
def test_appel_natif_relance_tout_de_suite_avec_correction(monkeypatch, flux):
    (contenu, appels, fin), corps = _appel_chat(
        monkeypatch, [FLUX_NATIF, _flux_texte('{"tool_calls":[{"name":"get_time","arguments":{}}]}')], flux)
    assert appels and appels[0]["function"]["name"] == "get_time"
    assert fin["raison"] == "tool_calls"
    assert not contenu or "échoué" not in contenu  # le bilan d'échec de Venice n'est jamais relayé
    assert len(corps) == 2 and "CORRECTION" in corps[1]["systemPrompt"]


def test_appel_natif_deux_relances_puis_message_clair(monkeypatch):
    (contenu, appels, fin), corps = _appel_chat(monkeypatch, [FLUX_NATIF, FLUX_NATIF, FLUX_NATIF], flux=True)
    assert appels is None
    assert len(corps) == 1 + vp.RELANCES_NATIF
    assert "[pont]" in contenu and "kimi-k2-5" in contenu


def test_appel_natif_puis_reponse_en_prose(monkeypatch):
    (contenu, appels, _), _ = _appel_chat(monkeypatch, [FLUX_NATIF, _flux_texte("Il est midi.")])
    assert appels is None and contenu == "Il est midi."


def test_appel_sans_cle_arguments_et_accolade_en_trop():
    """Forme rendue par DeepSeek au rejeu du 31/10/2026 : arguments à plat et une accolade de trop."""
    outils = [{"type": "function", "function": {"name": "Read", "parameters": {}}}]
    texte = ('{"tool_calls": [{"name": "Read", "arguments": {"file_path": "a.py"}}, '
             '{"name": "Read", "file_path": "b.py"}}, {"name": "Read", "file_path": "c.py"}}]}')
    _, appels = vp.extraire_appels(texte, outils)
    assert [json.loads(a["function"]["arguments"]) for a in appels] == [
        {"file_path": "a.py"}, {"file_path": "b.py"}, {"file_path": "c.py"}]
