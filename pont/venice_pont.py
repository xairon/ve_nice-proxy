"""Pont OpenAI -> Venice (chemin web) pour OmniRoute.

Le jeton Clerk (60 s) est miné depuis le cookie __client ; api.venice.ai le refuse (401),
outerface.venice.ai l'accepte. Les outils sont émulés : définitions dans le prompt système,
réponse JSON {"tool_calls": [...]} retransformée en tool_calls OpenAI.
"""
import base64
import hmac
import json
import math
import os
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLERK = "https://clerk.venice.ai/v1"
CLERK_VERSION = {"__clerk_api_version": "2025-04-10"}
OUTERFACE = "https://outerface.venice.ai/api/inference/chat"
AGENTS = "https://outerface.venice.ai/api/inference/chat/agents/venice"
SESSION = "https://venice.ai/api/user/session"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
EN_TETES_WEB = {"User-Agent": UA, "Origin": "https://venice.ai", "Referer": "https://venice.ai/"}


class CookieExpire(Exception):
    """Le cookie __client n'ouvre plus de session : reconnexion nécessaire sur venice.ai."""


class JetonClerk:
    def __init__(self, mint, marge=15):
        self._mint, self._marge = mint, marge
        self._jeton, self._exp, self._cookie_ok = None, 0.0, None
        self._verrou = threading.Lock()

    def obtenir(self):
        with self._verrou:
            if self._jeton and time.time() < self._exp - self._marge:
                return self._jeton
            try:
                self._jeton, self._exp = self._mint()
            except CookieExpire:
                self._jeton, self._cookie_ok = None, False
                raise
            self._cookie_ok = True
            return self._jeton

    def invalider(self):
        with self._verrou:
            self._jeton, self._exp = None, 0.0

    def etat(self):
        return {"cookie_ok": self._cookie_ok, "jeton_valide_jusqu_a": self._exp}


def _nouveau_cookie(reponse):
    """Valeur d'un Set-Cookie __client, None si Clerk ne fait pas tourner le cookie (cas mesuré le 28/10/2026)."""
    for brut in reponse.raw.headers.get_all("Set-Cookie") or []:
        nom, _, reste = brut.partition("=")
        if nom.strip() == "__client":
            return reste.split(";")[0]
    return None


def _session_web(cookie):
    import requests
    s = requests.Session()
    s.headers.update(EN_TETES_WEB)
    s.cookies.set("__client", cookie, domain="clerk.venice.ai")
    return s


