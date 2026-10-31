# OmniRoute : alias, clients et bogue du masqueur

[OmniRoute](https://github.com/diegosouzapw/OmniRoute) est une passerelle de modèles (une API compatible OpenAI devant plusieurs fournisseurs). Elle est **facultative** : le pont suffit à OpenCode, aider ou curl. Elle apporte :

- des **alias** d'usage (`ven-qwen-nc` au lieu de `qwen-3-8-27b`) avec repli entre modèles ;
- **une clé par client**, limitée à certains alias, avec un plafond de requêtes (20 par minute) : on lit la consommation de chacun et on coupe un client sans toucher aux autres ;
- la **traduction de formats** : `/v1/responses` (Codex CLI) et `/v1/messages` (Claude Code) sont convertis vers *chat completions* — vérifié le 28/10/2026 sur OmniRoute 3.8.52. Depuis le 31/10/2026 le pont les expose lui-même : OmniRoute n'est plus nécessaire pour ces deux clients ;
- un tableau de bord et un journal des appels.

Version testée : **3.8.52**. Les gabarits `gabarits/omniroute/*.exemple.yaml` décrivent la configuration voulue (nœud, alias, clients) ; ce sont des documents de référence — le dépôt ne contient pas d'outil qui les applique : reproduisez-les dans le tableau de bord d'OmniRoute.

## 1. Déclarer le pont comme fournisseur

Dans OmniRoute : fournisseur de type **openai-compatible**, préfixe `ven`, URL `http://<hôte du pont>:8700/v1` (depuis un conteneur Docker en réseau pont, ce n'est pas `127.0.0.1`), clé = la valeur de `VENICE_PONT_CLE`.

> Le préfixe **`venice` est réservé** par OmniRoute (son fournisseur natif Venice, payant à l'usage via l'API officielle). Utilisez `ven`.

## 2. Alias recommandés (sans pièce seulement)

| Alias | Cible | Usage |
|---|---|---|
| `ven-qwen-nc` | `ven/qwen-3-8-27b` | généraliste (contexte ~39k) |
| `ven-chat` | `ven/venice-uncensored-1-2` | discussion |
| `ven-kimi` | `ven/kimi-k2-5` | agents de code, grande fenêtre (262k) |
| `ven-deepseek-nc` | `ven/deepseek-v4-1-flash-uncensored` | très grande fenêtre (524k) ; piètre agent de code |
| `ven-agent` | Kimi K2.5 → Qwen 3.8 27B → un modèle d'un autre fournisseur | repli pour les agents de code |

**Ne mettez aucun modèle payant dans un alias** : le pont les refuse (403) et, si vous l'aviez autorisé, ils débiteraient vos crédits. Un essai du 28/10/2026 avec trois alias payants a coûté 39 crédits avant correction.

## 3. Un client = une clé

Créez une clé par outil (OpenCode, Hermes, Open WebUI…), avec :

- les **alias autorisés** (la liste ci-dessus, pas plus) ;
- **20 requêtes par minute** au plus : un agent en boucle ne doit pas donner au compte Pro un motif régulier de robot ;
- les **connexions autorisées** limitées à `ven` (et au fournisseur de repli éventuel).

Vérification faite en déploiement : un alias non autorisé répond **403**, `GET /v1/models` ne liste que les alias autorisés.

## 4. Bogue du masqueur de secrets d'OmniRoute 3.8.52 (arguments d'outil dupliqués)

**Symptôme** : un agent de code qui écrit un fichier long (appel d'outil avec de gros arguments) échoue avec un JSON invalide : les arguments de l'appel d'outil sont **ré-émis en double** dans le flux. Le pont direct n'est pas touché ; le même agent via OmniRoute l'est.

**Cause** (mesurée, banc de reproduction avec un faux serveur) : le filtre `credential-masker` d'OmniRoute 3.8.52, qui masque les secrets dans les réponses en flux, travaille sur une fenêtre de 512 caractères et ré-émet le début des arguments d'outil au-delà. Bogue amont, corrigé dans la 3.8.53 (PR #18027 du projet), **non publiée au 28/10/2026**. Il touche tous les clients qui font passer des arguments d'outil de plus de 512 caractères, pas seulement Venice.

**Réglage** — couper le masqueur **dans la base** d'OmniRoute :

```bash
curl -X PATCH http://127.0.0.1:20128/api/settings \
  -H "Authorization: Bearer <jeton d'administration>" -H 'Content-Type: application/json' \
  -d '{"credentialRedactionEnabled": false}'
```

- La variable d'environnement `CREDENTIAL_REDACTION_ENABLED=false` **ne suffit pas** : le code évalue « réglage en base OU variable », donc un réglage en base resté vrai l'emporte (voir `gabarits/omniroute/compose.exemple.yml`).
- Alternative sans toucher au réglage global : l'en-tête de requête `x-omniroute-disabled-guardrails: credential-masker`.
- **Retour arrière** : `{"credentialRedactionEnabled": true}` par la même requête. À réexaminer à la sortie de la 3.8.53 (remettre à vrai).
- Contrepartie : sans masqueur, un secret qu'un modèle écrirait dans sa réponse n'est plus masqué. Réservez ce réglage à une instance personnelle.
- Alternative : brancher l'agent directement sur le pont (`venice-direct` dans OpenCode).

Vérification après réglage : écrire par l'agent un fichier de 120 à 150 lignes via un alias `ven-*` et relire le fichier (essai du 28/10/2026 : exact, avec OpenCode via `ven-qwen-nc` et `ven-agent`).

## 5. Autres points de vigilance

- OmniRoute **borne** parfois la fenêtre annoncée au plus petit contexte des cibles d'un alias de repli : un alias qui mélange Kimi (262k) et Qwen (39k) peut être limité à 39k.
- Les alias `ven-*` ne doivent pas avoir de repli vers un modèle *payant* du même fournisseur : `repli: interdit` pour les alias à cible unique.
- Codex CLI affiche « Model metadata … not found » pour un alias : sans conséquence.
- Claude Code suppose 200k de contexte pour un alias inconnu : choisissez un alias à grande fenêtre (`ven-kimi`).
