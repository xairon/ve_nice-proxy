"""Usage agentique (31/10/2026) : formats d'appel d'outil, tool_choice, flux avec outils, garde de contexte,
traductions Anthropic (/v1/messages) et Responses (/v1/responses), API officielle (serveur factice local)."""
import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import formats  # noqa: E402
import venice_pont as vp  # noqa: E402

OUTILS = [
    {"type": "function", "function": {"name": "read", "description": "Lit un fichier",
                                      "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "bash", "description": "Shell",
                                      "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}},
]


def _args(appel):
    return json.loads(appel["function"]["arguments"])


# --- extraction des appels ----------------------------------------------------------------------------------------

def test_balise_tool_call_style_qwen_hermes():
    texte = 'Je regarde.\n<tool_call>\n{"name": "read", "arguments": {"filePath": "a.py"}}\n</tool_call>'
    contenu, appels = vp.extraire_appels(texte, OUTILS)
    assert contenu == "Je regarde." and appels[0]["function"]["name"] == "read" and _args(appels[0]) == {"filePath": "a.py"}


def test_plusieurs_balises_donnent_plusieurs_appels():
    texte = ('<tool_call>{"name":"read","arguments":{"filePath":"a"}}</tool_call>'
             '<tool_call>{"name":"bash","arguments":{"command":"ls"}}</tool_call>')
    _, appels = vp.extraire_appels(texte, OUTILS)
    assert [a["function"]["name"] for a in appels] == ["read", "bash"]
    assert appels[0]["id"] != appels[1]["id"]


def test_objet_nu_liste_et_variantes_de_cles():
    _, a = vp.extraire_appels('{"name": "bash", "parameters": {"command": "ls"}}', OUTILS)
    assert _args(a[0]) == {"command": "ls"}
    _, a = vp.extraire_appels('[{"name":"read","arguments":{"filePath":"x"}},{"name":"bash","arguments":{}}]', OUTILS)
    assert len(a) == 2
    _, a = vp.extraire_appels('{"function": {"name": "functions.Read", "arguments": "{\\"filePath\\": \\"y\\"}"}}', OUTILS)
    assert a[0]["function"]["name"] == "read" and _args(a[0]) == {"filePath": "y"}


def test_json_repare_virgule_finale_et_appel_tronque():
    _, a = vp.extraire_appels('{"tool_calls":[{"name":"bash","arguments":{"command":"ls",}}]}', OUTILS)
    assert _args(a[0]) == {"command": "ls"}
    _, a = vp.extraire_appels('{"tool_calls":[{"name":"bash","arguments":{"command":"echo salut', OUTILS)
    assert _args(a[0]) == {"command": "echo salut"}


def test_bloc_json_au_milieu_de_la_prose():
    texte = 'Voici :\n```json\n{"tool_calls":[{"name":"read","arguments":{"filePath":"b"}}]}\n```\nmerci'
    contenu, a = vp.extraire_appels(texte, OUTILS)
    assert a and contenu == "Voici :"


def test_json_de_code_ordinaire_reste_du_texte():
    texte = 'Votre package.json :\n{"name": "mon-projet", "version": "1.0.0"}'
    contenu, a = vp.extraire_appels(texte, OUTILS)
    assert a is None and contenu == texte


def test_reflexion_non_fermee_n_est_pas_un_appel():
    texte = '<think>je pourrais appeler {"name":"bash","arguments":{}}'
    assert vp.extraire_appels(texte, OUTILS)[1] is None


# --- flux avec outils ---------------------------------------------------------------------------------------------

def test_filtre_laisse_passer_la_prose_et_retient_l_appel():
    f = vp.FiltreAppel()
    sortie = "".join(f.pousser(m) for m in ["Je vais ", "lire le fichier.\n", '{"tool', '_calls":[{"name":"read",',
                                            '"arguments":{}}]}'])
    assert sortie == "Je vais lire le fichier.\n"
    assert f.reste().startswith('{"tool_calls"')


def test_filtre_relache_une_accolade_ordinaire():
    f = vp.FiltreAppel()
    sortie = "".join(f.pousser(m) for m in ["La fonction f() { return 1; }", " est triviale, vraiment très triviale."])
    assert sortie + f.reste() == "La fonction f() { return 1; } est triviale, vraiment très triviale."
    assert "return 1" in sortie  # relâchée avant la fin, pas retenue jusqu'au bout


def test_filtre_relaie_la_reflexion_sans_y_chercher_d_appel():
    f = vp.FiltreAppel()
    sortie = "".join(f.pousser(m) for m in ["<think>", '{"name":"x"}', "</think>", "Réponse"])
    assert sortie + f.reste() == '<think>{"name":"x"}</think>Réponse'


# --- tool_choice, alias, contexte ---------------------------------------------------------------------------------

def test_tool_choice_none_required_et_impose():
    assert vp.preparer_outils({"tools": OUTILS, "tool_choice": "none"}) == (None, False, None)
    assert vp.preparer_outils({"tools": OUTILS, "tool_choice": "required"}) == (OUTILS, True, None)
    outils, obligatoire, nom = vp.preparer_outils({"tools": OUTILS, "tool_choice": {"type": "function", "function": {"name": "bash"}}})
    assert obligatoire and nom == "bash" and [o["function"]["name"] for o in outils] == ["bash"]


def test_alias_des_clients_de_code():
    assert vp.resoudre_modele("claude-sonnet-4-5-20250929") == "kimi-k2-5"
    assert vp.resoudre_modele("claude-3-5-haiku-20241022") == "qwen-3-8-27b"
    assert vp.resoudre_modele("gpt-5-codex") == "kimi-k2-5"
    assert vp.resoudre_modele("qwen-3-8-27b") == "qwen-3-8-27b"
    assert vp.resoudre_modele("api/zai-org-glm-4.6") == "api/zai-org-glm-4.6"
    assert vp.resoudre_modele("zai-org-glm-5-2") == "zai-org-glm-5-2"  # inconnu : passe tel quel (et sera refusé)
    assert vp.resoudre_modele("claude-x", vp.lire_alias("claude-*=gemma4-uncensored")) == "gemma4-uncensored"


def _corps(n, taille=1000, systeme="S"):
    prompt = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i} " + "x" * taille} for i in range(n)]
    return {"systemPrompt": systeme, "prompt": prompt, "maxTokens": 0}


def test_contexte_sous_le_plafond_inchange():
    c = _corps(4)
    assert vp.garder_contexte("qwen-3-8-27b", c, maximum=10000) is c


def test_contexte_elague_les_anciens_messages_en_gardant_debut_et_fin():
    c = vp.garder_contexte("qwen-3-8-27b", _corps(20), maximum=3000)
    contenus = [m["content"] for m in c["prompt"]]
    assert contenus[0].startswith("m0 ") and contenus[-1].startswith("m19 ")
    assert "retiré" in contenus[1] and len(contenus) < 20


def test_contexte_impossible_ou_elagage_coupe_leve_context_length_exceeded():
    with pytest.raises(vp.ContexteDepasse) as e:
        vp.garder_contexte("qwen-3-8-27b", _corps(3, systeme="s" * 40000), maximum=3000)
    assert e.value.statut == 400 and e.value.code == "context_length_exceeded" and "prompt is too long" in e.value.message
    with pytest.raises(vp.ContexteDepasse):
        vp.garder_contexte("qwen-3-8-27b", _corps(20), maximum=3000, elaguer=False)


def test_route_agents_non_concernee_par_la_garde():
    c = _corps(50)
    assert vp.garder_contexte("kimi-k2-5", c, maximum=100) is c


def test_contenu_et_nom_d_outil_conserves_dans_l_historique():
    msgs = [{"role": "user", "content": "go"},
            {"role": "assistant", "content": "Je lis.", "tool_calls": [{"id": "c1", "type": "function",
                                                                       "function": {"name": "read", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "contenu"}]
    corps = vp.construire_corps_venice("m", msgs, OUTILS, {})
    assert corps["prompt"][1]["content"].startswith("Je lis.\n")
    assert "(read, appel c1)" in corps["prompt"][2]["content"]


# --- serveur : faux Venice ----------------------------------------------------------------------------------------

class _Jeton:
    def obtenir(self):
        return "j"

    def invalider(self):
        pass

    def etat(self):
        return {"cookie_ok": True}


@pytest.fixture
def pont(monkeypatch):
    """Pont local dont la réponse de Venice (chat classique) est réglable : liste de morceaux par appel."""
    reponses, corps_recus = [], []

    def faux_discuter(jeton, corps):
        corps_recus.append(corps)
        morceaux = reponses.pop(0) if reponses else ["ok"]
        return iter(json.dumps({"kind": "content", "content": m}) for m in morceaux)

    monkeypatch.setattr(vp, "discuter", faux_discuter)
    srv = vp.ServeurPont(("127.0.0.1", 0), vp.fabriquer_handler(_Jeton(), "cle"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def poster(chemin, corps, entetes=None, brut=False):
        req = urllib.request.Request(base + chemin, data=json.dumps(corps).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(entetes or {"Authorization": "Bearer cle"})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                donnees = r.read().decode()
                return r.status, donnees if brut else json.loads(donnees)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    yield poster, reponses, corps_recus
    srv.shutdown()


def _sse(brut):
    """[(événement, données)] d'un flux SSE."""
    sortie, nom = [], None
    for ligne in brut.splitlines():
        if ligne.startswith("event: "):
            nom = ligne[7:]
        elif ligne.startswith("data: ") and ligne[6:] != "[DONE]":
            sortie.append((nom, json.loads(ligne[6:])))
            nom = None
    return sortie


APPEL_READ = '{"tool_calls":[{"name":"read","arguments":{"filePath":"a.py"}}]}'


def test_chat_flux_avec_outils_relaie_la_prose_puis_l_appel(pont):
    poster, reponses, _ = pont
    reponses.append(["Je vais lire ", "le fichier.\n", APPEL_READ[:20], APPEL_READ[20:]])
    st, brut = poster("/v1/chat/completions", {"model": "qwen-3-8-27b", "stream": True, "tools": OUTILS,
                                              "messages": [{"role": "user", "content": "lis a.py"}]}, brut=True)
    morceaux = [d for _, d in _sse(brut)]
    textes = "".join(m["choices"][0]["delta"].get("content") or "" for m in morceaux)
    appels = [tc for m in morceaux for tc in m["choices"][0]["delta"].get("tool_calls") or []]
    assert st == 200 and textes == "Je vais lire le fichier.\n"
    assert appels[0]["function"]["name"] == "read" and json.loads(appels[1]["function"]["arguments"]) == {"filePath": "a.py"}
    assert morceaux[-1]["choices"][0]["finish_reason"] == "tool_calls" and brut.rstrip().endswith("[DONE]")


def test_chat_tool_choice_required_relance_si_texte(pont):
    poster, reponses, corps_recus = pont
    reponses.extend([["Je pense qu'il faut lire."], [APPEL_READ]])
    st, rep = poster("/v1/chat/completions", {"model": "qwen-3-8-27b", "tools": OUTILS, "tool_choice": "required",
                                             "messages": [{"role": "user", "content": "lis"}]})
    assert st == 200 and rep["choices"][0]["finish_reason"] == "tool_calls"
    assert len(corps_recus) == 2 and "OBLIGATOIRE" in corps_recus[0]["systemPrompt"]


def test_chat_contexte_trop_long_refuse_proprement(pont, monkeypatch):
    poster, _, corps_recus = pont
    monkeypatch.setattr(vp, "CONTEXTE_CHAT", 1000)
    st, rep = poster("/v1/chat/completions", {"model": "qwen-3-8-27b", "messages": [
        {"role": "system", "content": "s" * 10000}, {"role": "user", "content": "x"}]})
    assert st == 400 and rep["error"]["code"] == "context_length_exceeded" and corps_recus == []


def test_chat_modele_manquant_400(pont):
    poster, *_ = pont
    st, rep = poster("/v1/chat/completions", {"messages": []})
    assert st == 400


# --- /v1/messages (Claude Code) -----------------------------------------------------------------------------------

OUTILS_ANTHROPIC = [{"name": "Read", "description": "Lit un fichier",
                     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}}}]


def test_messages_appel_d_outil_avec_x_api_key_et_alias(pont):
    poster, reponses, corps_recus = pont
    reponses.append(['Je lis.\n{"tool_calls":[{"name":"Read","arguments":{"file_path":"/a"}}]}'])
    st, rep = poster("/v1/messages", {
        "model": "claude-3-5-haiku-20241022", "max_tokens": 1024, "tools": OUTILS_ANTHROPIC,
        "system": [{"type": "text", "text": "Tu es Claude Code.", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "lis /a"}]}]},
        entetes={"x-api-key": "cle", "anthropic-version": "2023-06-01"})
    assert st == 200 and rep["type"] == "message" and rep["stop_reason"] == "tool_use"
    assert rep["content"][0] == {"type": "text", "text": "Je lis."}
    outil = rep["content"][1]
    assert outil["type"] == "tool_use" and outil["name"] == "Read" and outil["input"] == {"file_path": "/a"}
    assert outil["id"].startswith("toolu_")
    assert corps_recus[0]["modelId"] == "qwen-3-8-27b" and "Tu es Claude Code." in corps_recus[0]["systemPrompt"]


def test_messages_resultat_d_outil_rejoue(pont):
    poster, reponses, corps_recus = pont
    reponses.append(["Le fichier contient 42."])
    st, rep = poster("/v1/messages", {"model": "qwen-3-8-27b", "max_tokens": 100, "tools": OUTILS_ANTHROPIC, "messages": [
        {"role": "user", "content": "lis /a"},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "...", "signature": "s"},
                                          {"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": "/a"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": [{"type": "text", "text": "42"}]},
                                     {"type": "text", "text": "et alors ?"}]}]}, entetes={"x-api-key": "cle"})
    assert st == 200 and rep["stop_reason"] == "end_turn" and rep["content"][0]["text"] == "Le fichier contient 42."
    prompt = corps_recus[0]["prompt"]
    assert '"name": "Read"' in prompt[1]["content"]
    assert prompt[2]["content"] == "Résultat de l'outil (Read, appel toolu_1) : 42"
    assert prompt[3]["content"].startswith("et alors ?")


def test_messages_flux_sequence_complete(pont):
    poster, reponses, _ = pont
    reponses.append(["Je lis.\n", '{"tool_calls":[{"name":"Read","arguments":{"file_path":"/a"}}]}'])
    st, brut = poster("/v1/messages", {"model": "qwen-3-8-27b", "max_tokens": 100, "stream": True, "tools": OUTILS_ANTHROPIC,
                                       "messages": [{"role": "user", "content": "lis"}]},
                      entetes={"x-api-key": "cle"}, brut=True)
    ev = _sse(brut)
    noms = [n for n, _ in ev]
    assert st == 200 and noms[0] == "message_start" and noms[-2:] == ["message_delta", "message_stop"]
    assert all(n == d["type"] for n, d in ev)
    textes = "".join(d["delta"]["text"] for n, d in ev if n == "content_block_delta" and d["delta"]["type"] == "text_delta")
    json_outil = "".join(d["delta"]["partial_json"] for n, d in ev if n == "content_block_delta" and d["delta"]["type"] == "input_json_delta")
    debuts = [d["content_block"] for n, d in ev if n == "content_block_start"]
    assert textes == "Je lis.\n" and json.loads(json_outil) == {"file_path": "/a"}
    assert [b["type"] for b in debuts] == ["text", "tool_use"] and debuts[1]["name"] == "Read"
    assert ev[-2][1]["delta"]["stop_reason"] == "tool_use"
    assert noms.count("content_block_start") == noms.count("content_block_stop") == 2


def test_messages_erreurs_au_format_anthropic(pont):
    poster, *_ = pont
    st, rep = poster("/v1/messages", {"model": "zai-org-glm-5-2", "max_tokens": 10,
                                      "messages": [{"role": "user", "content": "x"}]}, entetes={"x-api-key": "cle"})
    assert st == 403 and rep["type"] == "error" and rep["error"]["type"] == "permission_error"
    st, rep = poster("/v1/messages", {"model": "qwen-3-8-27b", "messages": []}, entetes={"x-api-key": "faux"})
    assert st == 401 and rep["error"]["type"] == "authentication_error"


def test_count_tokens(pont):
    poster, *_ = pont
    st, rep = poster("/v1/messages/count_tokens", {"model": "x", "messages": [{"role": "user", "content": "a" * 400}]},
                     entetes={"x-api-key": "cle"})
    assert st == 200 and 100 <= rep["input_tokens"] <= 140


# --- /v1/responses (Codex CLI) ------------------------------------------------------------------------------------

OUTILS_CODEX = [
    {"type": "function", "name": "shell", "description": "Lance une commande",
     "parameters": {"type": "object", "properties": {"command": {"type": "array", "items": {"type": "string"}}}}},
    {"type": "custom", "name": "apply_patch", "description": "Applique un patch",
     "format": {"type": "grammar", "syntax": "lark", "definition": "start: begin_patch"}},
    {"type": "web_search"},
]


def test_responses_function_call_et_historique(pont):
    poster, reponses, corps_recus = pont
    reponses.append(['{"tool_calls":[{"name":"shell","arguments":{"command":["ls"]}}]}'])
    st, rep = poster("/v1/responses", {"model": "qwen-3-8-27b", "instructions": "Tu es Codex.", "tools": OUTILS_CODEX, "input": [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "liste"}]}]})
    assert st == 200 and rep["object"] == "response" and rep["status"] == "completed"
    item = rep["output"][0]
    assert item["type"] == "function_call" and item["name"] == "shell" and json.loads(item["arguments"]) == {"command": ["ls"]}
    assert item["call_id"]
    assert "Tu es Codex." in corps_recus[0]["systemPrompt"] and "apply_patch" in corps_recus[0]["systemPrompt"]
    assert "web_search" not in corps_recus[0]["systemPrompt"]
    # tour suivant : sortie de l'outil
    reponses.append(["Deux fichiers."])
    st, rep2 = poster("/v1/responses", {"model": "qwen-3-8-27b", "tools": OUTILS_CODEX, "input": [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "liste"}]},
        {"type": "reasoning", "summary": []},
        item,
        {"type": "function_call_output", "call_id": item["call_id"], "output": "a\nb"}]})
    assert rep2["output"][0]["type"] == "message" and rep2["output"][0]["content"][0]["text"] == "Deux fichiers."
    assert "a\nb" in corps_recus[1]["prompt"][2]["content"] and "shell" in corps_recus[1]["prompt"][2]["content"]


