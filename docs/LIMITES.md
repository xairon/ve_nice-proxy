# Ce qui n'est pas pris en charge

Le pont traduit le **texte**, les **images** (entrée et sortie), les **fichiers** joints et la **voix** (synthèse et transcription) vers les routes du site. Ce qui suit n'existe pas, par choix (zone grise des CGU, risque de débit) ou par manque de cartographie. Les capacités multimodales sont détaillées dans [MULTIMODAL.md](MULTIMODAL.md).

| Fonction | État | Détail |
|---|---|---|
| Vision, fichiers, **OCR** (images et PDF scannés), audio vers un modèle (transcrit), images (génération, édition, agrandissement, détourage), voix (synthèse, transcription), embeddings, recherche web | **fonctionnent** | matrice et limites : [MULTIMODAL.md](MULTIMODAL.md) |
| Vision sur la route agents (Kimi, DeepSeek) | non | média passant par un manifeste propre aux « minds » ; utiliser un modèle vision du chat classique |
| Audio « natif » (le modèle entend le ton, la musique) | non, payant | seuls des modèles payants (Gemini…) lisent l'audio : le pont transcrit |
| Horodatage de la transcription (`srt`, `vtt`) | non | la route du site n'en renvoie pas |
| Vidéo, musique (génération) | **payant, non exposé** | 141 + 20 modèles tous payants (Wan 2.7, 5 s : 55 crédits) |
| Édition avec masque, multi-images, clonage de voix | non exposé | non essayé (modèles payants ou risque de débit) |
| Personnages, mémoire Venice, historique de conversations | non | le pont est sans état : le client renvoie tout l'historique ; la route des personnages répond `[]` sur ce compte |
| `/v1/completions`, `/v1/responses`, `/v1/messages` | **non exposés par le pont** | pour Codex CLI et Claude Code, passer par OmniRoute qui traduit ces formats ([HARNESS.md](HARNESS.md)) |
| Température / `top_p` sur la route agents | ignorés | Venice ne les accepte pas sur cette route |
| Comptage de jetons | non | `usage` à zéro ou estimé |
| Vrai streaming | non | réponse complète reçue puis rejouée par morceaux |
| Appels d'outils natifs | non | émulés dans le prompt ; fiabilité variable selon le modèle |
| Contexte au-delà de ~39k sur le chat classique | tronqué en silence | utiliser la route agents (Kimi, DeepSeek) |
| Modèles payants | refusés par défaut | [MODELES.md](MODELES.md) |
| Recherche web / lecture de page / recherche X | optionnel, désactivé par défaut | champs `web_search`, `web_scrape`, `x_search` dans la requête (chat classique) ; seul `web_search` a été essayé (1 essai, 0 crédit, citations `^n^`) |
| Plusieurs utilisateurs sur un même pont | non conçu | une clé partagée ; un compte = un pont |

Pour toute fonction « non cartographiée » : ne l'essayez pas sans avoir lu [SECURITE.md](SECURITE.md). Chaque nouvelle route utilisée par programme étend l'usage que les CGU interdisent déjà.
