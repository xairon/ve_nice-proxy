# venice-setup

[![CI](https://github.com/xairon/ve_nice-proxy/actions/workflows/ci.yml/badge.svg)](https://github.com/xairon/ve_nice-proxy/actions/workflows/ci.yml) ![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue) ![Licence MIT](https://img.shields.io/badge/licence-MIT-green) ![Dépendances 0](https://img.shields.io/badge/dépendances-0-brightgreen)

Brancher un compte **Venice** (abonnement Pro) sur vos outils d'IA — OpenCode, Hermes, Codex CLI, Claude Code, Open WebUI, OmniRoute, tout client « OpenAI-compatible » — par un petit pont local, en utilisant les modèles « sans pièce » (illimités avec Pro).

> ## ⚠️ À lire avant tout : conditions d'utilisation de Venice
> Ce projet fait utiliser **le cookie de session web** de votre compte par un programme. Les conditions d'utilisation de Venice **interdisent l'usage programmatique** du compte web : l'API officielle (payante à l'usage) est le chemin prévu. **Votre compte peut être suspendu.** Utilisez-le à vos risques, avec un compte dont vous acceptez de risquer l'accès, à faible cadence (le pont plafonne à 20 requêtes par minute par défaut). Les auteurs n'ont aucun lien avec Venice et ne donnent aucune garantie (licence MIT, voir `LICENSE`). Détails : [docs/SECURITE.md](docs/SECURITE.md).

## En bref

```bash
git clone https://github.com/xairon/ve_nice-proxy && cd ve_nice-proxy
./venice-setup quickstart      # cookie > service > état > configuration d'un client
```

Le pont écoute ensuite sur `127.0.0.1:8700` et sert une API OpenAI-compatible. Le **tool calling** (lire, écrire, lancer) est **émulé** dans le prompt, pas natif : comprendre pourquoi et le tester → [docs/OUTILS.md](docs/OUTILS.md).

## À quoi ça sert

L'API publique de Venice est facturée à l'usage. L'abonnement Pro donne, **sur le site**, des modèles illimités (ceux qui n'affichent pas de pièce dans le sélecteur). Le pont permet à vos outils de développement d'utiliser ces modèles comme s'ils parlaient à une API OpenAI. Il :

1. fabrique un jeton Clerk de 60 s à partir du cookie `__client` de votre compte (et le renouvelle),
2. parle à `outerface.venice.ai`, le service que le site utilise,
3. expose une API **OpenAI-compatible** locale (`/v1/chat/completions`, `/v1/models`, flux SSE), avec des **appels d'outils émulés** (les définitions d'outils passent dans le prompt, la réponse JSON est transformée en `tool_calls`), et le **multimodal** : vision, PDF et **OCR**, audio, génération et édition d'images, voix, embeddings, recherche web ([docs/MULTIMODAL.md](docs/MULTIMODAL.md)),
4. **refuse** les modèles payants (HTTP 403), plafonne le débit, et surveille votre solde de crédits.

## Architecture

```mermaid
flowchart LR
  subgraph clients [Vos outils]
    OC[OpenCode]
    HE[Hermes]
    OW[Open WebUI]
    CX[Codex CLI]
    CC[Claude Code]
    AI[aider, Cline, Continue, curl...]
  end
  OR["OmniRoute<br/>(facultatif : alias, clés, plafonds,<br/>traduction /v1/responses et /v1/messages)"]
  P["Pont venice_pont.py<br/>127.0.0.1:8700<br/>liste blanche, 20 req/min,<br/>alerte solde, /health"]
  V["outerface.venice.ai<br/>(abonnement Pro)"]
  CL["clerk.venice.ai<br/>(jeton de 60 s)"]
  OC -->|"clé du pont"| P
  AI --> P
  HE --> OR
  OW --> OR
  CX -->|"/v1/responses"| OR
  CC -->|"/v1/messages"| OR
  OR --> P
  P --> V
  P -.->|"cookie __client"| CL
```

Version texte :

```
 OpenCode / aider / curl ─────────────────────────┐
 Hermes / Open WebUI / Codex / Claude Code ─► OmniRoute (facultatif) ─► pont 127.0.0.1:8700 ─► outerface.venice.ai
                                              alias, clés, plafonds     liste blanche, 20 req/min,   (jeton Clerk miné depuis
                                                                         alerte solde, /health        le cookie __client)
```

Deux chemins existent côté Venice, que le pont choisit selon le modèle :

| Route Venice | Modèles | Contexte utile |
|---|---|---|
| Chat classique | Qwen 3.8 27B, Venice Uncensored 1.2, Gemma 4 Uncensored, GLM 4.7 Heretic, Role Play, Aion 3.0 | **~39 000 jetons** (au-delà : début tronqué en silence) |
| « Agents » | DeepSeek V4.1 Flash Uncensored, Kimi K2.5 | 524 288 (DeepSeek) ou 262 144 (Kimi), dont ~15 000 de prompt imposé par Venice |

## Prérequis

- **Python 3.9 ou plus**, **aucune dépendance** (bibliothèque standard seule).
- Pour tourner en service : Linux avec **systemd utilisateur**, ou **Docker** (`docker-compose.yml`). Ailleurs (macOS, Windows, essai rapide) : `python3 venice-setup run` au premier plan.
- Un **compte Venice Pro** et son cookie `__client` ([docs/COOKIE.md](docs/COOKIE.md)).
- Facultatif : OmniRoute (passerelle de modèles) pour Hermes, Open WebUI, Codex CLI, Claude Code.

## Démarrage rapide

