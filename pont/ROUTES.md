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

## Multimodal (28/10/2026, lu dans le code du site puis un essai par route, solde 285 avant/après chaque essai)
Corps et détails : [docs/MULTIMODAL.md](../docs/MULTIMODAL.md).
| Route | Corps | Réponse | Statut |
|---|---|---|---|
| `POST /api/inference/chat` | `prompt[].imagePath: [base64 brut]` (dernier message avec image seulement) ; `audioPath`, `videoPath` (modèles payants) ; `isFile: true` pour un fichier inliné | NDJSON | testé, 8 modèles sans pièce |
| `POST /api/inference/text_parser` | multipart `file` | `{text, tokens}` ; PDF sans texte : 400 `InvalidFileException` | testé |
| `POST /api/inference/image` | `modelId, prompt, width, height, steps, seed, requestId, hideWatermark, matureFilter, format(png|webp), embedExifMetadata, negativePrompt…` ; **ne jamais envoyer `acceptCreditFallback`** | octets de l'image ; en-têtes `x-ratelimit-remaining`, `x-venice-is-content-violation`, `x-venice-is-blurred` | testé (`z-image-turbo`, 0 crédit) |
| `POST /api/inference/image/quote` | `modelId, prompt, variants` | `{quote}` (crédits de repli) : 2 (z-image-turbo), 3 (flux-2-pro) | testé, gratuit |
| `POST /api/inference/tts` | `{input, model, voice, response_format(mp3|wav), speed}` | audio | testé, 11 modèles |
| `POST /api/inference/asr` | multipart `file` + `model=nvidia/parakeet-tdt-0.6b-v3`, `responseFormat`, `timestamps` ; ou JSON `audio` en base64 | `{text}` (aucun horodatage reçu malgré `timestamps`) | testé |
| `GET /api/inference/rate-limits` | — | `{chat, conversation, image, inpaint, scrape: {remaining, resetAt}}` | testé |
| `POST /api/inference/video/quote` | `modelId, prompt, duration, resolution…` | `{quote}` : 55 (wan-2-7, 5 s) | testé, gratuit |
| `POST /api/inference/video/queue`, `GET /video/retrieve`, `/music/queue` | voir schémas du site | file d'attente | **non essayé** (141 + 20 modèles tous payants) |
| `POST /api/inference/inpaint`, `/background-remove`, `/multi-edit` | multipart | image | repéré, non essayé |
| `GET /api/app/models` | — | catalogue par catégorie (`image`, `inpaint`, `text`, `tts`, `music`, `video`, `embedding`), drapeau `usesCredits` par modèle | testé |

## Non cartographié ou non testé (volontairement)
Personnages, mémoire, historique de conversations, vision sur la route agents (média passant par un manifeste propre aux « minds »), génération vidéo et musique, édition d'image.

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
