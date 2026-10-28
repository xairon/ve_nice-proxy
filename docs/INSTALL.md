# Installation pas à pas

Durée : 5 minutes. Tout est fait en **utilisateur normal** (pas de `sudo`).

## 1. Prérequis

```bash
python3 --version          # 3.9 ou plus (aucun module à installer)
systemctl --user status    # Linux : doit répondre (session systemd utilisateur) ; sinon voir « Sans systemd » plus bas
```

Raccourci : `python3 venice-setup quickstart` enchaîne les étapes 3 à 5 ci-dessous (et la configuration d'un client).

Pour que le service survive à la fermeture de votre session (serveur sans écran) : `loginctl enable-linger "$USER"`.

## 2. Récupérer le dépôt

```bash
git clone https://github.com/xairon/ve_nice-proxy
cd ve_nice-proxy
python3 -m pytest tests pont/tests   # facultatif ; demande pytest ; tests sans aucun appel réseau (un garde-fou le garantit)
```

## 3. Enregistrer le cookie (`login`)

```bash
./venice-setup login
```

La commande affiche le guide pour trouver le cookie `__client` ([COOKIE.md](COOKIE.md)), demande sa valeur (saisie masquée), la **valide auprès de Clerk** (aucun appel payant ; elle affiche votre solde de crédits), puis écrit `~/.config/venice-setup/defaut/venice.env` en mode 600 avec :

- `VENICE_CLERK_CLIENT` : votre cookie ;
- `VENICE_PONT_CLE` : une clé locale générée, que vos clients présenteront au pont.

Variantes : `--cookie-fichier chemin` (cookie seul dans un fichier), `--sans-verification` (hors ligne), `--dry-run` (n'écrit rien, ne crée pas de profil). Si Clerk renouvelle le cookie pendant la validation, c'est le nouveau qui est enregistré. Relancer `login` conserve la clé du pont et sauvegarde l'ancien fichier en `venice.env.bak-AAAAMMJJ-HHMMSS`.

## 4. Installer le service (`install`)

```bash
./venice-setup install --dry-run    # montre l'unité systemd et les commandes, n'écrit rien
./venice-setup install
```

Écrit `~/.config/systemd/user/venice-pont.service` (plafond mémoire 256 Mo, `Nice=10`, redémarrage sur échec), fait `daemon-reload`, `enable --now`, puis affiche l'état. Le pont écoute sur **`127.0.0.1:8700`** (local uniquement).

Sans systemd, lancer à la main :

```bash
VENICE_PONT_ENV=~/.config/venice-setup/defaut/venice.env python3 pont/venice_pont.py
```

## 5. Vérifier

```bash
./venice-setup status
./venice-setup models --pont
```

Sortie attendue de `status` :

```
Pont defaut : OK (127.0.0.1:8700)
  cookie : valide, expire dans 399.7 jours
  crédits : 545.0 (référence 545.0), débit détecté : non
```

(valeurs d'exemple). Code retour 1 si le pont est injoignable, le cookie mort ou un débit détecté.

## 6. Brancher un client

```bash
./venice-setup harness opencode --appliquer   # ou openai, hermes, omniroute, ...
```

Voir [HARNESS.md](HARNESS.md). Les modèles utilisables sans débit : [MODELES.md](MODELES.md).

## Plusieurs comptes

Un profil = un compte Venice = un pont = un port (8700, 8701, …) :

```bash
./venice-setup login --profil perso
./venice-setup install --profil perso      # service venice-pont-perso
./venice-setup status --profil perso
./venice-setup profils                     # liste : nom, adresse
```

Noms de profil : minuscules, chiffres, `-` et `_`, 32 caractères au plus. Chaque profil a son dossier `~/.config/venice-setup/<profil>/` (700) et sa clé. Rappel : plusieurs comptes automatisés multiplient le risque côté CGU.

## Désinstaller / retour arrière

```bash
./venice-setup uninstall --dry-run
./venice-setup uninstall              # arrête et supprime le service, garde cookie et clé
./venice-setup uninstall --purger     # efface aussi le dossier du profil et le retire de la liste
```

Chaque fichier modifié par `harness opencode --appliquer` est sauvegardé juste avant en `opencode.json.bak-AAAAMMJJ-HHMMSS` : pour revenir, recopier la sauvegarde.

## Variables d'environnement (facultatives)

| Variable | Rôle | Défaut |
|---|---|---|
| `VENICE_SETUP_HOME` | dossier des profils | `~/.config/venice-setup` |
| `VENICE_SETUP_SYSTEMD` | dossier des unités | `~/.config/systemd/user` |
| `VENICE_SETUP_OPENCODE` | fichier `opencode.json` visé | `~/.config/opencode/opencode.json` |
| `VENICE_PONT_ECOUTE` | adresse:port d'écoute du pont | `127.0.0.1:8700` |
| `VENICE_PONT_MAX_PAR_MIN` | plafond de requêtes par minute | `20` |
| `VENICE_PONT_GRATUITS` | liste blanche des modèles (séparés par des virgules) | modèles sans pièce relevés le 28/10/2026 |
| `VENICE_PONT_AUTORISER_PAYANTS` | `1` : accepte les modèles payants (**débite des crédits**) | non |

Écouter ailleurs que sur `127.0.0.1` (par exemple l'adresse d'un VPN privé pour qu'une autre machine du réseau utilise le pont) est possible, mais le pont n'a ni TLS ni autre protection que sa clé : ne jamais l'exposer à Internet ([SECURITE.md](SECURITE.md)).

## Sans systemd : macOS, Windows, essai rapide

```bash
python3 venice-setup login
python3 venice-setup run        # au premier plan ; Ctrl+C arrête. Le pont écoute sur 127.0.0.1:8700
```

Dans un autre terminal : `python3 venice-setup status`. Sous Windows, utilisez `python` ; les permissions 600 ne s'y appliquent pas (le dossier de votre profil utilisateur fait la protection) : n'y mettez que votre compte personnel. Windows n'a pas été essayé par l'auteur.

## Docker

```bash
python3 venice-setup login                 # écrit ~/.config/venice-setup/defaut/venice.env
docker compose up -d --build               # image python:3.12-slim, utilisateur non root, 256 Mo, 127.0.0.1:8700
curl -s http://127.0.0.1:8700/health
```

Variables facultatives : `PUID` / `PGID` (utilisateur du dossier de secrets, 1000 par défaut), `VENICE_PORT`, `VENICE_DATA` (dossier de secrets du profil). Le conteneur met à jour le cookie dans ce dossier quand Clerk le renouvelle. Récupérer la clé du pont : `grep VENICE_PONT_CLE ~/.config/venice-setup/defaut/venice.env`.