def test_responses_outil_custom_apply_patch(pont):
    poster, reponses, _ = pont
    patch = "*** Begin Patch\n*** Add File: a.txt\n+salut\n*** End Patch"
    reponses.append([json.dumps({"tool_calls": [{"name": "apply_patch", "arguments": {"input": patch}}]})])
    st, rep = poster("/v1/responses", {"model": "qwen-3-8-27b", "tools": OUTILS_CODEX, "input": "crée a.txt"})
    item = rep["output"][0]
    assert st == 200 and item["type"] == "custom_tool_call" and item["input"] == patch


def test_responses_flux_et_previous_response_id(pont):
    poster, reponses, corps_recus = pont
    reponses.append(["Bon", "jour"])
    st, brut = poster("/v1/responses", {"model": "qwen-3-8-27b", "input": "salut", "stream": True}, brut=True)
    ev = _sse(brut)
    noms = [n for n, _ in ev]
    assert st == 200 and noms[0] == "response.created" and noms[-1] == "response.completed"
    assert "".join(d["delta"] for n, d in ev if n == "response.output_text.delta") == "Bonjour"
    assert [d["sequence_number"] for _, d in ev] == list(range(1, len(ev) + 1))
    final = ev[-1][1]["response"]
    assert final["output"][0]["content"][0]["text"] == "Bonjour"
    reponses.append(["Re."])
    st, rep = poster("/v1/responses", {"model": "qwen-3-8-27b", "input": "encore", "previous_response_id": final["id"]})
    assert st == 200 and [m["content"][:7] for m in corps_recus[1]["prompt"]] == ["salut", "Bonjour", "encore"]
    st, rep = poster("/v1/responses", {"model": "qwen-3-8-27b", "input": "x", "previous_response_id": "resp_inconnu"})
    assert st == 400 and rep["error"]["code"] == "previous_response_not_found"


