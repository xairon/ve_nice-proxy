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
- Documentation complète : `docs/` (installation, cookie, modèles, harness, OmniRoute, sécurité, dépannage, limites, exemple), `CONTRIBUER.md`, ce fichier.
- Campagne de tests du 28/10/2026 : login réel, install/uninstall, status, models, profils multiples, chat, outil émulé, SSE, refus 403, Codex CLI et Claude Code via OmniRoute, Open WebUI avec authentification, essai de vision (échec documenté).

## 0.1.0 — 28/10/2026
- Premier dépôt : CLI `venice-setup` (login, install, uninstall, status, models, harness, profils), pont OpenAI-compatible (`pont/venice_pont.py`), gabarits systemd et OmniRoute, banc de mesures.
