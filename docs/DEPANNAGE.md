# Dépannage

Commencez toujours par :

```bash
./venice-setup status              # santé, cookie, crédits
journalctl --user -u venice-pont -n 50 --no-pager     # (venice-pont-<profil> pour un autre profil)
systemctl --user status venice-pont
```

| Symptôme | Cause | Remède |
|---|---|---|
| `Pont injoignable … Connection refused` | service arrêté ou autre port | `systemctl --user start venice-pont` ; `./venice-setup profils` pour voir le port du profil ; port déjà pris : `ss -ltn \| grep 8700` |
| **401** du pont (`Unauthorized`) | clé du pont absente ou fausse | l'en-tête doit être `Authorization: Bearer <VENICE_PONT_CLE>` ; valeur dans `~/.config/venice-setup/<profil>/venice.env` ; une variable d'environnement vide dans le client est la cause la plus fréquente |
| **503** `cookie_expire` (aussi dans `/health`) | cookie `__client` mort : déconnexion, expiration, changement de mot de passe | reconnectez-vous sur venice.ai, récupérez un nouveau cookie ([COOKIE.md](COOKIE.md)), `./venice-setup login` (la clé du pont est conservée), `systemctl --user restart venice-pont` |
| **503** `clerk_injoignable` | pas d'accès à `clerk.venice.ai` (réseau, proxy, panne) | testez `curl -sI https://clerk.venice.ai` ; réessayez plus tard |
| **403** `modele_payant_refuse` | le modèle demandé n'est pas dans la liste blanche (payant ou inconnu) | utilisez un modèle de [MODELES.md](MODELES.md) ; `./venice-setup models --pont` liste ce que sert votre pont ; faute de frappe fréquente : `gemma-4-uncensored` (API) au lieu de `gemma4-uncensored` (web) |
| **403** d'OmniRoute | alias non autorisé pour cette clé cliente | ajoutez l'alias à la clé, ou utilisez un alias de la liste de `GET /v1/models` |
| **429** `plafond_pont` | plus de 20 requêtes en 60 s | attendez `Retry-After` secondes ; ne relevez pas le plafond sans comprendre ([SECURITE.md](SECURITE.md)). Un agent qui boucle : l'arrêter |
| **429** d'OmniRoute | plafond de la clé cliente | idem côté client ; couper les requêtes automatiques (titres, tags) d'Open WebUI |
| **502** `Venice 400 … Invalid request` | requête refusée par Venice | contenu multimodal (images) non pris en charge : [LIMITES.md](LIMITES.md) ; `content` doit être une chaîne |
| **502** `Venice 5xx` / timeouts | panne ou saturation chez Venice | réessayez ; le pont ne rejoue qu'une fois sur 401 |
| `crédits : … débit détecté : OUI` (`alerte`) | le solde a baissé | 1) regardez le journal du pont : des requêtes de modèle y apparaissent-elles ? 2) un modèle payant autorisé (`autoriser_debit`, `VENICE_PONT_AUTORISER_PAYANTS`) ? 3) usage direct du site ou de l'API par vous ? Puis acquittez : `curl -X POST -H "Authorization: Bearer $VENICE_PONT_CLE" http://127.0.0.1:8700/credits/acquitter` |
| Réponses **hors sujet** ou instructions « oubliées » sur un gros prompt | contexte > ~39k jetons sur le chat classique : **début tronqué sans erreur** (HTTP 200) | réduisez le contexte, bornez `limit.context` à 38 000 dans le client, ou passez à `kimi-k2-5` / `deepseek-v4-1-flash-uncensored` (route agents) |
| Fichier écrit par l'agent **invalide**, arguments d'outil **dupliqués** | bogue du masqueur de secrets d'OmniRoute 3.8.52 | [OMNIROUTE.md](OMNIROUTE.md) §4 : couper `credentialRedactionEnabled` en base, ou passer par le pont direct |
| L'agent « n'appelle pas » l'outil, répond en texte | appels d'outils émulés : certains modèles répondent en prose (Kimi K2.5, Aion 3.0) | rappelez l'outil dans la consigne, changez de modèle (`qwen-3-8-27b`) ; ou activez le repli `ven-agent` |
| DeepSeek NC : « Tool not found », rien d'écrit | il se croit limité aux outils de Venice sur la route agents | utilisez Kimi K2.5 ou Qwen 3.8 pour les agents de code |
| Claude Code répond n'importe quoi via `ven-qwen-nc` (OmniRoute) | son prompt (> 39k) est tronqué | utilisez `ven-kimi`, ou branchez Claude Code directement sur le pont avec `kimi-k2-5` |
| 400 `context_length_exceeded` / « prompt is too long » | conversation trop longue pour le chat classique (~36k estimés) ; le pont refuse au lieu de laisser Venice tronquer en silence | compactez (`/compact`), ou passez à `kimi-k2-5` / `deepseek-v4-1-flash-uncensored` ; réglage : `VENICE_PONT_CONTEXTE_CHAT` |
| 400 `api_non_configuree` | modèle `api/…` sans clé | ajoutez `VENICE_API_KEY=` au fichier de secrets et redémarrez le pont |
| `systemd utilisateur introuvable` à l'installation | macOS, Windows ou conteneur | `python3 venice-setup run` (premier plan) ou Docker : [INSTALL.md](INSTALL.md) |
| `Python 3.9 ou plus requis` | interpréteur trop ancien | installez un Python récent |
| Service tué (« killed », `oom-kill` dans le journal) | plafond de 256 Mo atteint, ou **mémoire de la machine épuisée (swap saturé)** | `journalctl --user -u venice-pont \| grep -i -E 'oom\|killed'` ; `free -m` ; libérez de la mémoire ou installez le pont sur une machine moins chargée ; le pont lui-même est léger (le plafond de 256 Mo est large ; consommation exacte non mesurée) |
| Le pont démarre puis s'arrête sans message | fichier de secrets illisible ou vide | `ls -l ~/.config/venice-setup/<profil>/venice.env` (doit être 600, propriétaire vous) ; refaire `login` |
| `Profil 'x' inconnu` | profil jamais créé (ou purgé) | `./venice-setup login --profil x` ; `./venice-setup profils` |
| `Nom de profil invalide` | caractères interdits | minuscules, chiffres, `-`, `_`, 32 max |
| `opencode.jsonc existe … fusionnez à la main` | config avec commentaires non fusionnable automatiquement | copiez à la main le bloc affiché par `harness opencode` (sans `--appliquer`) |
| Un profil de test reste dans `profils` après un échec de `login` | corrigé le 28/10/2026 (le profil n'est créé qu'après validation) | mettre à jour le dépôt |
| Codex : `Model metadata for … not found` | alias inconnu de Codex | bénin |
| Codex : échec dès le démarrage avec un fournisseur en `wire_api = "chat"` | Codex n'accepte plus *chat* | `wire_api = "responses"` via OmniRoute ([HARNESS.md](HARNESS.md)) |

## Tester le pont à la main

```bash
CLE=$(grep ^VENICE_PONT_CLE= ~/.config/venice-setup/defaut/venice.env | cut -d= -f2-)
curl -s -H "Authorization: Bearer $CLE" http://127.0.0.1:8700/health
curl -s -H "Authorization: Bearer $CLE" http://127.0.0.1:8700/v1/models
curl -s -H "Authorization: Bearer $CLE" -H 'Content-Type: application/json' http://127.0.0.1:8700/v1/chat/completions \
  -d '{"model":"qwen-3-8-27b","messages":[{"role":"user","content":"Réponds: pong"}],"max_tokens":50,"reasoning_effort":"none"}'
```

`/health` : `{"ok": true, "cookie_ok": true, "cookie_jours_restants": …, "credits": {"courant": …, "reference": …, "debit": 0, "alerte": false}}`.
