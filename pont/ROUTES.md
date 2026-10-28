# Routes Venice utilisées par le pont (28/10/2026)

Authentification commune : jeton Clerk de 60 s (`Authorization: Bearer`), miné depuis le cookie `__client`. Pas de contournement d'anti-bot : les requêtes `requests` simples passent. « Testé » = essayé avec le jeton le 28/10/2026 ; « source » = lu dans le dépôt public `despin/venice-ai-chat-proxy`, non testé ici.

| Route | Rôle | Statut |
|---|---|---|
| `GET https://venice.ai/api/user/session` (ou outerface) | renvoie `{token}` : un JWT Venice dont la charge utile contient le solde : `veniceCredits` (total, 586), `bundledCreditsUsage.availableCredits` (forfait, 86/100), `referralCredits`, dates d'abonnement | testé, gratuit |
| `POST https://outerface.venice.ai/api/inference/chat` | chat classique, réponse NDJSON (`{"kind":"content","content":…}`) | testé |
| `POST …/api/inference/chat/agents/venice?agentModelId=<id>` | mode « Discussion agentique », SSE de type Responses | testé |
| `POST …/api/inference/workflow/chat?agentModelId=kimi-k2-5` | ancien workflow agentique | source, non testé |
| `GET https://api.venice.ai/api/v1/models` | catalogue API (le catalogue web est `/api/app/models`) | testé |
| `GET …/api/app/encrypted_models` | JWT du catalogue avec température/top_p par défaut de chaque modèle | source |
| `POST …/api/user/venice_mode/toggle` `{simple}` | bascule du mode simple | source |
| `api.venice.ai/api/v1/chat/completions` | API officielle : refuse le jeton Clerk (401) | testé |

## Chat classique : corps de requête
Champs vérifiés : `requestId`, `conversationType:"text"`, `type:"text"`, `modelId`, `prompt` (liste `{role, content}`), `systemPrompt`, `includeVeniceSystemPrompt` (false = sans le prompt Venice), `isCharacter:false`, `webEnabled`, `webScrapeEnabled`, `xSearchEnabled`, `temperature`, `topP`, `maxTokens`, `reasoning` (false coupe la réflexion), `clientProcessingTime`. Le dépôt source ajoute `simpleMode` et `userId`.

| Capacité | Champ OpenAI du pont | Testé | Crédits | Limite |
|---|---|---|---|---|
| Température, top_p, max tokens | `temperature`, `top_p`, `max_tokens` | oui | 0 | — |
| Prompt système du client sans prompt Venice | `messages[role=system]` (Venice désactivé par défaut) | oui | 0 | — |
| Réintégrer le prompt Venice | `include_venice_system_prompt` | oui | 0 | — |
| Réflexion coupée | `reasoning_effort: "none"` | oui | 0 | — |
| Recherche web (citations `^n^`) | `web_search` | oui, 1 essai sur qwen-3-8-27b | 0 | — |
| Lecture de pages web | `web_scrape` | non | ? | — |
| Recherche X | `x_search` | non | ? | — |
| Outils OpenAI | `tools` (émulés dans le prompt, JSON) | oui | 0 | un modèle peut répondre en texte (Kimi K2.5, Aion 3.0) |
| Contexte | — | oui | 0 | ~39k jetons ; au-delà, début tronqué sans erreur |
| Concurrence | — | oui | 0 | 16 simultanées sans 429 |

## Route agents : corps de requête
`{"clientTools": [], "input": {"messages": [{"type":"message","role":"user","id":"…","status":"completed","content":[{"type":"output_text","text":"…","annotations":[]}]}]}}`. Pas de champ système ni de température : le système passe comme premier message utilisateur `[System]\n…`. Flux : `response.output_text.delta` (le raisonnement arrive avec un `item_id` en `rs_…`, la réponse en `agent-node:llm:0`), `response.output_text.done` avec `context_metadata {total_tokens, max_context_length: 524288}`, puis `response.completed`. Les `clientTools` natifs ne sont pas utilisés : les outils sont émulés comme sur le chat classique. Prompt imposé par Venice ≈ 15k jetons ; compactage du contexte au-delà de ~250k. Crédits : 0 sur DeepSeek V4.1 Flash Uncensored et Kimi K2.5 au banc.

## Non cartographié ou non testé (volontairement)
Images (1000/jour annoncés), TTS, ASR, upload de fichiers et pièces jointes, personnages, mémoire, historique de conversations : routes non relevées, rien d'essayé (risque de débit de crédits, de modification du compte ou d'usage au-delà de ce que le propriétaire du compte a décidé). À cartographier par observation du navigateur du propriétaire du compte si besoin.

## Risques
Usage en zone grise des CGU : cookie de session utilisé par un programme. Garde-fous : plafond 20 req/min côté OmniRoute, pas de boucle, arrêt au premier 429.

## Banc OpenCode, tâche de code réelle (28/10/2026)
Tâche : module JS `energie.mjs` + tests `node:test` + README, outils d'OpenCode 1.18.21 (prompt ~65 Ko, ~17k jetons par requête).
| Modèle (via pont direct) | Durée | Requêtes | Résultat |
|---|---|---|---|
| Qwen 3.8 27B (chat) | 32 s | 7 | 15/15 tests |
| Kimi K2.5 (agents) | 57 s | ~6 | 12/12 tests |
| Kimi K2.7 Code (chat, débité) | 70 s | 6 | 11/11 tests |
| DeepSeek V4.1 Flash NC (agents) | 22 à 131 s | 1 à 3 | échec : se croit limité aux outils Venice (« Tool not found »), rien écrit |
Via OmniRoute : 146 s puis abandon, écritures longues refusées (arguments d'outil dupliqués).
