# venice-setup — Venice session proxy

Brancher un compte **Venice** (abonnement Pro) sur vos outils d'IA (OpenCode, Hermes, OmniRoute, tout client OpenAI-compatible), le plus simplement possible, avec les modèles « sans pièce » (illimités avec Pro).

> ## ⚠️ Avertissement CGU : à lire avant d'utiliser
> Ce projet fait utiliser **le cookie de session web** de votre compte par un programme. Les conditions d'utilisation de Venice **interdisent l'usage programmatique** du compte web (l'API officielle, payante, est le chemin prévu). Votre compte **peut être suspendu**. Utilisez-le à vos risques, avec un compte dont vous acceptez de risquer l'accès, à faible cadence (le pont plafonne à 20 requêtes/minute par défaut). Les auteurs n'ont aucun lien avec Venice et ne garantissent rien. Licence : MIT (voir `LICENSE`), sans garantie.

## Pourquoi un pont ?
L'API publique de Venice est facturée à l'usage. L'abonnement Pro donne accès, sur le site, à des modèles « sans pièce » (illimités). Mesure du 28/10/2026 : `api.venice.ai` refuse le jeton de session (401). Le pont :
1. **mint** un jeton Clerk de 60 s depuis le cookie `__client` (et le renouvelle),
2. parle à `outerface.venice.ai` (le chemin utilisé par le site), que ce jeton ouvre,
3. expose une API **OpenAI-compatible** locale (`/v1/chat/completions`, `/v1/models`, flux SSE rejoué), avec **appels d'outils émulés** (définitions dans le prompt, réponse JSON retransformée en `tool_calls`).

```
 OpenCode / Hermes / aider ... ──► OmniRoute (facultatif) ──► pont local 127.0.0.1:8700 ──► outerface.venice.ai
        (clé du pont)                 alias + plafonds         liste blanche, 20 req/min,     (jeton Clerk miné
                                                                alerte solde, health          depuis le cookie)
```

## Démarrage rapide
```
./venice-setup login          # guide pour récupérer le cookie __client, saisie masquée, validation, écriture en 600
./venice-setup install        # service utilisateur systemd (--dry-run pour voir sans rien faire)
./venice-setup status         # santé du pont, cookie, crédits
./venice-setup models         # sans pièce / payants
./venice-setup harness opencode --appliquer   # fusionne le fournisseur dans opencode.json (sauvegarde .bak-*)
./venice-setup harness openai                 # variables OPENAI_BASE_URL / OPENAI_API_KEY
```
Prérequis : Python 3.9+, `requests` (`pip install --user requests`), systemd utilisateur. Tests : `python -m pytest tests pont/tests`.

### Récupérer le cookie `__client`
Connectez-vous sur venice.ai, outils de développement (F12) > Application/Stockage > Cookies > `https://venice.ai`, copiez la valeur de `__client` (commence par `eyJ`). Valable environ un an. Cookie mort : `/health` répond 503 `cookie_expire` ; reconnectez-vous et relancez `venice-setup login`.

### Plusieurs comptes
Un profil = un compte = un pont (port suivant) : `venice-setup login --profil perso`, `install --profil perso`. Chaque profil a son dossier `~/.config/venice-setup/<profil>/` et son service `venice-pont-<profil>`. `venice-setup profils` les liste. Rappel : plusieurs comptes automatisés multiplient le risque CGU.

### Désinstaller / retour arrière
`./venice-setup uninstall` retire le service ; `--purger` efface aussi cookie et clé du pont. Chaque fichier modifié (`opencode.json`, unité) est d'abord sauvegardé en `.bak-AAAAMMJJ-HHMMSS`.

## Modèles
**Sans pièce** (illimités avec Pro, relevés dans le sélecteur de venice.ai le 28/10/2026, 0 crédit débité aux bancs) : `qwen-3-8-27b`, `venice-uncensored-1-2`, `gemma4-uncensored`, `olafangensan-glm-4.7-flash-heretic`, `venice-uncensored-role-play`, `aion-labs-aion-3-0`, et en route « agents » `deepseek-v4-1-flash-uncensored`, `kimi-k2-5`.
**Avec pièces (débités)** : GLM 5.2/5.3, Kimi K2.7 Code, DeepSeek V4.1 Flash (chat), Aion 3.5, Qwen 3.6 Plus, Grok 4.6, Claude Fable 5.1… Le pont les **refuse** (403 `modele_payant_refuse`). Cette liste change : revérifier. Détails : `pont/bench-2026-10-28.md`.

## Limites mesurées (28/10/2026, un échantillon par mesure)
- Chat classique : contexte utile **~39k jetons** (au-delà : début tronqué en silence, HTTP 200).
- Route agents : fenêtre **524 288** (DeepSeek NC) ou **262 144** (Kimi K2.5) ; ~15k jetons de prompt imposés par Venice ; contexte compacté côté serveur au-delà de ~250k ; température et top_p ignorés.
- Pas de comptage de jetons (`usage` à zéro en chat classique), pas de vrai flux (réponse rejouée en SSE).
- Appels d'outils émulés : un modèle peut répondre en texte au lieu du JSON demandé.

## Garde-fous
Liste blanche des modèles sans pièce (variable `VENICE_PONT_GRATUITS`) ; 20 requêtes/minute au total (`VENICE_PONT_MAX_PAR_MIN`, 429 + `Retry-After` au-delà) ; lecture du solde toutes les 10 min, `/health` expose `credits.alerte` si le solde baisse (débit imprévu ; acquitter par `POST /credits/acquitter`) ; écoute locale par défaut (`127.0.0.1`) ; clé du pont obligatoire ; services plafonnés à 256 Mo.

## Clients (honnêteté : testé / non testé)
| Client | État | Commande |
|---|---|---|
| OpenCode | **testé** (création de fichiers + tests avec `kimi-k2-5`) | `harness opencode --appliquer` |
| OpenAI générique (curl, SDK) | **testé** | `harness openai` |
| OmniRoute (fournisseur custom + alias) | **testé** en 3.8.52 | `harness omniroute`, gabarits `gabarits/omniroute/` |
| Hermes Agent | **testé** | `harness hermes` |
| aider, Cline, Continue, Open WebUI | **non testé** (réglage « OpenAI-compatible » générique) | `harness aider` etc. |
| Codex CLI | **non testé, probablement incompatible** : d'après des guides tiers, il exige l'API Responses, que le pont n'expose pas | `harness codex` |
| Claude Code | **non testé** : parle l'API Anthropic ; passer par un routeur comme [claude-code-router](https://github.com/musistudio/claude-code-router), dont le fonctionnement actuel est à vérifier dans son README | `harness claude-code` |

## Modules optionnels (désactivés par défaut)
- Recherche web, lecture de page, recherche X : le pont accepte les champs `web_search`, `web_scrape`, `x_search` dans la requête (chat classique). Non activés d'office.
- **Vision (image en entrée) : non prise en charge** — le pont ne garde que le texte des messages (`construire_corps_venice`). À explorer.
- Images, voix, transcription : routes non cartographiées (`pont/ROUTES.md`), **à explorer**, rien de lancé (risque de débit).

## Bugs connus
- **OmniRoute 3.8.52** : le masqueur de secrets des réponses ré-émet des arguments d'outil au-delà de 512 caractères (JSON invalide, écritures longues cassées). Corrigé en 3.8.53. Contournement : couper `credentialRedactionEnabled` **en base** (`PATCH /api/settings`), la variable d'environnement seule ne suffit pas (`gabarits/omniroute/compose.exemple.yml`), ou envoyer l'en-tête `x-omniroute-disabled-guardrails: credential-masker`. Sinon utiliser le fournisseur direct (`harness opencode`).
- Gabarit OmniRoute : le préfixe de fournisseur `venice` est réservé ; utiliser `ven`.

## Arborescence
```
venice-setup          CLI (Python, bibliothèque standard)
pont/                 le pont (venice_pont.py), tests, ROUTES.md (routes relevées), bancs
gabarits/             service systemd, env.example, gabarits OmniRoute
tests/                tests du CLI
```
Aucun secret dans ce dépôt : cookie et clé du pont vivent dans `~/.config/venice-setup/<profil>/venice.env` (600).
