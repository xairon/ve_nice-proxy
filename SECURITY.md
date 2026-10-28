# Politique de sécurité

## Signaler une vulnérabilité

Ouvrez un **avis de sécurité privé** (onglet « Security » > « Report a vulnerability » du dépôt GitHub). N'ouvrez pas d'issue publique pour une faille.
Ne joignez **jamais** votre cookie `__client`, votre clé du pont ou un jeton : décrivez le problème avec des valeurs fictives.

On répond sous une semaine, en bonne volonté (projet personnel, sans engagement de délai).

## Ce qui est dans le périmètre

- le pont `pont/venice_pont.py` (authentification par clé, refus des modèles payants, plafonds, téléchargement d'images par URL, lecture des corps de requête) ;
- le CLI `venice-setup` (écriture des secrets en 600, génération des unités, `--purger`) ;
- l'image Docker et `docker-compose.yml`.

## Ce qui n'en fait pas partie

- Le risque connu et assumé d'**usage programmatique d'un compte web**, interdit par les conditions de Venice : voir [docs/SECURITE.md](docs/SECURITE.md). Un compte suspendu n'est pas une vulnérabilité du projet.
- Un pont exposé sur Internet ou sur un réseau non fiable : il est conçu pour `127.0.0.1` ou un réseau privé (le conteneur ne publie que sur `127.0.0.1`).

## Bonnes pratiques

Un compte dont vous acceptez de risquer l'accès ; la clé du pont jamais dans un dépôt ; `python tools/scan_secrets.py --historique` avant tout `git push` ; les secrets restent en 600 dans un dossier en 700.
