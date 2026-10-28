# Exemple de bout en bout

Objectif : partir d'une machine vide et obtenir une réponse de Qwen 3.8 depuis OpenCode, avec le pont installé en service. Les sorties ci-dessous sont celles du 28/10/2026 (valeurs d'exemple).

## 1. Cookie et service

```console
$ ./venice-setup login
Récupérer le cookie __client (une seule fois, valable environ un an) :
  ...
Cookie __client :               ← collez la valeur, rien ne s'affiche
Cookie valide. Solde de crédits : 545.0.
Écrit : ~/.config/venice-setup/defaut/venice.env (600). Profil 'defaut', port 8700. Étape suivante : venice-setup install --profil defaut

$ ./venice-setup install
Unité écrite : ~/.config/systemd/user/venice-pont.service
Pont defaut : OK (127.0.0.1:8700)
  cookie : valide, expire dans 399.7 jours
  crédits : 545.0 (référence 545.0), débit détecté : non
```

## 2. Vérifier à la main

```console
$ export VENICE_PONT_CLE="$(grep ^VENICE_PONT_CLE= ~/.config/venice-setup/defaut/venice.env | cut -d= -f2-)"
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8700/v1/models
401                                                  ← sans clé : refusé
$ curl -s -H "Authorization: Bearer $VENICE_PONT_CLE" http://127.0.0.1:8700/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{"model":"qwen-3-8-27b","messages":[{"role":"user","content":"Réponds par le seul mot: pong"}],"max_tokens":50,"reasoning_effort":"none"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["choices"][0]["message"]["content"])'
pong
$ curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $VENICE_PONT_CLE" -H 'Content-Type: application/json' \
    http://127.0.0.1:8700/v1/chat/completions -d '{"model":"zai-org-glm-5-2","messages":[{"role":"user","content":"hi"}]}'
403                                                  ← modèle payant : refusé, rien débité
```

Appel d'outil émulé :

```console
$ curl -s -H "Authorization: Bearer $VENICE_PONT_CLE" -H 'Content-Type: application/json' http://127.0.0.1:8700/v1/chat/completions -d '{
    "model":"qwen-3-8-27b","reasoning_effort":"none","max_tokens":200,
    "messages":[{"role":"user","content":"Quelle heure est-il à Paris ? Utilise l outil."}],
    "tools":[{"type":"function","function":{"name":"heure","description":"heure dans une ville",
      "parameters":{"type":"object","properties":{"ville":{"type":"string"}},"required":["ville"]}}}]}' \
  | python3 -c 'import sys,json; m=json.load(sys.stdin)["choices"][0]; print(m["finish_reason"], m["message"]["tool_calls"][0]["function"])'
tool_calls {'name': 'heure', 'arguments': '{"ville": "Paris"}'}
```

## 3. OpenCode

```console
$ ./venice-setup harness opencode --appliquer
OpenCode : fournisseur venice-direct ajouté dans ~/.config/opencode/opencode.json (sauvegarde ….bak-20261028-132933)
$ opencode run -m venice-direct/qwen-3-8-27b "Crée bonjour.txt contenant le mot salut"
```

## 4. Contrôler qu'aucun crédit n'est parti

```console
$ ./venice-setup status
Pont defaut : OK (127.0.0.1:8700)
  cookie : valide, expire dans 399.7 jours
  crédits : 545.0 (référence 545.0), débit détecté : non
```

Le solde est relu toutes les 10 minutes : attendez, ou forcez la lecture : `curl -s -H "Authorization: Bearer $VENICE_PONT_CLE" http://127.0.0.1:8700/credits`.

## 5. Via OmniRoute (Codex CLI, Claude Code, Hermes, Open WebUI)

Après avoir déclaré le pont et créé une clé cliente ([OMNIROUTE.md](OMNIROUTE.md)) :

```console
$ export OMNIROUTE_CLE=…        # clé cliente OmniRoute, jamais la clé du pont
$ codex exec --skip-git-repo-check -s read-only "Réponds uniquement par le mot: pong"     # config.toml : voir HARNESS.md
pong
$ ANTHROPIC_BASE_URL=http://127.0.0.1:20128 ANTHROPIC_API_KEY=$OMNIROUTE_CLE \
    claude -p "Réponds uniquement par le mot: pong" --model ven-kimi --tools ""
pong
```

## 6. Retour arrière complet

```console
$ ./venice-setup uninstall --purger
Supprimé : ~/.config/systemd/user/venice-pont.service
Supprimé : ~/.config/venice-setup/defaut (cookie et clé du pont)
$ cp ~/.config/opencode/opencode.json.bak-20261028-132933 ~/.config/opencode/opencode.json   # annule la fusion OpenCode
```
