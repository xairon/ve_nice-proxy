# Historique

## [Non publié] — 28/10/2026

### Corrigé
- `login` : un cookie invalide ou rotatif ne provoque plus de trace d'erreur (`PermissionError`) ; Clerk qui renouvelle le cookie pendant la validation → c'est le cookie renouvelé qui est enregistré. La validation travaille dans un dossier jetable.
- `login` : un refus de Clerk ou un `--dry-run` ne laisse plus de profil créé dans `profils.json`.
- Dossier de profil créé en mode 700 (il l'était en 775 ; les fichiers étaient déjà en 600).
- Noms de profil validés (`[a-z0-9][a-z0-9_-]{0,31}`) : `..`, `a/b`… refusés (risque d'écrire ou de supprimer hors du dossier des profils).
- `uninstall --purger` retire le profil de la liste ; sans unité installée, plus d'appel `systemctl` inutile ni de message d'erreur effrayant.
- `harness codex` et `harness claude-code` : configurations réellement testées, via OmniRoute (`/v1/responses`, `/v1/messages`).

### Ajouté
- **Multimodal** (28/10/2026, routes lues dans le code du site, chaque capacité essayée une fois, solde Venice inchangé) : vision (`content` en liste, `image_url` data URL ou https avec garde SSRF) sur 8 modèles sans pièce ; fichiers joints (partie `file`, extraction par la route `text_parser`) ; `/v1/images/generations` (6 modèles sans pièce, `b64_json`, quota Pro lu et surveillé, jamais de repli sur les crédits) ; `/v1/audio/speech` (9 voix de modèles) ; `/v1/audio/transcriptions` (Parakeet) ; `/quotas`, `/v1/images/models`, `/v1/audio/models` ; plafonds propres par catégorie ; refus des corps de plus de 32 Mo. Vidéo cartographiée, non exposée. [docs/MULTIMODAL.md](docs/MULTIMODAL.md).
- Liste blanche du chat élargie : `qwen3-6-27b`, `qwen3-5-35b-a3b`, `google-gemma-4-26b-a4b-it`, `google-gemma-4-31b-it`, `qwen3-vl-235b-a22b` (0 crédit mesuré).
- Documentation complète : `docs/` (installation, cookie, modèles, harness, OmniRoute, sécurité, dépannage, limites, exemple), `CONTRIBUER.md`, ce fichier.
- Campagne de tests du 28/10/2026 : login réel, install/uninstall, status, models, profils multiples, chat, outil émulé, SSE, refus 403, Codex CLI et Claude Code via OmniRoute, Open WebUI avec authentification, essai de vision (échec, corrigé depuis : voir ci-dessus).

## 0.1.0 — 28/10/2026
- Premier dépôt : CLI `venice-setup` (login, install, uninstall, status, models, harness, profils), pont OpenAI-compatible (`pont/venice_pont.py`), gabarits systemd et OmniRoute, banc de mesures.
