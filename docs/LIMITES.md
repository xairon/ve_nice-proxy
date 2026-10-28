# Ce qui n'est pas pris en charge

Le pont traduit **du texte** : messages `system` / `user` / `assistant` / `tool`, appels d'outils émulés, flux SSE rejoué. Le reste n'existe pas, par choix (zone grise des CGU, risque de débit) ou par manque de cartographie.

| Fonction | État | Détail |
|---|---|---|
| **Vision** (image en entrée) | **ne marche pas** | Test du 28/10/2026, un essai, 0 crédit : le chat classique (`qwen-3-8-27b`) répond HTTP 400 `Expected string, received array` quand `content` est une liste `[{type: text}, {type: image_url}]` (format OpenAI). Le pont ne garde donc que le texte des messages. Le champ qui porte une image côté site (téléversement préalable ? champ de pièce jointe ?) n'est pas relevé : à explorer par observation du navigateur |
| Génération d'images | non cartographié | annoncée par Venice (quota quotidien) mais **débite des crédits** ; rien d'essayé |
| Voix (TTS), transcription (ASR) | non cartographié | rien d'essayé |
| Téléversement de fichiers / pièces jointes | non cartographié | |
| Personnages, mémoire Venice, historique de conversations | non | le pont est sans état : le client renvoie tout l'historique |
| `/v1/embeddings`, `/v1/completions`, `/v1/responses`, `/v1/messages` | **non exposés par le pont** | pour Codex CLI et Claude Code, passer par OmniRoute qui traduit ces formats ([HARNESS.md](HARNESS.md)) |
| Température / `top_p` sur la route agents | ignorés | Venice ne les accepte pas sur cette route |
| Comptage de jetons | non | `usage` à zéro ou estimé |
| Vrai streaming | non | réponse complète reçue puis rejouée par morceaux |
| Appels d'outils natifs | non | émulés dans le prompt ; fiabilité variable selon le modèle |
| Contexte au-delà de ~39k sur le chat classique | tronqué en silence | utiliser la route agents (Kimi, DeepSeek) |
| Modèles payants | refusés par défaut | [MODELES.md](MODELES.md) |
| Recherche web / lecture de page / recherche X | optionnel, désactivé par défaut | champs `web_search`, `web_scrape`, `x_search` dans la requête (chat classique) ; seul `web_search` a été essayé (1 essai, 0 crédit, citations `^n^`) |
| Plusieurs utilisateurs sur un même pont | non conçu | une clé partagée ; un compte = un pont |

Pour toute fonction « non cartographiée » : ne l'essayez pas sans avoir lu [SECURITE.md](SECURITE.md). Chaque nouvelle route utilisée par programme étend l'usage que les CGU interdisent déjà.