class SourceClerk:
    """Cookie __client + appels Clerk. Écrit atomiquement une valeur renvoyée par Clerk (verrou), sans redémarrage."""

    SEUIL_JOURS = 30

    def __init__(self, cookie, fichier_env, session_factory=None):
        self.cookie, self._fichier = cookie, fichier_env
        self._fabrique = session_factory
        self._verrou = threading.Lock()
        self._meta = {"cookie_cree_le": None, "cookie_expire_le": None, "session_expire_le": None,
                      "dernier_renouvellement": None, "derniere_touche": None}

    def _session(self):
        return self._fabrique() if self._fabrique else _session_web(self.cookie)

    def _verifier(self, r, quoi):
        if r.status_code in (401, 403, 404):
            raise CookieExpire(f"{quoi} {r.status_code}")
        r.raise_for_status()

    def _client(self, s):
        r = s.get(f"{CLERK}/client", params=CLERK_VERSION, timeout=30)
        self._verifier(r, "client")
        self._noter_cookie(r)
        rep = r.json().get("response") or {}
        sid = rep.get("last_active_session_id")
        if not sid:
            raise CookieExpire("aucune session active")
        self._meta["cookie_cree_le"] = (rep.get("created_at") or 0) / 1000 or None
        self._meta["cookie_expire_le"] = (rep.get("cookie_expires_at") or 0) / 1000 or None
        for ses in rep.get("sessions") or []:
            if ses.get("id") == sid and ses.get("expire_at"):
                self._meta["session_expire_le"] = ses["expire_at"] / 1000
        return sid

    def _noter_cookie(self, reponse):
        nouveau = _nouveau_cookie(reponse)
        if not nouveau:
            return
        with self._verrou:
            if nouveau == self.cookie:
                return
            self.cookie = nouveau
            self._ecrire_fichier(nouveau)
            self._meta["dernier_renouvellement"] = time.time()

    def _ecrire_fichier(self, valeur):
        import tempfile
        chemin = os.path.expanduser(self._fichier)
        lignes = open(chemin).read().splitlines()
        sortie, vu = [], False
        for ligne in lignes:
            if ligne.startswith("VENICE_CLERK_CLIENT="):
                if not vu:
                    sortie.append("VENICE_CLERK_CLIENT=" + valeur)
                vu = True
            else:
                sortie.append(ligne)
        if not vu:
            sortie.append("VENICE_CLERK_CLIENT=" + valeur)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(chemin), suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(sortie) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, chemin)

    def mint(self):
        s = self._session()
        sid = self._client(s)
        r = s.post(f"{CLERK}/client/sessions/{sid}/tokens", params=CLERK_VERSION, timeout=30)
        self._verifier(r, "jeton")
        self._noter_cookie(r)
        jwt = r.json()["jwt"]
        p = jwt.split(".")[1]
        return jwt, float(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["exp"])

    def toucher(self):
        s = self._session()
        sid = self._client(s)
        r = s.post(f"{CLERK}/client/sessions/{sid}/touch", params=CLERK_VERSION, timeout=30)
        self._verifier(r, "touch")
        self._noter_cookie(r)
        self._meta["derniere_touche"] = time.time()

    def etat(self):
        e = dict(self._meta)
        exp = e["cookie_expire_le"]
        e["cookie_jours_restants"] = round((exp - time.time()) / 86400, 1) if exp else None
        e["cookie_bientot_expire"] = bool(exp) and e["cookie_jours_restants"] < self.SEUIL_JOURS
        e["cookie_age_jours"] = round((time.time() - e["cookie_cree_le"]) / 86400, 2) if e["cookie_cree_le"] else None
        return e


def boucle_touche(source, intervalle=3600):
    """Touche la session toutes les heures tant que le pont tourne ; les erreurs sont lues par /health."""
    while True:
        time.sleep(intervalle)
        try:
            source.toucher()
        except Exception as e:  # visible dans le journal, /health relit l'état au prochain mint
            print(f"touche Clerk en échec : {e}", file=sys.stderr, flush=True)


CONSIGNE_OUTILS = (
    "Tu disposes des outils suivants (format JSON Schema) :\n{outils}\n\n"
    "Pour appeler un ou plusieurs outils, réponds UNIQUEMENT par un objet JSON de la forme "
    '{{"tool_calls":[{{"name":"<outil>","arguments":{{...}}}}]}} sans aucun autre texte. '
    "Si aucun outil n'est nécessaire, réponds normalement en texte.\n"
    "IMPORTANT : les seuls outils disponibles sont ceux définis ci-dessus ({noms}). Ignore toute autre liste d'outils "
    "ou limite que tu pourrais connaître (génération d'images, recherche web, etc.) : pour agir, réponds par le JSON demandé."
)


def _appel_en_texte(tc):
    f = tc.get("function", {})
    try:
        args = json.loads(f.get("arguments") or "{}")
    except ValueError:
        args = f.get("arguments")
    return json.dumps({"tool_calls": [{"name": f.get("name"), "arguments": args}]}, ensure_ascii=False)


