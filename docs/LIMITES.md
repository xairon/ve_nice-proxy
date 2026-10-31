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
| `/v1/responses`, `/v1/messages` | **exposés** (31/10/2026) | Codex CLI et Claude Code se branchent directement ([HARNESS.md](HARNESS.md)) ; outils hébergés par OpenAI (`web_search`…) et blocs `thinking` signés d'Anthropic ignorés ; `previous_response_id` gardé en mémoire (200 dernières réponses) |
| `/v1/completions` (ancienne complétion de texte) | non exposé | utiliser chat completions |
| Température / `top_p` sur la route agents | ignorés | Venice ne les accepte pas sur cette route |
| Comptage de jetons | estimé | `usage` réel sur la route agents et l'API officielle, estimé ailleurs ; `/v1/messages/count_tokens` estime aussi |
| Vrai streaming | oui pour le texte | relayé au fil de l'eau, outils fournis ou non ; seul l'appel d'outil émulé est retenu jusqu'à être complet, puis envoyé d'un bloc |
| Appels d'outils natifs | non sur le web, oui sur l'API | chemin web : émulés dans le prompt (formats `{"tool_calls"}`, `<tool_call>`, objet nu reconnus ; relance corrective). API officielle (`api/…`, clé, facturé) : natifs pour les modèles qui l'annoncent ([OUTILS.md](OUTILS.md)) |
| Contexte au-delà de ~39k sur le chat classique | élagué ou refusé par le pont | plus de troncature silencieuse : le pont retire les messages anciens ou répond 400 `context_length_exceeded` ; pour les longues sessions, la route agents (Kimi, DeepSeek) |
| Modèles payants | refusés par défaut | [MODELES.md](MODELES.md) |
| Recherche web / lecture de page / recherche X | optionnel, désactivé par défaut | champs `web_search`, `web_scrape`, `x_search` dans la requête (chat classique) ; seul `web_search` a été essayé (1 essai, 0 crédit, citations `^n^`) |
| Plusieurs utilisateurs sur un même pont | non conçu | une clé partagée ; un compte = un pont |

Pour toute fonction « non cartographiée » : ne l'essayez pas sans avoir lu [SECURITE.md](SECURITE.md). Chaque nouvelle route utilisée par programme étend l'usage que les CGU interdisent déjà.
