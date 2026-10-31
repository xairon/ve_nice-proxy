# Outils (tool calling) et agents de code

Comment le pont fait utiliser des outils (lire un fichier, lancer une commande, écrire du code) à un modèle Venice, dans quels formats il parle aux clients de code, et ce qu'il faut savoir avant de brancher un agent.

## Résumé

| Question | Réponse |
|---|---|
| Quels clients ? | Tout client **chat completions** (OpenCode, aider, Cline, Continue…), **Claude Code** par `/v1/messages` (format Anthropic) et **Codex CLI** par `/v1/responses` (format Responses), directement sur le pont depuis le 31/10/2026. |
| Tool calling natif ? | **Non** sur le chemin web (cookie `__client`) : les définitions sont **émulées dans le prompt** et la réponse est retransformée en appels d'outil du format du client. **Oui** sur l'API officielle (modèles `api/…`, clé API, facturée à l'usage) pour les modèles qui l'annoncent. |
| Pourquoi pas natif sur le web ? | La route agents de Venice accepte `clientTools` mais ne les présente pas au modèle (mesuré le 30/10/2026, six formes essayées). |
| Fiabilité de l'émulation | Bonne sur DeepSeek V4.1 Flash et Kimi K2.5 depuis la relance corrective du 30/10/2026 ; le pont reconnaît aussi les formats que les modèles produisent d'eux-mêmes (voir plus bas). |
| Flux | **Réel**, y compris avec des outils : la prose part au fil de l'eau, seul l'appel d'outil est retenu jusqu'à ce qu'il soit complet. |

## Ce qui se passe concrètement (chemin web)

1. Le client envoie ses outils (`tools` OpenAI, `tools` Anthropic avec `input_schema`, ou `tools` Responses, y compris les outils `custom` comme `apply_patch` de Codex et `local_shell`).
2. Le pont traduit la requête en chat completions, met les définitions (JSON Schema) dans le prompt système et rappelle la consigne à la fin du dernier message. Le modèle doit répondre par :

   ```json
   {"tool_calls":[{"name":"bash","arguments":{"command":"ls"}}]}
   ```

3. Il analyse la réponse et renvoie des appels d'outil au format du client : `tool_calls` (OpenAI), blocs `tool_use` (Anthropic), items `function_call` / `custom_tool_call` / `local_shell_call` (Responses). Le client exécute l'outil et renvoie le résultat ; le pont le transforme en message texte pour Venice, avec le nom de l'outil (`Résultat de l'outil (read, appel call_…) : …`).

Le pont est **sans état** : le client renvoie tout l'historique à chaque tour. Exception : `/v1/responses` garde en mémoire les 200 dernières réponses pour `previous_response_id` (perdues au redémarrage).

## Formats d'appel reconnus

Les modèles n'obéissent pas toujours au format demandé. Le pont accepte, dans cet ordre :

| Format | Exemple | Modèles qui le produisent |
|---|---|---|
| Demandé | `{"tool_calls":[{"name":"read","arguments":{…}}]}` | tous, la plupart du temps |
| Balises | `<tool_call>{"name":"read","arguments":{…}}</tool_call>` (une ou plusieurs) | Qwen, GLM, modèles entraînés au format Hermes |
| Objet ou liste nus | `{"name":"read","parameters":{…}}`, `[{…},{…}]` | variable |
| Bloc Markdown | ```` ```json {…} ``` ```` au milieu de la prose | variable |

Tolérances : prose avant l'appel (elle devient le contenu du message), clés `arguments` / `parameters` / `input`, nom préfixé (`functions.read`) ou en casse différente (`Read`), virgule finale, appel **tronqué** par `max_tokens` (accolades refermées). Les noms sont vérifiés contre la liste fournie : un JSON ordinaire (un `package.json` cité) ou un exemple avec un outil inconnu **reste du texte**.

## `tool_choice`

| Valeur | Effet |
|---|---|
| `auto` (défaut) | le modèle choisit |
| `none` | les outils ne sont pas présentés |
| `required` (OpenAI), `{"type":"any"}` (Anthropic) | consigne « appel obligatoire » ; si le modèle répond en texte, une relance corrective |
| un outil précis | seul cet outil est présenté, appel obligatoire |
| `parallel_tool_calls: false`, `disable_parallel_tool_use` | un seul appel gardé |

## Les garde-fous de l'émulation

- **Relance corrective.** Si le modèle appelle un outil **natif** de Venice, celui-ci répond « Tool not found » et le modèle rédige un refus. Le pont reconnaît ce refus et relance **une fois** avec une consigne renforcée. Même chose quand un appel était obligatoire et n'est pas venu.
- **Flux avec outils.** Le texte est relayé dès qu'il arrive ; à partir de ce qui ressemble au début d'un appel (`{"tool_calls"`, `{"name"`, `<tool_call>`, ```` ``` ````), le pont retient la suite, l'analyse à la fin, puis envoie l'appel (ou le texte retenu s'il n'y avait pas d'appel). La réflexion `<think>…</think>` est relayée telle quelle, sans y chercher d'appel. En flux, si une relance corrective a lieu, le refus initial a déjà été affiché.

## Garde de contexte (chat classique)

Le chat classique de Venice plafonne entre 39 000 et 40 000 jetons et, au-delà, **jette le début sans erreur** : le prompt système, donc la définition des outils, disparaît et l'agent devient incohérent. Le pont estime la taille (3,2 caractères par jeton, prudent) et, au-delà de `VENICE_PONT_CONTEXTE_CHAT` (36 000 par défaut) :

1. **élague** les messages les plus anciens en gardant le système, le premier message (souvent la tâche) et la fin de la conversation, avec une note `[Le pont a retiré N message(s) ancien(s)…]` ;
2. si cela ne suffit pas (prompt système trop gros, ou `VENICE_PONT_ELAGAGE=0`), **refuse** avec HTTP 400 `context_length_exceeded` et le message `prompt is too long: … tokens > … maximum`, que les clients de code reconnaissent pour compacter.

La route agents (Kimi K2.5, DeepSeek V4.1 Flash) et l'API officielle ne sont pas concernées. `VENICE_PONT_CONTEXTE_CHAT=0` coupe la garde.

## Alias de modèles

Les clients de code envoient leurs propres noms de modèle. Par défaut :

| Nom reçu | Modèle Venice |
|---|---|
| `claude-*haiku*` (tâches de fond de Claude Code) | `qwen-3-8-27b` |
| `claude-*`, `gpt-*`, `o1…o9*`, `codex-*` | `kimi-k2-5` |

Un nom de modèle Venice connu (ou préfixé `api/`) n'est jamais réécrit. Remplacer la liste : `VENICE_PONT_ALIAS="claude-*=deepseek-v4-1-flash-uncensored,gpt-*=kimi-k2-5"` (motifs `fnmatch`, le premier qui correspond gagne).

## API officielle : outils natifs (facultatif, facturé)

Ajoutez `VENICE_API_KEY=<clé>` au fichier de secrets du pont (`~/.config/venice-setup/<profil>/venice.env`) puis redémarrez-le. Les modèles **préfixés `api/`** (par exemple `api/qwen3-235b-a22b-instruct-2507`, liste complète dans `GET /v1/models`) passent alors par `api.venice.ai` :

- c'est le chemin **prévu par Venice et conforme à ses CGU**, mais **facturé à l'usage** (crédits API, pas l'abonnement Pro) : la liste blanche des modèles sans pièce ne s'y applique pas, le plafond de débit du pont si ;
- les modèles qui annoncent `supportsFunctionCalling` dans le catalogue reçoivent les outils **en natif** (vrai tool calling, `tool_choice` transmis) ; les autres passent par l'émulation ;
- le prompt système de Venice est désactivé (`include_venice_system_prompt: false`) ;
- sans cookie `__client` dans le fichier, le pont démarre en **mode « API seule »** : tout modèle est servi par l'API (le préfixe est ajouté), et les routes propres au site (images, voix…) répondent 503.

État : **vérifié contre un serveur factice** reproduisant l'API (tests `pont/tests/test_agentique.py`), **pas encore contre la vraie API** faute de clé pendant le développement. Un premier essai réel est le bienvenu : notez le modèle, la date et le coût.

## Ce que votre client doit tolérer

- **Absence d'appel** : le modèle peut répondre en texte même quand des outils sont fournis. Traitez le texte comme une réponse finale.
- **Arguments d'un bloc** : avec l'émulation, les arguments d'un appel arrivent en un seul morceau (`input_json_delta`, `function_call_arguments.delta`), pas jeton par jeton.
- **`usage` estimé** : la route agents donne un total réel ; ailleurs, c'est une estimation (~4 caractères par jeton). `/v1/messages/count_tokens` renvoie aussi une estimation.

## Contexte : quel modèle pour les agents

- **Route agents** (`kimi-k2-5`, `deepseek-v4-1-flash-uncensored`) : grand contexte (262 k / 524 k), prompt Venice imposé ≈ 15 k jetons, température ignorée. **À préférer pour coder**, et **obligatoire pour Claude Code** dont le prompt dépasse 20 k jetons.
- **Chat classique** (Qwen 3.8 et autres) : ~36 k utiles sous la garde du pont. Réglez le client à ~36 k (`limit.context` dans OpenCode).

Détails des modèles : [MODELES.md](MODELES.md). Ce qui n'est pas pris en charge : [LIMITES.md](LIMITES.md).

## Tester

Avec `curl` (le pont doit tourner) :

```bash
export VENICE_PONT_CLE="$(grep ^VENICE_PONT_CLE= ~/.config/venice-setup/defaut/venice.env | cut -d= -f2-)"
# chat completions
curl -s http://127.0.0.1:8700/v1/chat/completions \
  -H "Authorization: Bearer $VENICE_PONT_CLE" -H 'Content-Type: application/json' \
  -d '{
    "model": "deepseek-v4-1-flash-uncensored",
    "messages": [{"role": "user", "content": "Lis /etc/hostname avec l'"'"'outil read."}],
    "tools": [{"type": "function", "function": {
      "name": "read", "description": "Lit un fichier local.",
      "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}}, "required": ["filePath"]}}}]
  }'
# format Anthropic (ce que Claude Code envoie)
curl -s http://127.0.0.1:8700/v1/messages -H "x-api-key: $VENICE_PONT_CLE" -H 'Content-Type: application/json' \
  -d '{"model": "claude-sonnet-4-5", "max_tokens": 1024,
       "tools": [{"name": "read", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}}],
       "messages": [{"role": "user", "content": "Lis /etc/hostname."}]}'
```

Réponse attendue : `"finish_reason": "tool_calls"` (ou `"stop_reason": "tool_use"`) et un appel nommé `read`. Si vous recevez du texte du type « je n'ai pas d'outil », la relance a échoué : renvoyez la requête ou changez de modèle.

Avec un client : `./venice-setup harness opencode --appliquer`, `./venice-setup harness claude-code` ou `./venice-setup harness codex`, puis demandez « crée `notes.txt` avec trois lignes ». Le journal doit montrer un appel d'écriture, et le fichier doit exister.