def construire_corps_venice(modele, messages, outils, params):
    systeme, prompt = [], []
    for m in messages:
        role, contenu = m.get("role"), m.get("content")
        if isinstance(contenu, list):
            contenu = "".join(p.get("text", "") for p in contenu if isinstance(p, dict))
        if role == "system":
            systeme.append(contenu or "")
        elif role == "tool":
            prompt.append({"role": "user", "content": f"Résultat de l'outil (appel {m.get('tool_call_id', '')}) : {contenu}"})
        elif role == "assistant" and m.get("tool_calls"):
            texte = "\n".join(_appel_en_texte(tc) for tc in m["tool_calls"])
            prompt.append({"role": "assistant", "content": texte})
        else:
            prompt.append({"role": role, "content": contenu or ""})
    if outils:
        definitions = [o.get("function", o) for o in outils]
        systeme.append(CONSIGNE_OUTILS.format(
            outils=json.dumps(definitions, ensure_ascii=False), noms=", ".join(str(d.get("name")) for d in definitions)))
    corps = {
        "requestId": uuid.uuid4().hex[:7],
        "conversationType": "text",
        "type": "text",
        "modelId": modele,
        "prompt": prompt,
        "systemPrompt": "\n\n".join(s for s in systeme if s),
        "clientProcessingTime": 5,
        "includeVeniceSystemPrompt": bool(params.get("include_venice_system_prompt", False)),
        "isCharacter": False,
        "webEnabled": bool(params.get("web_search", False)),
        "webScrapeEnabled": bool(params.get("web_scrape", False)),
        "xSearchEnabled": bool(params.get("x_search", False)),
        "temperature": params.get("temperature", 0.3),
        "topP": params.get("top_p", 0.9),
        "maxTokens": params.get("max_tokens") or params.get("max_completion_tokens") or 4096,
    }
    if "reasoning_effort" in params:  # « none » coupe la réflexion (champ web `reasoning`)
        corps["reasoning"] = params["reasoning_effort"] != "none"
    return corps


_PENSEE = re.compile(r"<think>.*?</think>", re.S)
_CLOTURE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def extraire_appels(texte, outils):
    """(contenu, tool_calls) : tool_calls non None si le texte est un appel d'outil valide."""
    if not outils or not texte:
        return texte, None
    noms = {o.get("function", o).get("name") for o in outils}
    brut = _PENSEE.sub("", texte).strip()
    m = _CLOTURE.match(brut)
    if m:
        brut = m.group(1)
    try:
        obj, _fin = json.JSONDecoder().raw_decode(brut)  # un modèle peut enchaîner du texte après l'appel
    except ValueError:
        return texte, None
    liste = obj.get("tool_calls") if isinstance(obj, dict) else None
    if not liste or not all(isinstance(t, dict) and t.get("name") in noms for t in liste):
        return texte, None
    appels = []
    for t in liste:
        args = t.get("arguments", {})
        appels.append({
            "id": "call_" + uuid.uuid4().hex[:24],
            "type": "function",
            "function": {"name": t["name"], "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)},
        })
    return None, appels


def morceaux_contenu(lignes):
    for ligne in lignes:
        if not ligne:
            continue
        try:
            o = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(o, dict) and o.get("kind") == "content" and "content" in o:
            yield o["content"]


def reponse_openai(modele, contenu, appels, jetons=0):
    msg = {"role": "assistant", "content": contenu}
    if appels:
        msg["tool_calls"] = appels
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:24], "object": "chat.completion",
        "created": int(time.time()), "model": modele,
        "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if appels else "stop"}],
        "usage": {"prompt_tokens": jetons, "completion_tokens": 0, "total_tokens": jetons},
    }


def morceaux_sse(rep):
    """Chunks `chat.completion.chunk` d'une réponse complète. Appel d'outil en forme canonique OpenAI :
    id et nom avec arguments vides, puis les arguments seuls, puis la fin (un client qui concatène les
    arguments ne les voit qu'une fois)."""
    ch = rep["choices"][0]
    base = {"id": rep["id"], "object": "chat.completion.chunk", "created": rep["created"], "model": rep["model"]}

    def morceau(delta, fin=None):
        return {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}

    appels = ch["message"].get("tool_calls")
    if not appels:
        return [morceau({"role": "assistant", "content": ch["message"]["content"] or ""}),
                morceau({}, ch["finish_reason"])]
    entetes = [{"index": i, "id": tc["id"], "type": tc["type"],
                "function": {"name": tc["function"]["name"], "arguments": ""}} for i, tc in enumerate(appels)]
    args = [{"index": i, "function": {"arguments": tc["function"]["arguments"]}} for i, tc in enumerate(appels)]
    return [morceau({"role": "assistant", "tool_calls": entetes}), morceau({"tool_calls": args}),
            morceau({}, ch["finish_reason"])]


def cle_valide(entete, cle):
    if not cle or not entete or not entete.startswith("Bearer "):
        return False
    return hmac.compare_digest(entete[7:], cle)


def lire_env(chemin):
    out = {}
    for ligne in open(os.path.expanduser(chemin)):
        if "=" in ligne and not ligne.lstrip().startswith("#"):
            k, v = ligne.strip().split("=", 1)
            out[k] = v
    return out


