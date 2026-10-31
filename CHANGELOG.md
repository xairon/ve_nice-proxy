# Historique

## Non publié

### Ajouté (31/10/2026 : DeepSeek sans outils)
- **`venice-delegue`** : donne des fichiers et une consigne à un modèle du pont **sans déclarer d'outil**, applique ses blocs « chercher / remplacer », lance la commande de test et renvoie les échecs au modèle (3 tours par défaut). Formats `texte` et `json` aussi. Raison : DeepSeek V4.1 Flash échoue comme agent à outils sur la route agents de Venice, mais sans outil il a corrigé le projet d'essai en une requête (4 s, 6/6 tests, 0 crédit, 31/10/2026). Garde de chemin : aucune écriture hors du dossier de travail.

### Ajouté (31/10/2026)
- **`venice-mcp`** : serveur MCP (stdio, bibliothèque standard) avec les outils `deepseek_coder` (DeepSeek écrit, le serveur applique et teste) et `deepseek_demander`. Avec la consigne `gabarits/claude-code/CLAUDE.deepseek.md`, Claude Code (ou OpenCode) confie de lui-même l'écriture du code à DeepSeek. `venice-setup harness claude-code` imprime les deux lignes d'installation. Testé en réel : Kimi a délégué la correction à DeepSeek (1 appel, 0 Edit/Write de sa part), tests verts, 28 s, 0 crédit.

### Vérifié en réel (31/10/2026)
- **aider + DeepSeek V4.1 Flash Uncensored** : sans outils, sur ce dépôt (109k jetons envoyés), renommage transversal en 66 s, 263 tests verts, 0 crédit ; kimi-k2-5 réussit aussi en 137 s. `venice-setup harness aider` imprime la recette (DeepSeek par défaut) et `gabarits/aider/aider.model.metadata.json` annonce les vraies fenêtres (500k / 250k).
- **Claude Code 2.1.312 contre le vrai Venice** (`kimi-k2-5`, pont `main`) : lecture, édition et lancement de pytest par les outils émulés, bogue corrigé, tests verts, 0 crédit. `venice-setup harness claude-code` et `docs/HARNESS.md` le disent.

### Corrigé (31/10/2026, DeepSeek V4.1 Flash et les outils)
- Cause trouvée en rejouant une vraie requête de Claude Code : sur la route agents, DeepSeek appelle les outils en **natif** ; la boucle d'agent interne de Venice ne les connaît pas (`veniceai:tool_call_generation`, outils `Unrecognized`), répond « Tool not found » au modèle et le laisse réessayer jusqu'à ~10 fois dans la même réponse avant un bilan d'échec. Le pont coupe maintenant le flux dès le premier appel natif et relance aussitôt avec la consigne corrective (deux fois au plus), avant que rien ne parte chez le client ; à défaut, un message clair remplace le bilan d'échec.
- Appels d'outil mal formés acceptés : arguments à plat à côté du nom (`{"name":"Read","file_path":"x"}`) et accolade fermante en trop.