def test_responses_flux_appel_de_fonction(pont):
    poster, reponses, _ = pont
    reponses.append(['{"tool_calls":[{"name":"shell","arguments":{"command":["ls"]}}]}'])
    st, brut = poster("/v1/responses", {"model": "qwen-3-8-27b", "input": "ls", "tools": OUTILS_CODEX, "stream": True}, brut=True)
    ev = _sse(brut)
    fait = [d["item"] for n, d in ev if n == "response.output_item.done"]
    assert fait[0]["type"] == "function_call" and json.loads(fait[0]["arguments"]) == {"command": ["ls"]}
    assert "response.function_call_arguments.done" in [n for n, _ in ev]


# --- traductions pures --------------------------------------------------------------------------------------------

def test_anthropic_tool_choice_et_parallele():
    req = formats.requete_depuis_anthropic({"model": "m", "messages": [], "tools": OUTILS_ANTHROPIC,
                                            "tool_choice": {"type": "tool", "name": "Read", "disable_parallel_tool_use": True}})
    assert req["tool_choice"] == {"type": "function", "function": {"name": "Read"}} and req["parallel_tool_calls"] is False
    assert formats.requete_depuis_anthropic({"model": "m", "messages": [], "tools": OUTILS_ANTHROPIC,
                                             "tool_choice": {"type": "any"}})["tool_choice"] == "required"


