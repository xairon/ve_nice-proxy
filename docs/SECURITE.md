# Sécurité, risques et garde-fous

## 1. Le risque principal : les conditions d'utilisation de Venice

Le pont fait agir **le cookie de session web** de votre compte comme un navigateur. Les conditions d'utilisation de Venice interdisent l'usage programmatique du compte web (le chemin prévu est l'API officielle, payante). Conséquences possibles : **suspension du compte**, perte de l'abonnement et des crédits. Ce risque n'est pas technique : aucun réglage ne le supprime. Il se réduit en :

- utilisant un compte dont l'accès n'est pas vital ;
- gardant un débit faible et humain (le pont plafonne à 20 requêtes/minute ; ne pas relever ce plafond) ;
- évitant les boucles automatiques sans limite et les rafales (pas de repli automatique en cascade sur ce compte) ;
- n'utilisant pas plusieurs comptes ni le partage entre personnes ;
- renonçant en cas de doute à ce projet et prenant l'API officielle.

Le pont ne contourne aucune protection anti-robot : il n'ajoute que les en-têtes d'un navigateur ordinaire.

## 2. Garde-fous intégrés

| Garde-fou | Effet | Réglage |
|---|---|---|
| **Liste blanche** de modèles sans pièce | un modèle absent de la liste est refusé : HTTP 403 `modele_payant_refuse` | `VENICE_PONT_GRATUITS` ; `"autoriser_debit": true` dans une requête ou `VENICE_PONT_AUTORISER_PAYANTS=1` pour passer outre (**débite des crédits**) |
| **Plafond de débit** | au-delà de 20 requêtes sur 60 s (tous clients confondus) : 429 `plafond_pont` + `Retry-After` | `VENICE_PONT_MAX_PAR_MIN` |
| **Alerte solde** | le solde est relu toutes les 10 minutes ; s'il baisse de 0,5 crédit ou plus sous la référence, `/health` expose `credits.alerte: true` et `credits.debit` ; `venice-setup status` sort en code 1 | `POST /credits/acquitter` remet la référence au solde courant ; `GET /credits` force une relecture |
| **Écoute locale** | le pont écoute sur `127.0.0.1` | `VENICE_PONT_ECOUTE` |
| **Clé obligatoire** | toute requête sans `Authorization: Bearer <VENICE_PONT_CLE>` (ou `x-api-key`, format Anthropic) est refusée (401) | clé générée à `login`, conservée aux relances |
| **Garde de contexte** | une conversation trop longue pour le chat classique est élaguée ou refusée (400) au lieu d'être tronquée en silence par Venice | `VENICE_PONT_CONTEXTE_CHAT`, `VENICE_PONT_ELAGAGE=0` |
| **API officielle à part** | les modèles `api/…` ne passent par `api.venice.ai` que si `VENICE_API_KEY` est présente ; ils sont **facturés à l'usage** et échappent à la liste blanche (pas au plafond de débit) | retirer la clé du fichier coupe ce chemin |
| **Plafond mémoire** | unité systemd `MemoryMax=256M`, `Nice=10` | `gabarits/venice-pont.service.in` |

L'alerte de solde est un **détecteur après coup**, pas un frein : la liste blanche est le frein. Elle ne fait pas la différence entre un débit causé par le pont et un débit causé par votre usage direct du site Venice (images, vidéo…) ou de l'API : un solde qui baisse sans qu'aucune requête de modèle n'ait été envoyée par le pont (journal du service vide) vient d'ailleurs. Cas rencontré pendant les tests du 28/10/2026 : 260 crédits perdus en une minute, sans aucune requête d'inférence du pont.

## 3. Où vivent les secrets

| Secret | Où | Protection |
|---|---|---|
| Cookie `__client` | `~/.config/venice-setup/<profil>/venice.env` (`VENICE_CLERK_CLIENT`) | fichier 600, dossier 700, écriture atomique (créé en 600 d'emblée) |
| Clé du pont | même fichier (`VENICE_PONT_CLE`) | idem ; transmise aux clients par variable d'environnement ou `{file:…}` |
| Clé API Venice (facultative) | même fichier (`VENICE_API_KEY`) | idem ; envoyée seulement à `api.venice.ai` |
| Jeton Clerk de 60 s | mémoire du pont uniquement | jamais écrit |
| Sauvegardes `venice.env.bak-*` | même dossier (700) | 600 ; supprimez-les si vous changez de cookie |

`venice-setup` n'affiche **jamais** le cookie ni la clé ; les commandes `harness` affichent le *chemin* du fichier, pas la valeur (un test vérifie qu'aucun secret n'apparaît dans leur sortie).

### Ne jamais committer un secret

- Le dépôt ne contient aucun cookie ni aucune clé ; `gabarits/env.example` n'a que des marqueurs `<…>`.
- Ne copiez pas `venice.env` dans le dépôt, un ticket, une conversation, une capture d'écran.
- Avant chaque `git push`, relancer la recherche (adaptez le motif) : `git grep -nE 'eyJ[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}'` sur l'arbre **et** l'historique (`git log -p | grep -E …`). Un cookie qui a fuité, même supprimé ensuite, est à considérer comme compromis : déconnectez la session sur venice.ai et refaites `login`.

## 4. Exposition réseau

- Par défaut `127.0.0.1` : seules les applications de la machine atteignent le pont.
- Pour qu'une autre machine l'utilise, préférez un **VPN privé** (WireGuard, Tailscale…) et écoutez sur l'adresse de ce réseau. **Jamais sur Internet** : le pont n'a ni TLS, ni limitation d'origine, ni journal d'accès ; quiconque détient la clé utilise votre abonnement.
- Si OmniRoute ou Open WebUI sont publiés, activez leur authentification **avant** l'ouverture et vérifiez qu'un accès sans identifiants répond 401. L'interface web d'un agent de code (`opencode web`) donne un shell : mot de passe obligatoire, réseau privé seulement.
- La clé du pont est la seule barrière côté pont : régénérez-la (supprimer `VENICE_PONT_CLE` du fichier puis `login`) si vous pensez qu'elle a fuité.

## 5. Données

Vos prompts et réponses transitent par Venice (les conditions de confidentialité du produit sont celles du site, à lire) et par OmniRoute/Open WebUI s'ils sont utilisés (qui peuvent journaliser). Le pont lui-même ne journalise pas le contenu des échanges.

## 6. Signaler un problème de sécurité

Ouvrez une issue sans y mettre de secret ou écrivez au mainteneur. Si un cookie est exposé : reconnectez-vous / déconnectez la session sur venice.ai (le cookie meurt), puis `venice-setup login`.