```bash
git clone https://github.com/xairon/ve_nice-proxy && cd ve_nice-proxy
python3 venice-setup quickstart      # login (cookie en saisie masquée) > service > état > configuration d'un client
```

`quickstart` enchaîne les quatre étapes (il accepte `--cookie-fichier`, `--dry-run`, `--harnais opencode --appliquer`). Étape par étape :

```bash
python3 venice-setup login                          # guide + saisie masquée du cookie __client, validation, écriture en 600
python3 venice-setup install                        # service systemd utilisateur (--dry-run pour voir sans rien faire)
python3 venice-setup run                            # ... ou : pont au premier plan, sans systemd (macOS, Windows, essai)
python3 venice-setup status                         # santé du pont, cookie, crédits
python3 venice-setup harness opencode --appliquer   # ajoute le fournisseur dans opencode.json (sauvegarde .bak-*)
```

**Docker** (après `login`) : `docker compose up -d --build`, puis `curl -s http://127.0.0.1:8700/health`. Le conteneur ne publie que sur `127.0.0.1`.

**Sans OmniRoute** : le pont suffit à OpenCode, aider, Continue, Cline, curl et tout client OpenAI-compatible. OmniRoute n'est utile que pour Codex CLI et Claude Code (API Responses et Messages) ou pour des alias et des clés par client.

Windows : les tests du pont passent sur le runner Windows de la CI (28/10/2026), mais l'auteur n'a pas de machine Windows : `python venice-setup run` au premier plan est le chemin à tenter, un retour est le bienvenu.

## Documentation

| Document | Contenu |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | Installation pas à pas, plusieurs comptes, désinstallation |
| [docs/COOKIE.md](docs/COOKIE.md) | Récupérer le cookie `__client` (Chrome, Firefox), durée de vie, renouvellement |
| [docs/MODELES.md](docs/MODELES.md) | Modèles gratuits (sans pièce) et payants, contextes mesurés, lequel choisir |
| [docs/OUTILS.md](docs/OUTILS.md) | Tool calling émulé : pourquoi pas natif, garde-fous, comment le tester |
| [docs/HARNESS.md](docs/HARNESS.md) | Chaque client : état **testé / non testé**, configuration exacte |
| [docs/OMNIROUTE.md](docs/OMNIROUTE.md) | Alias, clients, bogue du masqueur de secrets (3.8.52) et réglage |
| [docs/SECURITE.md](docs/SECURITE.md) | Risque CGU, plafonds, liste blanche, alerte solde, où vivent les secrets |
| [docs/DEPANNAGE.md](docs/DEPANNAGE.md) | 401, 403, 429, 503, cookie expiré, contexte tronqué, doublons, mémoire… |
| [docs/MULTIMODAL.md](docs/MULTIMODAL.md) | Images en entrée et en sortie, fichiers, voix : routes, formats, coûts mesurés |
| [docs/LIMITES.md](docs/LIMITES.md) | Ce qui n'est **pas** pris en charge |
| [docs/EXEMPLE.md](docs/EXEMPLE.md) | Exemple de bout en bout |
| [pont/ROUTES.md](pont/ROUTES.md) | Routes Venice relevées et champs de requête |
| [pont/bench-2026-10-28.md](pont/bench-2026-10-28.md) | Banc de mesures du 28/10/2026 |
| [CONTRIBUER.md](CONTRIBUER.md) · [CHANGELOG.md](CHANGELOG.md) | Contribuer, historique |

## Commandes

| Commande | Rôle |
|---|---|
| `login [--profil P] [--cookie-fichier F] [--dry-run]` | enregistre le cookie, valide auprès de Clerk (aucun appel payant) |
| `install [--profil P] [--dry-run]` | écrit l'unité systemd utilisateur et la démarre |
| `uninstall [--profil P] [--purger] [--dry-run]` | retire le service ; `--purger` efface aussi cookie et clé |
| `status [--profil P]` | santé, jours restants du cookie, crédits, débit détecté (code retour 1 si problème) |
| `models [--pont]` | modèles sans pièce / payants ; `--pont` liste ce que sert votre pont |
| `harness NOM [--modele M] [--appliquer]` | configuration pour un client (`opencode`, `openai`, `omniroute`, `hermes`, `openwebui`, `aider`, `cline`, `continue`, `codex`, `claude-code`) |
| `profils` | liste les profils (un profil = un compte = un pont) |

Tests : `python -m pytest tests pont/tests` (222 tests, aucun appel réseau).

## Ce qui n'est pas pris en charge

Génération vidéo ou musique, édition d'image, audio ou vidéo en entrée d'un modèle, personnages, mémoire Venice : voir [docs/LIMITES.md](docs/LIMITES.md). Le **multimodal** (vision, fichiers, génération d'images, synthèse et transcription vocales) fonctionne : voir [docs/MULTIMODAL.md](docs/MULTIMODAL.md). Le **tool calling natif** n'est pas exposé par le chemin web : les outils sont émulés, avec une relance corrective si le modèle appelle un outil natif de Venice ([docs/OUTILS.md](docs/OUTILS.md)).

## Arborescence

```
venice-setup          CLI (Python, bibliothèque standard seule)
pont/                 le pont (venice_pont.py), ses tests, ROUTES.md, bancs de mesure
gabarits/             unité systemd, env.example, gabarits OmniRoute
docs/                 la documentation
tests/                tests du CLI
```

Aucun secret dans ce dépôt : cookie et clé du pont vivent dans `~/.config/venice-setup/<profil>/venice.env` (mode 600, dossier 700). Licence : MIT.
