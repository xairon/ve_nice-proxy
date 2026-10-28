# Ce qui n'est pas pris en charge

Le pont traduit le **texte**, les **images** (entrée et sortie), les **fichiers** joints et la **voix** (synthèse et transcription) vers les routes du site. Ce qui suit n'existe pas, par choix (zone grise des CGU, risque de débit) ou par manque de cartographie. Les capacités multimodales sont détaillées dans [MULTIMODAL.md](MULTIMODAL.md).

| Fonction | État | Détail |
|---|---|---|
| Vision (image en entrée) | **fonctionne** | champ `imagePath` du site ; 8 modèles sans pièce ; data URL ou https ; seule la route « chat classique » (pas Kimi ni DeepSeek) |
| Fichiers joints (PDF, texte) | **fonctionne** | partie `file` du message ; PDF **sans couche texte** (scanné) refusé en 400 : pas d'OCR |
| Génération d'images | **fonctionne** | `/v1/images/generations`, 6 modèles sans pièce, quota Pro ~1 000/jour ; pas d'image-vers-image ni d'édition (`/v1/images/edits` non exposé) |
| Synthèse vocale (TTS) | **fonctionne** | `/v1/audio/speech`, 9 modèles, formats mp3 et wav seulement ; pas de flux |
| Transcription (ASR) | **fonctionne** | `/v1/audio/transcriptions`, un seul modèle (Parakeet) ; **pas d'horodatage** : `srt` et `vtt` refusés, `verbose_json` sans segments ; pas de `language` ni de traduction |
| Audio ou vidéo en entrée d'un modèle | non | seuls des modèles payants (Gemini…) les lisent ; transcrire d'abord |
| Vidéo, musique (génération) | **cartographié, non exposé** | 141 modèles vidéo, aucun sans pièce (ex. Wan 2.7, 5 s en 720p : devis de 55 crédits) ; voir [MULTIMODAL.md](MULTIMODAL.md) |
| Édition d'image, détourage, haute définition | non exposé | routes `inpaint`, `background-remove` repérées dans le code du site, non essayées |
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
