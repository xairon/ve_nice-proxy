# Clients (« harness ») : état et configuration

`./venice-setup harness NOM` affiche la configuration exacte pour votre pont (et `--appliquer` la fusionne quand c'est sûr). Légende : **TESTÉ** = essayé pour de vrai, avec la date et la version ; **NON TESTÉ** = configuration déduite de la documentation du client, jamais lancée.

Deux familles :

- **Directs sur le pont** (`http://127.0.0.1:8700/v1`, clé = `VENICE_PONT_CLE`) : tout client qui parle *chat completions*.
- **Via OmniRoute** ([OMNIROUTE.md](OMNIROUTE.md)) : nécessaire pour les clients qui parlent un autre format (Codex CLI : *Responses* ; Claude Code : *Messages* d'Anthropic) ou pour mettre alias, clés et plafonds par client.

| Client | État (28/10/2026) | Chemin |
|---|---|---|
| OpenCode 1.18.21 | **TESTÉ** (banc : tâche de code réelle avec Kimi K2.5 12/12 tests, Qwen 3.8 15/15 ; fusion de config `--appliquer` vérifiée sur une copie). Nouvel essai bout en bout avec ce CLI : voir note ci-dessous | pont direct, ou OmniRoute |
| curl / SDK OpenAI | **TESTÉ** (chat, outil émulé, flux SSE, refus 403) | pont direct |
| OmniRoute 3.8.52 | **TESTÉ** (fournisseur `openai-compatible` + alias) | pont → OmniRoute |
| Hermes Agent v0.22.2 | **TESTÉ via OmniRoute** ; branchement direct : format conforme au schéma de config, non lancé | OmniRoute |
| Open WebUI v0.11.4 | **TESTÉ via OmniRoute** (authentification vérifiée, chat réel) ; direct sur le pont : même réglage, non lancé | OmniRoute |
| Codex CLI 0.162.1 | **TESTÉ via OmniRoute uniquement** (`codex exec`, réponse `pong` sur `ven-kimi`) | OmniRoute (`/v1/responses`) |
| Claude Code 2.1.312 | **TESTÉ via OmniRoute uniquement** (`claude -p`, `pong` sur `ven-kimi`). Sur `ven-qwen-nc` le prompt est tronqué : réponse hors sujet | OmniRoute (`/v1/messages`) |
| claude-code-router | **NON TESTÉ** (alternative à OmniRoute ; voir ci-dessous) | pont direct |
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

*Réglages > Connexions > OpenAI > +* : URL `http://127.0.0.1:20128/v1` (OmniRoute) ou `http://127.0.0.1:8700/v1` (pont), clé correspondante, puis filtrer la liste de modèles. Avec Docker en réseau hôte (`network_mode: host`), `127.0.0.1` désigne bien la machine ; en réseau pont, utiliser l'adresse de l'hôte. Recommandations (testées dans notre déploiement) : **authentification activée** (`WEBUI_AUTH=True`, `ENABLE_SIGNUP=False`), titres/tags/suggestions automatiques **coupés** (ils consomment votre plafond de requêtes), `mem_limit` posé.

## Codex CLI (via OmniRoute)

Codex CLI exige l'API *Responses* (`wire_api = "chat"` a été retiré début 2026 d'après la documentation de la communauté et des guides tiers, non confirmé par une source OpenAI primaire). Le pont n'expose que *chat completions* ; OmniRoute traduit `/v1/responses` vers lui.

```toml
# ~/.codex/config.toml
model_provider = "omniroute"
model = "ven-kimi"
[model_providers.omniroute]
name = "OmniRoute"
base_url = "http://127.0.0.1:20128/v1"
env_key = "OMNIROUTE_CLE"
wire_api = "responses"
```

Testé : `OMNIROUTE_CLE=… codex exec --skip-git-repo-check -s read-only "Réponds uniquement par le mot: pong"` → `pong`. Avertissement bénin : « Model metadata for `ven-kimi` not found » (Codex ne connaît pas l'alias). Le `CODEX_HOME` était un dossier jetable.

## Claude Code (via OmniRoute)

OmniRoute expose `/v1/messages` (format Anthropic) et le traduit vers Venice :

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:20128
export ANTHROPIC_API_KEY="$OMNIROUTE_CLE"
claude --model ven-kimi
```

Testé : `claude -p "Réponds uniquement par le mot: pong" --model ven-kimi --tools ""` → `pong` (avec un `CLAUDE_CONFIG_DIR` jetable). Claude Code avertit que le modèle est inconnu et suppose 200k de contexte : les alias à grande fenêtre (Kimi 262k) conviennent ; **le prompt de Claude Code dépasse 39k jetons : sur `ven-qwen-nc` il est tronqué en silence et la réponse est hors sujet** (essai du 28/10/2026 : réponse sans rapport avec la demande).

### claude-code-router (non testé)

Projet tiers (<https://github.com/musistudio/claude-code-router>), configuré dans `~/.claude-code-router/config.json` : un fournisseur dont `api_base_url` est l'URL **complète** `http://127.0.0.1:8700/v1/chat/completions`, `api_key` = clé du pont, `models: ["kimi-k2-5"]`, et un bloc `Router` qui désigne `"default": "venice,kimi-k2-5"` ; lancement par `ccr code`. Non essayé ici : préférez OmniRoute, déjà en place et testé.

## aider (non testé)

Selon la documentation d'aider : `OPENAI_API_BASE=http://127.0.0.1:8700/v1`, `OPENAI_API_KEY=<clé du pont>`, puis `aider --model openai/kimi-k2-5` (le préfixe `openai/` sélectionne le protocole chat completions de LiteLLM).

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
