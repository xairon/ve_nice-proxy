# Modèles : gratuits (sans pièce) ou payants

Venice facture une partie de ses modèles en **crédits** ; d'autres sont **illimités avec l'abonnement Pro**. Sur le site, le sélecteur de modèle affiche une **pièce** à côté des modèles payants. Le pont n'a pas d'API qui dise lesquels sont illimités : sa liste blanche est **relevée à la main** dans ce sélecteur (28/10/2026) et **peut changer** — revérifiez-la de temps en temps (le script `pont/bench_limites.py` et la lecture du solde servent à confirmer qu'un modèle ne débite pas).

## Modèles sans pièce (servis par le pont, 0 crédit débité aux bancs)

| Identifiant (à mettre dans `model`) | Route | Contexte utile | Remarques |
|---|---|---|---|
| `qwen-3-8-27b` | chat classique | ~39k | Qwen 3.8 27B non censuré, Pro seulement. ~190 jetons/s, premier jeton 0,8 s. Bon généraliste et bon en code simple ; **le meilleur choix par défaut** |
| `venice-uncensored-1-2` | chat classique | ~39k | ~125 à 170 jetons/s, outils émulés corrects |
| `gemma4-uncensored` | chat classique | ~39k | 1,2 s, outils corrects |
| `olafangensan-glm-4.7-flash-heretic` | chat classique | ~39k | 3 s, outils corrects |
| `venice-uncensored-role-play` | chat classique | ~39k | pensé pour le jeu de rôle |
| `aion-labs-aion-3-0` | chat classique | ~39k | répond souvent en texte au lieu de l'appel d'outil |
| `kimi-k2-5` | **agents** | 262 144 | le meilleur pour les agents de code ; ~15k jetons de prompt imposés par Venice ; répond parfois en texte au lieu du JSON d'outil |
| `deepseek-v4-1-flash-uncensored` | **agents** | 524 288 | très grande fenêtre ; en agent de code il peut se croire limité aux outils de Venice et ne rien écrire (échec mesuré dans OpenCode) |

## Multimodal sans pièce (mesuré le 28/10/2026, solde identique avant et après chaque essai)

| Capacité | Modèles | Détail |
|---|---|---|
| Vision, OCR (entrée image) | `qwen-3-8-27b`, `qwen3-6-27b`, `qwen3-5-35b-a3b`, `google-gemma-4-26b-a4b-it`, `google-gemma-4-31b-it`, `gemma4-uncensored`, `venice-uncensored-1-2`, `qwen3-vl-235b-a22b` | un dessin (cercle rouge, carré bleu) décrit correctement par chacun ; `venice-uncensored-role-play` répond HTTP 500 avec une image |
| Génération d'image | `z-image-turbo` (défaut), `chroma`, `stable-diffusion-3.5-rev2`, `lustify-sdxl`, `lustify-v8`, `wai-illu` | seul `z-image-turbo` a été exécuté ; les autres sont `usesCredits: false` dans le catalogue web. 36 autres modèles d'image sont payants (refusés) |
| Synthèse vocale | `tts-kokoro` (défaut), `tts-qwen3-0-6b`, `tts-qwen3-1-7b`, `tts-xai-v1`, `tts-gemini-3-1-flash`, `tts-elevenlabs-turbo-v2-5`, `tts-minimax-speech-02-hd` (mp3) ; `tts-inworld-1-5-max`, `tts-gradium-v1` (wav seulement) | texte de 15 caractères par modèle. `tts-orpheus` et `tts-chatterbox-hd` n'ont pas répondu en 120 s : exclus |
| Édition d'image | `qwen-edit-uncensored` (défaut), `firered-image-edit` | image d'au moins ~512 px ; sortie 1 024 px mesurée ; quota « inpaint » 1 000/jour |
| Agrandissement, détourage | (pas de choix de modèle) | ×2 et ×4 mesurés ; PNG avec transparence |
| Embeddings | `text-embedding-bge-m3` | 1 024 dimensions, un seul modèle sur cette route |
| Transcription | `nvidia/parakeet-tdt-0.6b-v3` | multilingue, français correct ; tout nom de modèle envoyé (`whisper-1`…) est remplacé par celui-ci |

Le catalogue web (`/api/app/models`) porte un drapeau `usesCredits` par modèle : c'est la source de la liste ci-dessus (`false` = sans pièce). Les modèles **vidéo** (141) et **musique** (20) sont tous payants.

## Modèles payants (refusés par le pont : HTTP 403 `modele_payant_refuse`)

GLM 5.2 et 5.3 Flash, Kimi K2.7 Code, DeepSeek V4.1 Flash (version chat), Aion 3.5, Qwen 3.6 Plus Uncensored, Grok 4.6, Claude Fable 5.1, Abliterated Large V2 et Flash… (liste relevée sur le sélecteur du site, incomplète) Mesure : environ 0,0003 $ pour une petite requête et ~0,02 $ à 30-50k jetons sur DeepSeek V4.1 Flash (1 crédit = 0,01 $). Pour en autoriser un malgré tout : requête avec le champ `"autoriser_debit": true`, ou `VENICE_PONT_AUTORISER_PAYANTS=1` (tous). **Déconseillé** : un agent en boucle peut vider le solde. Le garde-fou « solde » ([SECURITE.md](SECURITE.md)) alerte si le solde baisse.

## Quand utiliser lequel

| Besoin | Modèle | Pourquoi |
|---|---|---|
| Discussion, rédaction, traduction | `qwen-3-8-27b` | rapide, sans refus, gratuit |
| Agent de code (OpenCode…) | `kimi-k2-5` puis `qwen-3-8-27b` en repli | bancs : Kimi 12/12 tests, Qwen 15/15 sur une tâche de code réelle (OpenCode 1.18.21, ~17k jetons par requête) |
| Très long contexte (> 39k) | `kimi-k2-5` ou `deepseek-v4-1-flash-uncensored` | seuls modèles à grande fenêtre ; au-delà de ~250k Venice **compacte** le contexte |
| Jeu de rôle | `venice-uncensored-role-play` | |
| Claude Code | `kimi-k2-5` (via OmniRoute) | le prompt de Claude Code dépasse 39k : sur Qwen il est tronqué et les réponses sont hors sujet |

## Limites mesurées (28/10/2026, un échantillon par mesure)

- **Chat classique** : plafond entre 39 000 et 40 000 jetons. Au-delà, **pas d'erreur** : HTTP 200, mais Venice garde la fin et jette le début (le prompt système peut disparaître). Réglez vos clients à ~38 000 (`limit.context`).
- **Route agents** : fenêtre annoncée 524 288 (DeepSeek) ou 262 144 (Kimi). Un message minimal consomme déjà ~14 à 15k jetons. Contexte compacté côté serveur au-delà de ~250k. Température et `top_p` ignorés.
- **Pas de comptage de jetons** : `usage` vaut zéro (chat classique) ou une estimation (route agents).
- **Pas de vrai flux** : la réponse est reçue en entier puis rejouée en SSE.
- **Débit** : 16 requêtes simultanées sans 429 ; 60 requêtes en 3 minutes sans refus ; le pont plafonne de toute façon à 20/minute.
- **Appels d'outils** : émulés (définitions dans le prompt, réponse JSON retransformée). Un modèle peut répondre en texte : l'agent client doit tolérer l'absence d'appel.

Tous les chiffres détaillés : [pont/bench-2026-10-28.md](../pont/bench-2026-10-28.md).

## Vérifier qu'un modèle est vraiment gratuit

1. Notez le solde : `./venice-setup status` (ligne « crédits »).
2. Envoyez 5 à 10 requêtes au modèle à travers le pont **en autorisant le débit explicitement** (`"autoriser_debit": true`) — c'est le seul cas où cela vaut la peine.
3. Relisez le solde (`GET /credits` force une lecture ; sinon le pont relit toutes les 10 minutes). Un solde inchangé sur 5 requêtes est un indice, pas une preuve : un plafond caché reste possible.
