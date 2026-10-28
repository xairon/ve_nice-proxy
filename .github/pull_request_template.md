## Ce que change cette PR

## Vérifications

- [ ] `python -m pytest -q` passe (aucun appel au vrai Venice dans les tests)
- [ ] `ruff check .` et `python tools/scan_secrets.py --historique` passent
- [ ] Une fonction qui parle à Venice est documentée avec sa **mesure de coût** (solde avant et après) dans `docs/`
- [ ] Aucun secret, aucune adresse ou chemin personnel