### Corrigé (31/10/2026, relevé pendant l'essai réel)
- `venice-setup status` sans fichier de secrets disait « Pont injoignable » alors que le pont répondait : il dit maintenant que le fichier de secrets manque.
- Le pont écrit une ligne par requête dans son journal (méthode, chemin sans paramètres, code ; jamais d'en-tête ni de contenu). `VENICE_PONT_JOURNAL=0` la coupe.

### Ajouté (31/10/2026 : module de code agentique)
- **Claude Code en direct** : le pont expose l'API Messages d'Anthropic (`/v1/messages`, `/v1/messages/count_tokens`, flux SSE au format Anthropic, `tool_use`/`tool_result`, images, documents, clé en `x-api-key`). Essai réel : Claude Code 2.1.316 a écrit un fichier par l'outil `Write` émulé (réponses du modèle simulées). `venice-setup harness claude-code` pointe sur le pont.
- **Codex CLI en direct** : `/v1/responses` (flux compris, `function_call`, outils `custom` comme `apply_patch`, `local_shell`, `previous_response_id` en mémoire). Vérifié avec le SDK OpenAI ; Codex lui-même pas encore lancé en direct. `venice-setup harness codex` pointe sur le pont.
- **Outils émulés plus robustes** : formats `<tool_call>…</tool_call>` (Qwen, GLM), objet ou liste nus, bloc ```json au milieu de la prose ; clés `parameters`/`input`, noms préfixés ou en casse différente, JSON réparé (virgule finale, appel tronqué). `tool_choice` (`none`, `required`, outil imposé avec relance) et `parallel_tool_calls`.
- **Vrai flux avec outils** : la prose est relayée au fil de l'eau, seul l'appel d'outil est retenu jusqu'à être complet (avant : toute la réponse en tampon).
- **Garde de contexte** du chat classique : au-delà de ~36k jetons estimés, élagage des messages anciens (système, premier message et fin gardés) ou 400 `context_length_exceeded`, au lieu de la troncature silencieuse de Venice qui effaçait la définition des outils.
- **Alias de modèles** (`VENICE_PONT_ALIAS`) : `claude-*`, `gpt-*`, `codex-*` → `kimi-k2-5`, `claude-*haiku*` → `qwen-3-8-27b`.
- **API officielle facultative** (`VENICE_API_KEY`) : modèles `api/<id>` servis par `api.venice.ai` (conforme aux CGU, facturé), outils natifs pour les modèles qui l'annoncent, émulation sinon ; mode « API seule » sans cookie. Vérifié contre un serveur factice, pas encore contre la vraie API.
- L'historique rejoué garde la prose de l'assistant à côté de ses appels d'outil, et le nom de l'outil dans chaque résultat ; le rôle `developer` est traité comme `system`.
- Erreurs au format du client (Anthropic : `{"type":"error",…}`) ; modèle absent → 400 au lieu de 502.

### Corrigé
- Outils émulés (30/10/2026, OpenCode) : une prose avant l'appel JSON est acceptée et devient le contenu ; quand le modèle appelle un outil natif de Venice et se voit répondre « Tool not found », le pont relance une fois avec une consigne corrective qui force le format JSON. Même requête rejouée : 12/12 appels d'outil produits, écriture de fichier vérifiée de bout en bout.

## 0.1.0 — 28/10/2026 (première version publiée)

### Corrigé
- `login` : un cookie invalide ou rotatif ne provoque plus de trace d'erreur (`PermissionError`) ; Clerk qui renouvelle le cookie pendant la validation → c'est le cookie renouvelé qui est enregistré. La validation travaille dans un dossier jetable.
- `login` : un refus de Clerk ou un `--dry-run` ne laisse plus de profil créé dans `profils.json`.
- Dossier de profil créé en mode 700 (il l'était en 775 ; les fichiers étaient déjà en 600).
- Noms de profil validés (`[a-z0-9][a-z0-9_-]{0,31}`) : `..`, `a/b`… refusés (risque d'écrire ou de supprimer hors du dossier des profils).
- `uninstall --purger` retire le profil de la liste ; sans unité installée, plus d'appel `systemctl` inutile ni de message d'erreur effrayant.
- `harness codex` et `harness claude-code` : configurations réellement testées, via OmniRoute (`/v1/responses`, `/v1/messages`).

### Ajouté
- **Aucune dépendance** : le pont n'utilise plus `requests` (client HTTP standard, essayé en réel face à Venice : Clerk, chat, vision, image, voix).
- `venice-setup quickstart` (login, service, état, client), `venice-setup run` (premier plan, toutes plateformes), `--version`, message clair sans systemd.
- Docker : `Dockerfile` (non root, bibliothèque standard) et `docker-compose.yml` (127.0.0.1, 256 Mo, système de fichiers en lecture seule).
- CI GitHub Actions (tests Linux et macOS, Python 3.9 et 3.13, essai Windows, ruff, scan de secrets sur l'arbre et l'historique, build Docker), `tools/scan_secrets.py`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, modèles d'issues et de PR.
- Garde-fou de test : aucune connexion sortante possible (un test avait fait un vrai appel à Venice avec un faux jeton).
- **Multimodal** (28/10/2026, routes lues dans le code du site, chaque capacité essayée une fois, solde Venice inchangé) : vision (`content` en liste, `image_url` data URL ou https avec garde SSRF) sur 8 modèles sans pièce ; fichiers joints (partie `file`, extraction par la route `text_parser`) ; `/v1/images/generations` (6 modèles sans pièce, `b64_json`, quota Pro lu et surveillé, jamais de repli sur les crédits) ; `/v1/audio/speech` (9 voix de modèles) ; `/v1/audio/transcriptions` (Parakeet) ; `/quotas`, `/v1/images/models`, `/v1/audio/models` ; plafonds propres par catégorie ; refus des corps de plus de 32 Mo. Vidéo et musique cartographiées, non exposées (tout est payant). [docs/MULTIMODAL.md](docs/MULTIMODAL.md).
- **OCR** : `/v1/ocr`, lecture automatique d'un PDF scanné ou d'une image envoyés comme fichier (pdftoppm ou images intégrées au PDF, sans dépendance) ; **audio vers un modèle** (`input_audio` transcrit puis injecté) ; `/v1/embeddings` (bge-m3) ; `/v1/images/edits` (2 modèles sans pièce), `/v1/images/upscale` (×2, ×4), `/v1/images/remove-background` ; `web_search_options`. Matrice complète entrée/sortie dans `docs/MULTIMODAL.md`.
- Liste blanche du chat élargie : `qwen3-6-27b`, `qwen3-5-35b-a3b`, `google-gemma-4-26b-a4b-it`, `google-gemma-4-31b-it`, `qwen3-vl-235b-a22b` (0 crédit mesuré).
- Documentation complète : `docs/` (installation, cookie, modèles, harness, OmniRoute, sécurité, dépannage, limites, exemple), `CONTRIBUER.md`, ce fichier.
- Campagne de tests du 28/10/2026 : login réel, install/uninstall, status, models, profils multiples, chat, outil émulé, SSE, refus 403, Codex CLI et Claude Code via OmniRoute, Open WebUI avec authentification, essai de vision (échec, corrigé depuis : voir ci-dessus).

## Avant la 0.1.0
- Premier dépôt : CLI `venice-setup` (login, install, uninstall, status, models, harness, profils), pont OpenAI-compatible (`pont/venice_pont.py`), gabarits systemd et OmniRoute, banc de mesures.
