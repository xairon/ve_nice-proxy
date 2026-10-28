# Contribuer

Merci de votre intérêt. Le projet est petit et volontairement sans dépendance (bibliothèque standard seule, CLI et pont).

## Règles

1. **Test d'abord.** Tout correctif ou toute fonction arrive avec son test (`tests/` pour le CLI, `pont/tests/` pour le pont). Les tests n'appellent **jamais** le réseau ni Venice, et n'écrivent que dans `tmp_path` (le fixture `vs` de `tests/test_cli.py` redirige `VENICE_SETUP_HOME`, `VENICE_SETUP_SYSTEMD` et `VENICE_SETUP_OPENCODE`).
2. **Aucun secret** dans le code, les tests, les journaux, les issues, les captures. Un test (`test_aucun_secret_dans_la_sortie_des_harnais`) vérifie que le CLI n'affiche jamais le cookie ni la clé : ne le contournez pas.
3. **Une opération destructrice ne cible jamais un chemin réel dans un test** (`uninstall --purger` supprime un dossier : le tester sur `tmp_path`).
4. **Rien qui débite des crédits** par défaut : toute route ou fonction susceptible de coûter doit être refusée par la liste blanche tant que l'utilisateur ne l'a pas demandée explicitement.
5. **Mesurer avant d'affirmer** : les chiffres de la documentation (contextes, débits) viennent de bancs reproductibles (`pont/bench_limites.py`) avec date et version. Marquez *testé* / *non testé* honnêtement dans [docs/HARNESS.md](docs/HARNESS.md).
6. **Français**, code et commentaires compris, sauf mot technique consacré.

## Mettre en place l'environnement de test

```bash
python3 -m venv .venv && .venv/bin/pip install pytest ruff
.venv/bin/python -m pytest tests pont/tests -q
```

## Proposer un changement

1. Ouvrez une issue (ou une discussion) décrivant le problème, sans secret.
2. Une branche par sujet, de petits commits cohérents avec un message explicite.
3. `pytest` vert, documentation et [CHANGELOG.md](CHANGELOG.md) à jour.
4. Avant de pousser : relire le diff **et** rechercher les secrets (voir [docs/SECURITE.md](docs/SECURITE.md)).

## Ajouter un client (harness)

Ajoutez une entrée à `HARNAIS` dans `venice-setup` (état commençant par `TESTÉ` ou `NON TESTÉ`), la branche d'affichage dans `cmd_harness`, un test, et la section correspondante dans `docs/HARNESS.md`. Ne marquez `TESTÉ` que ce qui a vraiment tourné, avec la version du client.

## Mettre à jour la liste des modèles sans pièce

Elle est relevée à la main dans le sélecteur de venice.ai (pièce = payant). Modifier `GRATUITS` dans `pont/venice_pont.py`, `docs/MODELES.md`, la sortie de `venice-setup models`, et noter la date. Ne jamais ajouter un modèle sans avoir vérifié l'absence de débit (voir `docs/MODELES.md`).
