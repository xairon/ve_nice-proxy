"""Traduction des formats Anthropic (Messages) et OpenAI (Responses) vers et depuis chat completions.

Module pur (bibliothèque standard, aucun appel réseau) : le pont traduit la requête en chat completions, la fait
passer par son cœur commun (outils émulés ou natifs), puis retraduit les événements produits dans le format du
client. C'est ce qui permet à Claude Code (/v1/messages) et à Codex CLI (/v1/responses) de parler au pont sans
passerelle intermédiaire.
"""
import json
import threading
import time
import uuid
from collections import OrderedDict


def _ident(prefixe):
    return prefixe + uuid.uuid4().hex[:24]


def _jetons(texte):
    return max(1, (len(texte) + 3) // 4) if texte else 0


def _json_args(arguments):
    """Arguments OpenAI (chaîne JSON) -> objet ; une chaîne illisible devient {"input": chaîne}."""
    if isinstance(arguments, dict):
        return arguments
    try:
        valeur = json.loads(arguments or "{}")
    except ValueError:
        return {"input": arguments}
    return valeur if isinstance(valeur, dict) else {"input": valeur}


# === Anthropic : /v1/messages =========================================================================================

def _texte_blocs(contenu):
    """Contenu Anthropic (chaîne ou liste de blocs) -> texte seul (résultats d'outil, système)."""
    if isinstance(contenu, str):
        return contenu
    morceaux = []
    for b in contenu or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            morceaux.append(b.get("text", ""))
        elif b.get("type") == "image":
            morceaux.append("[image]")
        elif b.get("type") == "tool_result":  # imbriqué : rare, mais on n'en perd pas le texte
            morceaux.append(_texte_blocs(b.get("content")))
    return "\n".join(m for m in morceaux if m)


def _image_anthropic(bloc):
    source = bloc.get("source") or {}
    if source.get("type") == "base64":
        return {"type": "image_url", "image_url": {"url": f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"}}
    if source.get("type") == "url":
        return {"type": "image_url", "image_url": {"url": source.get("url", "")}}
    return None


def _document_anthropic(bloc):
    source = bloc.get("source") or {}
    nom = bloc.get("title") or "document"
    if source.get("type") == "base64":
        return {"type": "file", "file": {"filename": nom + (".pdf" if "pdf" in source.get("media_type", "") else ""),
                                         "file_data": f"data:{source.get('media_type', 'application/pdf')};base64,{source.get('data', '')}"}}
    if source.get("type") == "text":
        return {"type": "text", "text": f"[Document {nom}]\n{source.get('data', '')}"}
    return None


def requete_depuis_anthropic(a):
    """Requête Messages d'Anthropic -> requête chat completions (format OpenAI)."""
    messages = []
    systeme = a.get("system")
    if systeme:
        messages.append({"role": "system", "content": _texte_blocs(systeme)})
    for m in a.get("messages") or []:
        role, contenu = m.get("role"), m.get("content")
        if isinstance(contenu, str):
            messages.append({"role": role, "content": contenu})
            continue
        if role == "assistant":
            textes, appels = [], []
            for b in contenu or []:
                if b.get("type") == "text":
                    textes.append(b.get("text", ""))
                elif b.get("type") in ("tool_use", "server_tool_use"):
                    appels.append({"id": b.get("id") or _ident("toolu_"), "type": "function",
                                   "function": {"name": b.get("name"), "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}})
                # thinking / redacted_thinking : non rejoués (signature propre à Anthropic)
            msg = {"role": "assistant", "content": "".join(textes) or None}
            if appels:
                msg["tool_calls"] = appels
            messages.append(msg)
            continue
        parties, resultats = [], []
        for b in contenu or []:
            genre = b.get("type")
            if genre == "tool_result":
                texte = _texte_blocs(b.get("content"))
                if b.get("is_error"):
                    texte = "[erreur] " + texte
                resultats.append({"role": "tool", "tool_call_id": b.get("tool_use_id", ""), "content": texte})
                images = [_image_anthropic(x) for x in b.get("content") or [] if isinstance(x, dict) and x.get("type") == "image"]
                parties.extend(i for i in images if i)
            elif genre == "text":
                parties.append({"type": "text", "text": b.get("text", "")})
            elif genre == "image":
                image = _image_anthropic(b)
                if image:
                    parties.append(image)
            elif genre == "document":
                doc = _document_anthropic(b)
                if doc:
                    parties.append(doc)
        messages.extend(resultats)  # les résultats d'outil suivent directement l'appel de l'assistant
        if parties:
            if all(p["type"] == "text" for p in parties):
                messages.append({"role": role, "content": "".join(p["text"] for p in parties)})
            else:
                messages.append({"role": role, "content": parties})
    req = {"model": a.get("model"), "messages": messages, "stream": bool(a.get("stream"))}
    if a.get("max_tokens"):
        req["max_tokens"] = a["max_tokens"]
    for cle in ("temperature", "top_p"):
        if a.get(cle) is not None:
            req[cle] = a[cle]
    if a.get("stop_sequences"):
        req["stop"] = a["stop_sequences"]
    outils = [{"type": "function", "function": {"name": o["name"], "description": o.get("description", ""),
                                                "parameters": o.get("input_schema") or {"type": "object", "properties": {}}}}
              for o in a.get("tools") or [] if isinstance(o, dict) and o.get("name") and "input_schema" in o]
    if outils:
        req["tools"] = outils
        choix = a.get("tool_choice") or {}
        genre = choix.get("type")
        if genre == "any":
            req["tool_choice"] = "required"
        elif genre == "tool" and choix.get("name"):
            req["tool_choice"] = {"type": "function", "function": {"name": choix["name"]}}
        elif genre == "none":
            req["tool_choice"] = "none"
        if choix.get("disable_parallel_tool_use"):
            req["parallel_tool_calls"] = False
    if (a.get("thinking") or {}).get("type") == "disabled":
        req["reasoning_effort"] = "none"
    return req


def jetons_entree_anthropic(a):
    """Estimation des jetons d'entrée (route /v1/messages/count_tokens) : ~4 caractères par jeton."""
    texte = json.dumps({k: a.get(k) for k in ("system", "messages", "tools")}, ensure_ascii=False)
    return _jetons(texte)


RAISONS_ANTHROPIC = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}


def _bloc_outil(tc):
    f = tc.get("function") or {}
    ident = tc.get("id") or ""
    return {"type": "tool_use", "id": ident if ident.startswith("toolu_") else "toolu_" + (ident.removeprefix("call_") or uuid.uuid4().hex[:24]),
            "name": f.get("name"), "input": _json_args(f.get("arguments"))}


def reponse_anthropic(modele, contenu, appels, fin):
    blocs = ([{"type": "text", "text": contenu}] if contenu else []) + [_bloc_outil(tc) for tc in appels or []]
    usage = fin.get("usage") or {}
    return {"id": _ident("msg_"), "type": "message", "role": "assistant", "model": modele,
            "content": blocs or [{"type": "text", "text": ""}],
            "stop_reason": RAISONS_ANTHROPIC.get(fin.get("raison"), "end_turn"), "stop_sequence": None,
            "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0),
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}


def flux_anthropic(modele, evenements, entree_estimee=0):
    """Événements du cœur -> (nom, données) des événements SSE de l'API Messages."""
    ident = _ident("msg_")
    yield "message_start", {"type": "message_start", "message": {
        "id": ident, "type": "message", "role": "assistant", "model": modele, "content": [],
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": entree_estimee, "output_tokens": 1, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 0}}}
    index, texte_ouvert, fin = 0, False, {"raison": "stop", "usage": {}}
    for genre, valeur in evenements:
        if genre == "texte":
            if not texte_ouvert:
                yield "content_block_start", {"type": "content_block_start", "index": index,
                                              "content_block": {"type": "text", "text": ""}}
                texte_ouvert = True
            yield "content_block_delta", {"type": "content_block_delta", "index": index,
                                          "delta": {"type": "text_delta", "text": valeur}}
        elif genre == "appels":
            if texte_ouvert:
                yield "content_block_stop", {"type": "content_block_stop", "index": index}
                index, texte_ouvert = index + 1, False
            for tc in valeur:
                bloc = _bloc_outil(tc)
                yield "content_block_start", {"type": "content_block_start", "index": index,
                                              "content_block": {**bloc, "input": {}}}
                yield "content_block_delta", {"type": "content_block_delta", "index": index, "delta": {
                    "type": "input_json_delta", "partial_json": json.dumps(bloc["input"], ensure_ascii=False)}}
                yield "content_block_stop", {"type": "content_block_stop", "index": index}
                index += 1
        elif genre == "fin":
            fin = valeur
    if texte_ouvert:
        yield "content_block_stop", {"type": "content_block_stop", "index": index}
    usage = fin.get("usage") or {}
    yield "message_delta", {"type": "message_delta",
                            "delta": {"stop_reason": RAISONS_ANTHROPIC.get(fin.get("raison"), "end_turn"), "stop_sequence": None},
                            "usage": {"output_tokens": usage.get("completion_tokens", 0),
                                      "input_tokens": usage.get("prompt_tokens", entree_estimee)}}
    yield "message_stop", {"type": "message_stop"}


TYPES_ERREUR_ANTHROPIC = {400: "invalid_request_error", 401: "authentication_error", 402: "billing_error",
                          403: "permission_error", 404: "not_found_error", 413: "request_too_large",
                          429: "rate_limit_error", 503: "overloaded_error"}


def erreur_anthropic(statut, message):
    return {"type": "error", "error": {"type": TYPES_ERREUR_ANTHROPIC.get(statut, "api_error"), "message": message}}


# === OpenAI Responses : /v1/responses =================================================================================

def _parametres_custom(outil):
    """Outil `custom` (entrée libre, ex. apply_patch de Codex) -> schéma JSON d'une fonction à un seul champ `input`."""
    description = "Entrée brute de l'outil, en texte libre (pas du JSON)."
    fmt = outil.get("format") or {}
    if fmt.get("type") == "grammar" and fmt.get("definition"):
        description += f" Elle doit respecter cette grammaire ({fmt.get('syntax', 'lark')}) :\n{fmt['definition']}"
    return {"type": "object", "properties": {"input": {"type": "string", "description": description}}, "required": ["input"]}


PARAMETRES_SHELL = {"type": "object", "properties": {
    "command": {"type": "array", "items": {"type": "string"}, "description": "Commande et arguments, ex. [\"bash\", \"-lc\", \"ls\"]"},
    "workdir": {"type": "string"}, "timeout_ms": {"type": "integer"}}, "required": ["command"]}


def _contenu_responses(contenu):
    """Contenu d'un item message Responses -> contenu chat completions (chaîne ou liste de parties)."""
    if isinstance(contenu, str):
        return contenu
    parties = []
    for p in contenu or []:
        genre = p.get("type")
        if genre in ("input_text", "output_text", "text", "summary_text", "refusal"):
            parties.append({"type": "text", "text": p.get("text") or p.get("refusal") or ""})
        elif genre == "input_image":
            url = p.get("image_url") if isinstance(p.get("image_url"), str) else (p.get("image_url") or {}).get("url")
            if url:
                parties.append({"type": "image_url", "image_url": {"url": url}})
        elif genre == "input_file" and p.get("file_data"):
            parties.append({"type": "file", "file": {"filename": p.get("filename") or "fichier", "file_data": p["file_data"]}})
    if all(p["type"] == "text" for p in parties):
        return "".join(p["text"] for p in parties)
    return parties


def _sortie_outil(sortie):
    if isinstance(sortie, str):
        return sortie
    if isinstance(sortie, list):
        return "".join(p.get("text", "") for p in sortie if isinstance(p, dict))
    return json.dumps(sortie, ensure_ascii=False)


def messages_depuis_items(items):
    """Items d'entrée Responses -> messages chat completions (appels et résultats d'outil compris)."""
    messages = []

    def appel(call_id, nom, arguments):
        tc = {"id": call_id or _ident("call_"), "type": "function", "function": {"name": nom, "arguments": arguments}}
        if messages and messages[-1]["role"] == "assistant" and not messages[-1].get("_ferme"):
            messages[-1].setdefault("tool_calls", []).append(tc)
        else:
            messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})

    for it in items:
        if not isinstance(it, dict):
            continue
        genre = it.get("type") or ("message" if "role" in it else None)
        if genre == "message":
            role = it.get("role", "user")
            messages.append({"role": "system" if role == "developer" else role, "content": _contenu_responses(it.get("content"))})
        elif genre == "function_call":
            appel(it.get("call_id"), it.get("name"), it.get("arguments") or "{}")
        elif genre == "custom_tool_call":
            appel(it.get("call_id"), it.get("name"), json.dumps({"input": it.get("input", "")}, ensure_ascii=False))
        elif genre == "local_shell_call":
            action = it.get("action") or {}
            appel(it.get("call_id") or it.get("id"), "local_shell", json.dumps(
                {"command": action.get("command") or [], "workdir": action.get("working_directory")}, ensure_ascii=False))
        elif genre in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            if messages and messages[-1]["role"] == "assistant":
                messages[-1]["_ferme"] = True
            messages.append({"role": "tool", "tool_call_id": it.get("call_id") or it.get("id", ""),
                             "content": _sortie_outil(it.get("output"))})
        # reasoning, web_search_call, etc. : ignorés (le pont est sans état côté Venice)
    for m in messages:
        m.pop("_ferme", None)
    return messages


class ConversationsResponses:
    """Mémoire courte des réponses (previous_response_id) : Codex envoie souvent store=false et tout l'historique,
    mais d'autres clients enchaînent par identifiant. Bornée, en mémoire, perdue au redémarrage."""

    def __init__(self, maximum=200):
        self._d, self._max, self._verrou = OrderedDict(), maximum, threading.Lock()

    def garder(self, ident, messages):
        with self._verrou:
            self._d[ident] = messages
            self._d.move_to_end(ident)
            while len(self._d) > self._max:
                self._d.popitem(last=False)

    def lire(self, ident):
        with self._verrou:
            return list(self._d.get(ident) or []) if ident in self._d else None


def requete_depuis_responses(r, conversations=None):
    """Requête Responses -> (requête chat completions, genres des outils {nom: function|custom|local_shell}).
    KeyError('previous_response_id') si l'identifiant précédent est inconnu."""
    messages = []
    precedent = r.get("previous_response_id")
    if precedent:
        anciens = conversations.lire(precedent) if conversations else None
        if anciens is None:
            raise KeyError("previous_response_id")
        messages.extend(m for m in anciens if m.get("role") != "system")
    if r.get("instructions"):
        messages.insert(0, {"role": "system", "content": r["instructions"]})
    entree = r.get("input")
    if isinstance(entree, str):
        messages.append({"role": "user", "content": entree})
    elif isinstance(entree, list):
        messages.extend(messages_depuis_items(entree))
    outils, genres = [], {}
    for o in r.get("tools") or []:
        genre = o.get("type")
        if genre == "function" and o.get("name"):
            outils.append({"type": "function", "function": {"name": o["name"], "description": o.get("description", ""),
                                                            "parameters": o.get("parameters") or {"type": "object", "properties": {}}}})
            genres[o["name"]] = "function"
        elif genre == "custom" and o.get("name"):
            outils.append({"type": "function", "function": {"name": o["name"], "description": o.get("description", ""),
                                                            "parameters": _parametres_custom(o)}})
            genres[o["name"]] = "custom"
        elif genre == "local_shell":
            outils.append({"type": "function", "function": {"name": "local_shell", "description": "Lance une commande dans le shell local.",
                                                            "parameters": PARAMETRES_SHELL}})
            genres["local_shell"] = "local_shell"
        # web_search, file_search, computer_use… : outils hébergés par OpenAI, sans équivalent ici
    req = {"model": r.get("model"), "messages": messages, "stream": bool(r.get("stream"))}
    if outils:
        req["tools"] = outils
        choix = r.get("tool_choice")
        if choix in ("required", "none"):
            req["tool_choice"] = choix
        elif isinstance(choix, dict) and choix.get("name"):
            req["tool_choice"] = {"type": "function", "function": {"name": choix["name"]}}
        if r.get("parallel_tool_calls") is False:
            req["parallel_tool_calls"] = False
    if r.get("max_output_tokens"):
        req["max_tokens"] = r["max_output_tokens"]
    for cle in ("temperature", "top_p"):
        if r.get(cle) is not None:
            req[cle] = r[cle]
    if (r.get("reasoning") or {}).get("effort") in ("none", "minimal"):
        req["reasoning_effort"] = "none"
    return req, genres


def _item_appel(tc, genres):
    f = tc.get("function") or {}
    nom, call_id = f.get("name"), tc.get("id") or _ident("call_")
    genre = genres.get(nom, "function")
    if genre == "custom":
        args = _json_args(f.get("arguments"))
        entree = args.get("input") if isinstance(args.get("input"), str) else f.get("arguments", "")
        return {"type": "custom_tool_call", "id": _ident("ctc_"), "status": "completed", "call_id": call_id, "name": nom, "input": entree}
    if genre == "local_shell":
        args = _json_args(f.get("arguments"))
        commande = args.get("command")
        commande = commande if isinstance(commande, list) else ["bash", "-lc", str(commande or "")]
        action = {"type": "exec", "command": commande, "env": {}}
        if args.get("workdir"):
            action["working_directory"] = args["workdir"]
        if args.get("timeout_ms"):
            action["timeout_ms"] = args["timeout_ms"]
        return {"type": "local_shell_call", "id": _ident("lsh_"), "status": "completed", "call_id": call_id, "action": action}
    return {"type": "function_call", "id": _ident("fc_"), "status": "completed", "call_id": call_id, "name": nom,
            "arguments": f.get("arguments") or "{}"}


def _item_message(texte, ident=None, statut="completed"):
    return {"type": "message", "id": ident or _ident("msg_"), "status": statut, "role": "assistant",
            "content": [{"type": "output_text", "text": texte, "annotations": []}] if texte is not None else []}


def _usage_responses(usage):
    usage = usage or {}
    return {"input_tokens": usage.get("prompt_tokens", 0), "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": usage.get("completion_tokens", 0), "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": usage.get("total_tokens", 0)}


def objet_response(ident, modele, r, sortie, statut="completed", usage=None, cree=None):
    return {"id": ident, "object": "response", "created_at": cree or int(time.time()), "status": statut,
            "model": modele, "output": sortie, "error": None, "incomplete_details": None,
            "instructions": r.get("instructions"), "metadata": r.get("metadata") or {},
            "parallel_tool_calls": r.get("parallel_tool_calls", True), "previous_response_id": r.get("previous_response_id"),
            "reasoning": {"effort": (r.get("reasoning") or {}).get("effort"), "summary": None},
            "store": r.get("store", False), "temperature": r.get("temperature"), "text": {"format": {"type": "text"}},
            "tool_choice": r.get("tool_choice", "auto"), "tools": r.get("tools") or [], "top_p": r.get("top_p"),
            "truncation": "disabled", "usage": _usage_responses(usage) if usage is not None else None}


def reponse_responses(modele, r, contenu, appels, fin, genres, ident=None):
    sortie = ([_item_message(contenu)] if contenu else []) + [_item_appel(tc, genres) for tc in appels or []]
    return objet_response(ident or _ident("resp_"), modele, r, sortie, usage=fin.get("usage") or {})


def messages_assistant(contenu, appels):
    """Ce que l'assistant a répondu, en messages chat completions (pour previous_response_id)."""
    msg = {"role": "assistant", "content": contenu}
    if appels:
        msg["tool_calls"] = appels
    return [msg]


def flux_responses(modele, r, evenements, genres, ident=None, sortie_finale=None):
    """Événements du cœur -> (nom, données) des événements SSE de l'API Responses. `sortie_finale` (liste) reçoit
    le contenu et les appels pour la mémoire des conversations."""
    ident, cree, numero = ident or _ident("resp_"), int(time.time()), [0]

    def ev(nom, donnees):
        numero[0] += 1
        return nom, {"type": nom, "sequence_number": numero[0], **donnees}

    base = objet_response(ident, modele, r, [], statut="in_progress", cree=cree)
    yield ev("response.created", {"response": base})
    yield ev("response.in_progress", {"response": base})
    sortie, textes, appels_vus, fin = [], [], [], {"raison": "stop", "usage": {}}
    message = None  # item message en cours

    def fermer_message():
        texte = "".join(textes)
        idx = len(sortie)
        item = _item_message(texte, message)
        yield ev("response.output_text.done", {"item_id": message, "output_index": idx, "content_index": 0, "text": texte, "logprobs": []})
        yield ev("response.content_part.done", {"item_id": message, "output_index": idx, "content_index": 0,
                                                "part": {"type": "output_text", "text": texte, "annotations": []}})
        yield ev("response.output_item.done", {"output_index": idx, "item": item})
        sortie.append(item)

    for genre, valeur in evenements:
        if genre == "texte":
            if message is None:
                message = _ident("msg_")
                yield ev("response.output_item.added", {"output_index": len(sortie), "item": _item_message(None, message, "in_progress")})
                yield ev("response.content_part.added", {"item_id": message, "output_index": len(sortie), "content_index": 0,
                                                         "part": {"type": "output_text", "text": "", "annotations": []}})
            textes.append(valeur)
            yield ev("response.output_text.delta", {"item_id": message, "output_index": len(sortie), "content_index": 0,
                                                    "delta": valeur, "logprobs": []})
        elif genre == "appels":
            if message is not None:
                yield from fermer_message()
                message = None
            for tc in valeur:
                appels_vus.append(tc)
                item, idx = _item_appel(tc, genres), len(sortie)
                if item["type"] == "function_call":
                    yield ev("response.output_item.added", {"output_index": idx, "item": {**item, "arguments": "", "status": "in_progress"}})
                    yield ev("response.function_call_arguments.delta", {"item_id": item["id"], "output_index": idx, "delta": item["arguments"]})
                    yield ev("response.function_call_arguments.done", {"item_id": item["id"], "output_index": idx, "arguments": item["arguments"]})
                elif item["type"] == "custom_tool_call":
                    yield ev("response.output_item.added", {"output_index": idx, "item": {**item, "input": "", "status": "in_progress"}})
                    yield ev("response.custom_tool_call_input.delta", {"item_id": item["id"], "output_index": idx, "delta": item["input"]})
                    yield ev("response.custom_tool_call_input.done", {"item_id": item["id"], "output_index": idx, "input": item["input"]})
                else:
                    yield ev("response.output_item.added", {"output_index": idx, "item": {**item, "status": "in_progress"}})
                yield ev("response.output_item.done", {"output_index": idx, "item": item})
                sortie.append(item)
        elif genre == "fin":
            fin = valeur
    if message is not None:
        yield from fermer_message()
    if sortie_finale is not None:
        sortie_finale.extend(messages_assistant("".join(textes) or None, appels_vus or None))
    yield ev("response.completed", {"response": objet_response(ident, modele, r, sortie, usage=fin.get("usage") or {}, cree=cree)})