def discuter(jeton, corps):
    """Itérateur de lignes NDJSON ; rejoue une fois avec un jeton neuf sur 401."""
    import requests
    for essai in (1, 2):
        r = requests.post(OUTERFACE, json=corps, stream=True, timeout=(15, 180), headers={
            **EN_TETES_WEB, "Referer": "https://venice.ai/chat", "Authorization": "Bearer " + jeton.obtenir()})
        if r.status_code == 401 and essai == 1:
            jeton.invalider()
            r.close()
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Venice {r.status_code}: {r.text[:200]}")
        r.encoding = "utf-8"  # Venice répond text/html sans charset : requests supposerait ISO-8859-1
        return r.iter_lines(decode_unicode=True)


MODELES_AGENT = set(filter(None, os.environ.get(
    "VENICE_PONT_AGENTS", "deepseek-v4-1-flash-uncensored,kimi-k2-5").split(",")))


def est_agent(modele):
    """Modèles servis seulement par la route « agents » (absents du chat classique)."""
    return modele in MODELES_AGENT


def _item_agent(role, texte):
    return {"type": "message", "role": role, "id": uuid.uuid4().hex[:11], "status": "completed",
            "content": [{"type": "output_text", "text": texte, "annotations": []}]}


def messages_agent(corps):
    """Corps du chat classique -> messages de la route agents (le système devient un 1er message utilisateur)."""
    msgs = []
    if corps.get("systemPrompt"):
        msgs.append(_item_agent("user", "[System]\n" + corps["systemPrompt"]))
    for m in corps["prompt"]:
        msgs.append(_item_agent(m["role"], m["content"]))
    return msgs


def lire_flux_agent(lignes):
    """Flux SSE de la route agents -> (texte, jetons totaux du contexte, système imposé par Venice compris)."""
    evenement, texte, jetons = None, [], 0
    for ligne in lignes:
        if ligne.startswith("event:"):
            evenement = ligne[6:].strip()
        elif ligne.startswith("data:"):
            try:
                d = json.loads(ligne[5:])
            except ValueError:
                continue
            if evenement == "response.output_text.delta":
                if str(d.get("item_id", "")).startswith("rs_"):  # raisonnement : pas dans la réponse
                    continue
                texte.append(d.get("delta", ""))
            elif evenement == "response.output_text.done":
                jetons = (d.get("context_metadata") or {}).get("total_tokens", jetons)
            elif evenement in ("response.failed", "response.error", "error"):
                err = (d.get("response") or d).get("error") or d
                raise RuntimeError(f"Venice agent: {json.dumps(err, ensure_ascii=False)[:200]}")
    return "".join(texte), jetons


def discuter_agent(jeton, modele, corps):
    """Appelle la route agents ; rejoue une fois avec un jeton neuf sur 401. Renvoie (texte, jetons)."""
    import requests
    for essai in (1, 2):
        r = requests.post(AGENTS, params={"agentModelId": modele}, stream=True, timeout=(15, 300),
                          json={"clientTools": [], "input": {"messages": messages_agent(corps)}},
                          headers={**EN_TETES_WEB, "Referer": "https://venice.ai/chat",
                                   "Accept": "text/event-stream", "x-venice-locale": "en",
                                   "Authorization": "Bearer " + jeton.obtenir()})
        if r.status_code == 401 and essai == 1:
            jeton.invalider()
            r.close()
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Venice {r.status_code}: {r.text[:200]}")
        r.encoding = "utf-8"
        return lire_flux_agent(r.iter_lines(decode_unicode=True))


# Modèles sans pièce = illimités avec Pro (relevé dans le sélecteur de venice.ai, banc du 28/10/2026 : 0 crédit débité).
# Tout autre modèle est refusé (403) sauf débit volontaire : `autoriser_debit: true` dans la requête, ou VENICE_PONT_AUTORISER_PAYANTS=1.
GRATUITS = set(filter(None, os.environ.get(
    "VENICE_PONT_GRATUITS",
    "qwen-3-8-27b,venice-uncensored-1-2,gemma4-uncensored,olafangensan-glm-4.7-flash-heretic,"
    "venice-uncensored-role-play,aion-labs-aion-3-0,deepseek-v4-1-flash-uncensored,kimi-k2-5").split(",")))
