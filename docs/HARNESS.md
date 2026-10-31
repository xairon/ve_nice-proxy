# Clients (« harness ») : état et configuration

`./venice-setup harness NOM` affiche la configuration exacte pour votre pont (et `--appliquer` la fusionne quand c'est sûr). Légende : **TESTÉ** = essayé pour de vrai, avec la date et la version ; **NON TESTÉ** = configuration déduite de la documentation du client, jamais lancée.

Deux familles :

- **Directs sur le pont** (`http://127.0.0.1:8700/v1`, clé = `VENICE_PONT_CLE`) : tout client qui parle *chat completions*.
- **Directs sur le pont, autres formats** : Claude Code (*Messages* d'Anthropic, `http://127.0.0.1:8700`) et Codex CLI (*Responses*, `http://127.0.0.1:8700/v1`), depuis le 31/10/2026.
- **Via OmniRoute** ([OMNIROUTE.md](OMNIROUTE.md)) : pour mettre alias, clés et plafonds par client.

| Client | État (28/10/2026) | Chemin |
|---|---|---|
| OpenCode 1.18.21 | **TESTÉ** (banc : tâche de code réelle avec Kimi K2.5 12/12 tests, Qwen 3.8 15/15 ; fusion de config `--appliquer` vérifiée sur une copie). Nouvel essai bout en bout avec ce CLI : voir note ci-dessous | pont direct, ou OmniRoute |
| curl / SDK OpenAI | **TESTÉ** (chat, outil émulé, flux SSE, refus 403) | pont direct |
| OmniRoute 3.8.52 | **TESTÉ** (fournisseur `openai-compatible` + alias) | pont → OmniRoute |
| Hermes Agent v0.22.2 | **TESTÉ via OmniRoute** ; branchement direct : format conforme au schéma de config, non lancé | OmniRoute |
| Open WebUI v0.11.4 | **TESTÉ via OmniRoute** (authentification vérifiée, chat réel) ; direct sur le pont : même réglage, non lancé | OmniRoute |
| Codex CLI 0.162.1 | **TESTÉ via OmniRoute** (`codex exec`, `pong` sur `ven-kimi`) ; **direct** (`/v1/responses`, 31/10/2026) : vérifié avec le SDK OpenAI, Codex lui-même **non lancé** | pont direct, ou OmniRoute |
| Claude Code 2.1.312 | **TESTÉ en direct contre Venice** (31/10/2026, `/v1/messages`, `kimi-k2-5` : Glob, Read, Edit, Bash, bogue corrigé, pytest vert, 0 crédit) ; **TESTÉ via OmniRoute** (2.1.312, `pong` sur `ven-kimi`) | pont direct, ou OmniRoute |
| claude-code-router | **NON TESTÉ** (plus nécessaire : le pont parle `/v1/messages`) | pont direct |
| aider | **NON TESTÉ** : installation impossible sur la machine d'essai (Python 3.13, dépendances sans roue précompilée) | pont direct |
| Cline, Continue | **NON TESTÉ** (extensions d'éditeur, non installées) | pont direct |

> Note OpenCode : le contrôle de sécurité de la machine d'essai a bloqué le lancement d'un nouvel agent `opencode run` pendant cette campagne ; l'essai bout en bout précédent (même modèle, même pont) reste la référence. Si vous l'installez, lancez `opencode run -m venice-direct/qwen-3-8-27b "Crée un fichier bonjour.txt contenant salut"` dans un dossier jetable pour le rejouer.

## OpenCode

```bash
./venice-setup harness opencode            # affiche le JSON
./venice-setup harness opencode --appliquer # le fusionne dans ~/.config/opencode/opencode.json (sauvegarde .bak-*)
export VENICE_PONT_CLE="$(grep ^VENICE_PONT_CLE= ~/.config/venice-setup/defaut/venice.env | cut -d= -f2-)"
opencode run -m venice-direct/kimi-k2-5 "..."
```

Le fournisseur ajouté (nom `venice-direct`) :

```json
{
  "provider": {
    "venice-direct": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Venice (pont local)",
      "options": { "baseURL": "http://127.0.0.1:8700/v1", "apiKey": "{env:VENICE_PONT_CLE}" },
      "models": {
        "kimi-k2-5":                       { "name": "kimi-k2-5", "tool_call": true, "limit": { "context": 38000, "output": 8192 } },
        "qwen-3-8-27b":                    { "name": "qwen-3-8-27b", "tool_call": true, "limit": { "context": 38000, "output": 8192 } },
        "deepseek-v4-1-flash-uncensored":  { "name": "deepseek-v4-1-flash-uncensored", "tool_call": true, "limit": { "context": 38000, "output": 8192 } }
      }
    }
  }
}
```

`limit.context` est volontairement borné à 38 000 : OpenCode compacte avant la troncature silencieuse de Venice. Si vous gardez Kimi (262k), vous pouvez monter la valeur. Pour ne pas passer par une variable d'environnement : `"apiKey": "{file:~/.config/venice-setup/defaut/pont-cle}"` avec un fichier contenant seulement la clé. Si vous avez un `opencode.jsonc` (avec commentaires), `--appliquer` refuse de le fusionner et vous demande de le faire à la main.

**Interface web / Android d'OpenCode** : `opencode web --hostname 127.0.0.1 --port 8535` avec `OPENCODE_SERVER_USERNAME` et `OPENCODE_SERVER_PASSWORD` définis (sans mot de passe, tout le monde atteignant le port pilote un agent avec shell). Testé : 401 sans identifiants, 200 avec. À publier sur un réseau privé (VPN, tailnet), jamais sur Internet.

## OpenAI générique (curl, SDK, tout outil « OpenAI-compatible »)

```bash
./venice-setup harness openai     # affiche OPENAI_BASE_URL et OPENAI_API_KEY à exporter
```

```bash
curl -s http://127.0.0.1:8700/v1/chat/completions \
  -H "Authorization: Bearer $VENICE_PONT_CLE" -H 'Content-Type: application/json' \
  -d '{"model":"qwen-3-8-27b","messages":[{"role":"user","content":"Réponds: pong"}],"max_tokens":50,"reasoning_effort":"none"}'
```

Champs supplémentaires acceptés : `reasoning_effort: "none"` (coupe la réflexion), `web_search`, `include_venice_system_prompt`, `autoriser_debit`.

Image en entrée, image en sortie, voix (détails et limites : [MULTIMODAL.md](MULTIMODAL.md)) :

```bash
# vision : modèle sans pièce + content en liste (data URL ou https)
curl -s http://127.0.0.1:8700/v1/chat/completions -H "Authorization: Bearer $VENICE_PONT_CLE" -H 'Content-Type: application/json' \
  -d '{"model":"qwen-3-8-27b","messages":[{"role":"user","content":[{"type":"text","text":"Décris."},{"type":"image_url","image_url":{"url":"https://exemple.org/photo.png"}}]}]}'
# génération d'image (réponse : data[0].b64_json)
curl -s http://127.0.0.1:8700/v1/images/generations -H "Authorization: Bearer $VENICE_PONT_CLE" -H 'Content-Type: application/json' \
  -d '{"prompt":"une pomme rouge","size":"1024x1024"}'
# synthèse vocale puis transcription
curl -s http://127.0.0.1:8700/v1/audio/speech -H "Authorization: Bearer $VENICE_PONT_CLE" -H 'Content-Type: application/json' \
  -d '{"input":"Bonjour","voice":"alloy"}' -o bonjour.mp3
curl -s http://127.0.0.1:8700/v1/audio/transcriptions -H "Authorization: Bearer $VENICE_PONT_CLE" -F file=@bonjour.mp3 -F model=whisper-1
```

## Hermes Agent

Dans `~/.hermes/config.yaml` (le format `providers:` a été comparé à une configuration Hermes v0.22.2 réelle) :

```yaml
providers:
  venice:
    name: Venice (pont local)
    base_url: http://127.0.0.1:8700/v1
    key_env: VENICE_PONT_CLE      # variable d'environnement qui contient la clé du pont
    model: qwen-3-8-27b
```

Le chemin **testé** passe par OmniRoute : `base_url: http://127.0.0.1:20128/v1`, `key_env: <variable de la clé OmniRoute>`, `model: ven-qwen-nc`. Dans une conversation Hermes, on change de fournisseur avec `/model ven-qwen-nc --provider <nom>` : **sans `--provider`**, le modèle est cherché chez le fournisseur par défaut et l'erreur « model ID not valid » apparaît.

## Open WebUI

Images, voix et dictée : Administration > Paramètres > Images (moteur OpenAI, URL du pont, modèle `z-image-turbo`), Audio (TTS et STT : moteur OpenAI, même URL et même clé). La vision marche avec un modèle de la liste vision de [MODELES.md](MODELES.md). Réglages à confirmer dans votre version d'Open WebUI : le pont répond toujours en `b64_json` pour les images.

*Réglages > Connexions > OpenAI > +* : URL `http://127.0.0.1:20128/v1` (OmniRoute) ou `http://127.0.0.1:8700/v1` (pont), clé correspondante, puis filtrer la liste de modèles. Avec Docker en réseau hôte (`network_mode: host`), `127.0.0.1` désigne bien la machine ; en réseau pont, utiliser l'adresse de l'hôte. Recommandations (testées dans notre déploiement) : **authentification activée** (`WEBUI_AUTH=True`, `ENABLE_SIGNUP=False`), titres/tags/suggestions automatiques **coupés** (ils consomment votre plafond de requêtes), `mem_limit` posé.

## Codex CLI (direct sur le pont)

Codex CLI exige l'API *Responses*. Le pont l'expose depuis le 31/10/2026 (`/v1/responses`, flux compris) : outils `function`, outils `custom` à entrée libre (`apply_patch`) et `local_shell` sont traduits ; les outils hébergés par OpenAI (`web_search`…) sont ignorés.

```toml
# ~/.codex/config.toml   (./venice-setup harness codex l'affiche avec votre adresse)
model_provider = "venice"
model = "kimi-k2-5"
[model_providers.venice]
name = "Venice (pont local)"
base_url = "http://127.0.0.1:8700/v1"
env_key = "VENICE_PONT_CLE"
wire_api = "responses"
```

État : **vérifié avec le SDK OpenAI** (`responses.create` et `responses.stream`, appels de fonction compris) et par les tests du pont ; **Codex CLI lui-même n'a pas encore été lancé en direct**. Un nom `gpt-*` / `codex-*` est réécrit vers `kimi-k2-5` (voir les alias dans [OUTILS.md](OUTILS.md)). Avertissement bénin attendu : « Model metadata … not found ».

Variante **testée** via OmniRoute (28/10/2026, `codex exec` → `pong`) : `base_url = "http://127.0.0.1:20128/v1"`, `env_key = "OMNIROUTE_CLE"`, `model = "ven-kimi"`.

## Claude Code (direct sur le pont)

Le pont expose l'API *Messages* d'Anthropic (`/v1/messages`, `/v1/messages/count_tokens`, flux SSE au format Anthropic, blocs `tool_use` / `tool_result`, images, clé lue dans `x-api-key` ou `Authorization`).

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8700            # sans /v1
export ANTHROPIC_API_KEY="$VENICE_PONT_CLE"
export ANTHROPIC_MODEL=kimi-k2-5
export ANTHROPIC_DEFAULT_HAIKU_MODEL=qwen-3-8-27b          # tâches de fond
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1          # moins de requêtes annexes (plafond de 20/min)
claude
```

**Testé contre le vrai Venice** (31/10/2026) : **Claude Code 2.1.312** en `claude -p`, `kimi-k2-5`, configuration de `venice-setup harness claude-code`, sur un petit projet Python dont un test échouait : en 20 s et 6 tours, Claude Code a enchaîné Glob, Read ×2, Edit et Bash (`pytest -v`), corrigé le bogue sans toucher aux tests, et `pytest` est passé (2/2). Aucune erreur du pont, solde inchangé (285 → 285). Seul avertissement du client, sans effet : `unrecognized_model`.

Essai antérieur (31/10/2026) : **Claude Code 2.1.316** en `claude -p "Crée bonjour.txt contenant salut" --allowedTools Write`, pont réel, **réponses du modèle simulées** (pas d'accès à Venice depuis la machine d'essai) : Claude Code a reçu l'appel `Write` émulé, écrit le fichier, renvoyé le résultat, puis affiché la réponse finale. Le prompt système de Claude Code (outils compris) pesait ~74 000 caractères, d'où le choix de `kimi-k2-5` : sur le chat classique, la garde de contexte du pont refuse vite avec « prompt is too long » (au lieu de la troncature silencieuse qui donnait des réponses hors sujet le 28/10/2026). Sans `ANTHROPIC_MODEL`, les noms `claude-*` sont réécrits vers `kimi-k2-5` (et `claude-*haiku*` vers `qwen-3-8-27b`).

Variante **testée** via OmniRoute (28/10/2026, `claude -p … --model ven-kimi` → `pong`) : `ANTHROPIC_BASE_URL=http://127.0.0.1:20128`, `ANTHROPIC_API_KEY="$OMNIROUTE_CLE"`.

### Claude Code chef, DeepSeek au clavier

`venice-setup harness claude-code` imprime aussi deux lignes à lancer une fois : l'outil MCP `venice-mcp` (`claude mcp add … deepseek`) et la consigne `gabarits/claude-code/CLAUDE.deepseek.md`. Claude Code explore et relit, et confie chaque écriture de code à DeepSeek V4.1 Flash Uncensored (gratuit, ~500k) par l'outil `deepseek_coder`, qui applique et teste. Détails : [OUTILS.md](OUTILS.md#en-outil-mcp--venice-mcp).

**Sur demande** : avec `gabarits/claude-code/CLAUDE.venice-mode.md` ajouté à `~/.claude/CLAUDE.md` et la commande `gabarits/claude-code/commands/venice.md` copiée dans `~/.claude/commands/`, Claude Code travaille normalement jusqu'à « utilise venice » ou `/venice`, puis confie l'écriture à DeepSeek pour le reste de la session ; « arrête venice » revient. Le gabarit `CLAUDE.deepseek.md` (délégation permanente) reste pour un projet dédié.

**Testé contre le vrai Venice** (31/10/2026, Claude Code 2.1.312 + `kimi-k2-5`, `.mcp.json` de projet + consigne) : panier sans sa remise, 1 test sur 2 en échec. En 28 s, Kimi a exploré (Read, Bash) puis appelé **une fois** `deepseek_coder` ; DeepSeek a écrit la correction, appliquée et testée par l'outil ; Kimi n'a fait **aucun** Edit ni Write. pytest 2/2, journal du pont : 6 × `/v1/messages` (Kimi) + 1 × `/v1/chat/completions` (DeepSeek), tous 200, 0 crédit.

### claude-code-router (non testé, plus nécessaire)

Projet tiers (<https://github.com/musistudio/claude-code-router>), configuré dans `~/.claude-code-router/config.json` : un fournisseur dont `api_base_url` est l'URL **complète** `http://127.0.0.1:8700/v1/chat/completions`, `api_key` = clé du pont, `models: ["kimi-k2-5"]`, et un bloc `Router` qui désigne `"default": "venice,kimi-k2-5"` ; lancement par `ccr code`. Non essayé ici : préférez OmniRoute, déjà en place et testé.

## aider (testé, recommandé pour DeepSeek et les gros dépôts)

aider n'envoie **aucun outil** : le modèle répond par des blocs SEARCH/REPLACE qu'aider applique. C'est ce qui débloque `deepseek-v4-1-flash-uncensored` (route agents, ~500k de contexte, gratuit) : avec des outils déclarés, la boucle d'agent de Venice intercepte ses appels natifs (« Tool not found »). `venice-setup harness aider` imprime la recette :

```bash
cp gabarits/aider/aider.model.metadata.json ~/.aider.model.metadata.json   # annonce la vraie fenêtre à aider
export OPENAI_API_BASE=http://127.0.0.1:8700/v1
export OPENAI_API_KEY=<clé du pont>
aider --model openai/deepseek-v4-1-flash-uncensored --edit-format diff --map-tokens 4096 --no-show-model-warnings
# ajoutez les fichiers à modifier ; --test-cmd "pytest -q" --auto-test pour boucler sur les tests
```

Essai réel du 31/10/2026 (aider 0.86.2, ce dépôt, renommage d'une fonction dans 3 fichiers, 263 tests) :

| modèle | durée | contexte envoyé | tours | tests |
|---|---|---|---|---|
| deepseek-v4-1-flash-uncensored | 66 s | 109k jetons | 1 | 263/263 |
| kimi-k2-5 | 137 s | 103k puis 105k | 2 | 263/263 |

Aucune mention d'outil dans les journaux, 0 crédit. Les modèles du chat classique (GLM 4.7 Heretic, Venice Uncensored 1.2, Gemma 4 Uncensored) marchent aussi avec aider, mais restent plafonnés à ~36k de contexte.

## Continue (non testé)

```yaml
# ~/.continue/config.yaml
models:
  - name: Venice (pont)
    provider: openai
    model: kimi-k2-5
    apiBase: http://127.0.0.1:8700/v1
    apiKey: <clé du pont>
    useResponsesApi: false
```

## Cline (non testé)

Fournisseur « OpenAI Compatible » : Base URL `http://127.0.0.1:8700/v1`, clé du pont, identifiant de modèle `kimi-k2-5`.