def test_anthropic_image_et_erreur_d_outil():
    req = formats.requete_depuis_anthropic({"model": "m", "messages": [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "is_error": True, "content": "échec"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
        {"type": "text", "text": "vois"}]}]})
    assert req["messages"][0] == {"role": "tool", "tool_call_id": "t", "content": "[erreur] échec"}
    assert req["messages"][1]["content"][0]["image_url"]["url"] == "data:image/png;base64,QUJD"


def test_responses_local_shell_aller_retour():
    req, genres = formats.requete_depuis_responses({"model": "m", "input": "x", "tools": [{"type": "local_shell"}]})
    assert genres == {"local_shell": "local_shell"} and req["tools"][0]["function"]["name"] == "local_shell"
    item = formats._item_appel({"id": "c", "function": {"name": "local_shell", "arguments": '{"command":["ls","-a"]}'}}, genres)
    assert item["type"] == "local_shell_call" and item["action"]["command"] == ["ls", "-a"]


# --- API officielle (serveur factice) -----------------------------------------------------------------------------

class _ApiFactice(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    recus = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        corps = json.dumps({"data": [
            {"id": "outils", "model_spec": {"capabilities": {"supportsFunctionCalling": True}, "availableContextTokens": 131072}},
            {"id": "sans-outils", "model_spec": {"capabilities": {"supportsFunctionCalling": False}}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _ApiFactice.recus.append((self.headers.get("Authorization"), req))
        if req["model"] == "outils":
            appel = {"id": "call_x", "type": "function", "function": {"name": "bash", "arguments": '{"command":"ls"}'}}
            if req.get("stream"):
                morceaux = [{"choices": [{"index": 0, "delta": {"content": "Je liste."}}]},
                            {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_x", "function": {"name": "bash", "arguments": ""}}]}}]},
                            {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"command":'}}]}}]},
                            {"choices": [{"index": 0, "finish_reason": "tool_calls",
                                          "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"ls"}'}}]}}]},
                            {"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55}}]
                return self._flux(morceaux)
            return self._json({"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [appel]},
                                            "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12}})
        texte = '{"tool_calls":[{"name":"bash","arguments":{"command":"pwd"}}]}'
        return self._flux([{"choices": [{"index": 0, "delta": {"content": texte}}]},
                           {"choices": [], "usage": {"total_tokens": 77}}])

    def _json(self, obj):
        corps = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _flux(self, morceaux):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for m in morceaux:
            self.wfile.write(b"data: " + json.dumps(m).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.close_connection = True


@pytest.fixture
def api():
    _ApiFactice.recus = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _ApiFactice)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield vp.ApiVenice("cle-api", url=f"http://127.0.0.1:{srv.server_address[1]}/api/v1")
    srv.shutdown()


def _pont_api(api_client, api_seule=False):
    srv = vp.ServeurPont(("127.0.0.1", 0), vp.fabriquer_handler(vp.JetonAbsent() if api_seule else _Jeton(), "cle",
                                                                api=api_client, api_seule=api_seule))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def poster(chemin, corps):
        req = urllib.request.Request(base + chemin, data=json.dumps(corps).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer cle"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                d = r.read().decode()
                return r.status, (json.loads(d) if not corps.get("stream") else d)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def lire(chemin):
        req = urllib.request.Request(base + chemin, headers={"Authorization": "Bearer cle"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    return srv, poster, lire


def test_api_outils_natifs_sans_emulation(api):
    srv, poster, _ = _pont_api(api)
    try:
        st, rep = poster("/v1/chat/completions", {"model": "api/outils", "tools": OUTILS, "tool_choice": "auto",
                                                 "messages": [{"role": "user", "content": "ls"}]})
        assert st == 200 and rep["choices"][0]["finish_reason"] == "tool_calls"
        assert rep["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "bash"
        cle, envoye = _ApiFactice.recus[-1]
        assert cle == "Bearer cle-api" and envoye["model"] == "outils" and envoye["tools"] == OUTILS
        assert envoye["venice_parameters"] == {"include_venice_system_prompt": False}
        assert "tool_calls" not in json.dumps(envoye["messages"])  # rien d'émulé dans le prompt
    finally:
        srv.shutdown()


def test_api_flux_natif_traduit_en_anthropic(api):
    srv, poster, _ = _pont_api(api)
    try:
        st, brut = poster("/v1/messages", {"model": "api/outils", "max_tokens": 50, "stream": True,
                                           "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
                                           "messages": [{"role": "user", "content": "ls"}]})
        ev = _sse(brut)
        assert st == 200 and ev[-2][1]["delta"]["stop_reason"] == "tool_use"
        blocs = [d["content_block"] for n, d in ev if n == "content_block_start"]
        assert [b["type"] for b in blocs] == ["text", "tool_use"]
        assert ev[-2][1]["usage"]["output_tokens"] == 5
    finally:
        srv.shutdown()


def test_api_modele_sans_tool_calling_passe_par_l_emulation(api):
    srv, poster, _ = _pont_api(api)
    try:
        st, rep = poster("/v1/chat/completions", {"model": "api/sans-outils", "tools": OUTILS,
                                                 "messages": [{"role": "user", "content": "où ?"}]})
        assert st == 200 and json.loads(rep["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]) == {"command": "pwd"}
        envoye = _ApiFactice.recus[-1][1]
        assert "tools" not in envoye and "bash" in envoye["messages"][0]["content"]
        assert rep["usage"]["total_tokens"] == 77
    finally:
        srv.shutdown()


def test_api_seule_prefixe_et_liste(api):
    srv, poster, lire = _pont_api(api, api_seule=True)
    try:
        st, rep = poster("/v1/chat/completions", {"model": "outils", "messages": [{"role": "user", "content": "x"}]})
        assert st == 200 and _ApiFactice.recus[-1][1]["model"] == "outils"
        ids = [m["id"] for m in lire("/v1/models")["data"]]
        assert ids == ["api/outils", "api/sans-outils"]
    finally:
        srv.shutdown()


def test_modele_api_sans_cle_refuse(pont):
    poster, *_ = pont
    st, rep = poster("/v1/chat/completions", {"model": "api/outils", "messages": [{"role": "user", "content": "x"}]})
    assert st == 400 and rep["error"]["code"] == "api_non_configuree"