AUTORISER_PAYANTS = os.environ.get("VENICE_PONT_AUTORISER_PAYANTS") == "1"


def modele_autorise(modele, req):
    return AUTORISER_PAYANTS or modele in GRATUITS or req.get("autoriser_debit") is True


class LimiteurDebit:
    """Plafond de requêtes sur une fenêtre glissante : un agent en boucle ne doit pas donner au compte Pro un motif de robot."""

    def __init__(self, maximum, fenetre=60, horloge=time.time):
        self._max, self._fenetre, self._horloge = maximum, fenetre, horloge
        self._instants, self._verrou = [], threading.Lock()

    def essayer(self):
        """(True, 0) si la requête passe ; (False, secondes à attendre) sinon."""
        with self._verrou:
            maintenant = self._horloge()
            self._instants = [t for t in self._instants if maintenant - t < self._fenetre]
            if len(self._instants) >= self._max:
                return False, max(1, math.ceil(self._fenetre - (maintenant - self._instants[0])))
            self._instants.append(maintenant)
            return True, 0


def decoder_solde(jwt):
    """Solde total (`veniceCredits`) dans la charge utile du jeton de /api/user/session."""
    p = jwt.split(".")[1]
    return float(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["veniceCredits"])


def lire_solde(jeton):
    import requests
    r = requests.get(SESSION, timeout=30, headers={**EN_TETES_WEB, "Authorization": "Bearer " + jeton.obtenir()})
    r.raise_for_status()
    return decoder_solde(r.json()["token"])


class SuiviCredits:
    """Garde-fou crédits : alerte si le solde passe sous la référence (un modèle à pièce a débité).

    La référence monte avec une recharge (forfait mensuel) et se remet au solde courant sur acquittement. Elle survit
    à un redémarrage (fichier). `alerte` est lue par /health puis par une sonde externe."""

    SEUIL = 0.5

    def __init__(self, lecteur, fichier=None, horloge=time.time):
        self._lecteur, self._fichier, self._horloge = lecteur, fichier, horloge
        self._verrou = threading.Lock()
        self._e = {"courant": None, "reference": None, "lu_le": None, "erreur": None}
        try:
            self._e["reference"] = json.loads(open(fichier).read())["reference"] if fichier else None
        except (OSError, ValueError, KeyError):
            pass

    def _ecrire(self):
        if not self._fichier:
            return
        tmp = str(self._fichier) + ".tmp"
        with open(tmp, "w") as f:
            f.write(json.dumps({"reference": self._e["reference"]}))
        os.replace(tmp, self._fichier)

    def rafraichir(self):
        try:
            courant = self._lecteur()
        except Exception as e:  # une lecture ratée ne doit ni lever une fausse alerte ni arrêter le pont
            with self._verrou:
                self._e["erreur"] = str(e)[:200]
            return self.etat()
        with self._verrou:
            self._e.update(courant=courant, lu_le=self._horloge(), erreur=None)
            if self._e["reference"] is None or courant > self._e["reference"]:
                self._e["reference"] = courant
                self._ecrire()
        return self.etat()

    def acquitter(self):
        with self._verrou:
            if self._e["courant"] is not None:
                self._e["reference"] = self._e["courant"]
                self._ecrire()
        return self.etat()

    def etat(self):
        with self._verrou:
            e = dict(self._e)
        debit = (e["reference"] - e["courant"]) if e["reference"] is not None and e["courant"] is not None else 0
        return {**e, "debit": debit, "alerte": debit >= self.SEUIL}


def boucle_credits(suivi, intervalle=600):
    while True:
        suivi.rafraichir()
        time.sleep(intervalle)


def lister_modeles():
    """Les modèles sans pièce : le catalogue de l'API ne connaît pas les ids web (gemma4-uncensored) ni la route agents."""
    return [{"id": m, "object": "model", "owned_by": "venice-agent" if est_agent(m) else "venice"}
            for m in sorted(GRATUITS | MODELES_AGENT)]


def fabriquer_handler(jeton, cle_pont, source=None, limiteur=None, suivi=None):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _json(self, code, obj, entetes=None):
            data = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            for k, v in (entetes or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _autorise(self):
            if cle_valide(self.headers.get("Authorization"), cle_pont):
                return True
            self._json(401, {"error": {"message": "clé du pont invalide"}})
            return False

        def do_GET(self):
            if self.path == "/health":
                try:
                    jeton.obtenir()
                    return self._json(200, {"ok": True, **jeton.etat(), **(source.etat() if source else {}),
                                            **({"credits": suivi.etat()} if suivi else {})})
                except CookieExpire as e:
                    return self._json(503, {"ok": False, "raison": "cookie_expire", "detail": str(e)})
                except Exception as e:
                    return self._json(503, {"ok": False, "raison": "clerk_injoignable", "detail": str(e)[:200]})
            if not self._autorise():
                return
            if self.path in ("/v1/models", "/models"):
                try:
                    return self._json(200, {"object": "list", "data": lister_modeles()})
                except Exception as e:
                    return self._json(502, {"error": {"message": str(e)[:200]}})
            if self.path == "/credits" and suivi:
                return self._json(200, suivi.rafraichir())
            self._json(404, {"error": {"message": "inconnu"}})

        def do_POST(self):
            if not self._autorise():
                return
            if self.path == "/credits/acquitter" and suivi:
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                return self._json(200, suivi.acquitter())
            if self.path not in ("/v1/chat/completions", "/chat/completions"):
                return self._json(404, {"error": {"message": "inconnu"}})
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if not modele_autorise(req["model"], req):
                    return self._json(403, {"error": {
                        "code": "modele_payant_refuse", "message": f"{req['model']} n'est pas dans la liste des modèles sans pièce "
                        "(débit de crédits). Débit volontaire : autoriser_debit: true."}})
                if limiteur:
                    ok, attente = limiteur.essayer()
                    if not ok:
                        return self._json(429, {"error": {"code": "plafond_pont", "message": f"plafond du pont atteint, réessayer dans {attente} s"}},
                                          {"Retry-After": str(attente)})
                outils = req.get("tools") or None
                corps = construire_corps_venice(req["model"], req["messages"], outils, req)
                if est_agent(req["model"]):
                    texte, jetons = discuter_agent(jeton, req["model"], corps)
                else:
                    texte, jetons = "".join(morceaux_contenu(discuter(jeton, corps))), 0
            except CookieExpire as e:
                return self._json(503, {"error": {"message": "cookie Venice expiré", "detail": str(e)}})
            except Exception as e:
                return self._json(502, {"error": {"message": str(e)[:300]}})
            contenu, appels = extraire_appels(texte, outils)
            rep = reponse_openai(req["model"], contenu, appels, jetons)
            if not req.get("stream"):
                return self._json(200, rep)
            self._sse(rep)

        def _sse(self, rep):
            morceaux = morceaux_sse(rep)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "close")
            self.end_headers()
            for m in morceaux:
                self.wfile.write(b"data: " + json.dumps(m, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.close_connection = True

    return H


class ServeurPont(ThreadingHTTPServer):
    request_queue_size = 64  # 5 par défaut : des rafales de 8 à 16 requêtes se faisaient réinitialiser
    daemon_threads = True


def main():
    fichier = os.environ.get("VENICE_PONT_ENV", "~/.config/venice-setup/defaut/venice.env")
    env = lire_env(fichier)
    source = SourceClerk(env["VENICE_CLERK_CLIENT"], fichier)
    jeton = JetonClerk(source.mint)
    hote, port = os.environ.get("VENICE_PONT_ECOUTE", "127.0.0.1:8700").split(":")
    limiteur = LimiteurDebit(int(os.environ.get("VENICE_PONT_MAX_PAR_MIN", "20")))
    suivi = SuiviCredits(lambda: lire_solde(jeton), fichier=os.path.expanduser(
        os.environ.get("VENICE_PONT_CREDITS", "~/.config/venice-setup/defaut/credits.json")))
    srv = ServeurPont((hote, int(port)), fabriquer_handler(jeton, env["VENICE_PONT_CLE"], source, limiteur, suivi))
    threading.Thread(target=boucle_touche, args=(source,), daemon=True).start()
    threading.Thread(target=boucle_credits, args=(suivi,), daemon=True).start()
    print(f"venice-pont à l'écoute sur {hote}:{port}", file=sys.stderr, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
