#!/usr/bin/env python3
"""Cherche des secrets ou des données personnelles dans les fichiers suivis par git (et, avec --historique, dans tout l'historique).

Sortie 0 si rien n'est trouvé, 1 sinon. Aucune valeur trouvée n'est affichée en entier (début masqué par des étoiles).
Bibliothèque standard seule.
"""
import argparse
import re
import subprocess
import sys

MOTIFS = {
    "jeton JWT": re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    "cookie __client": re.compile(r"__client=[A-Za-z0-9._%-]{30,}"),
    "cookie Clerk dans un fichier d'environnement": re.compile(r"VENICE_CLERK_CLIENT=[A-Za-z0-9._%-]{40,}"),
    "jeton Bearer": re.compile(r"Bearer [A-Za-z0-9._-]{30,}"),
    "clé d'API": re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16})\b"),
    "chemin personnel": re.compile(r"/home/(?!user\b|runner\b|pont\b)[a-z][a-z0-9_-]*/"),
    "adresse tailnet": re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
    "nom de réseau privé": re.compile(r"[a-z0-9-]+\.ts\.net\b|\btaile0aeb9\b"),
    "adresse électronique": re.compile(r"\b[\w.+-]+@(?!example\.)[\w-]+\.[a-z]{2,}\b", re.I),
}
AUTORISES = {"100.64.0.1", "noreply@example.invalid"}   # valeurs d'exemple volontaires
EXCLUS = {"tools/scan_secrets.py", "tests/test_scan_secrets.py"}


def masque(valeur):
    return valeur[:4] + "*" * min(12, max(0, len(valeur) - 4))


def trouver(texte):
    for nom, motif in MOTIFS.items():
        for m in motif.finditer(texte):
            if m.group(0) not in AUTORISES:
                yield nom, m.group(0)


def scanner_arbre(racine="."):
    fichiers = subprocess.run(["git", "ls-files"], cwd=racine, capture_output=True, text=True, check=True).stdout.split("\n")
    trouvailles = []
    for f in filter(None, fichiers):
        if f in EXCLUS:
            continue
        try:
            with open(f"{racine}/{f}", encoding="utf-8") as fh:
                contenu = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        for n, ligne in enumerate(contenu.splitlines(), 1):
            trouvailles += [(f"{f}:{n}", nom, v) for nom, v in trouver(ligne)]
    return trouvailles


def scanner_historique(racine="."):
    sortie = subprocess.run(["git", "log", "-p", "--all", "--format=commit %h", "--no-color"], cwd=racine,
                            capture_output=True, text=True, check=True, errors="replace").stdout
    commit, fichier, trouvailles = "?", "?", []
    for ligne in sortie.splitlines():
        if ligne.startswith("commit "):
            commit = ligne[7:]
        elif ligne.startswith("+++ b/"):
            fichier = ligne[6:]
        elif ligne.startswith("+") and not ligne.startswith("+++") and fichier not in EXCLUS:
            trouvailles += [(f"{commit}:{fichier}", nom, v) for nom, v in trouver(ligne[1:])]
    return trouvailles


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--historique", action="store_true", help="scanne aussi toutes les lignes ajoutées de l'historique")
    ap.add_argument("--racine", default=".")
    a = ap.parse_args(argv)
    trouvailles = scanner_arbre(a.racine) + (scanner_historique(a.racine) if a.historique else [])
    for ou, nom, valeur in trouvailles:
        print(f"{ou}: {nom} : {masque(valeur)}", file=sys.stderr)
    print(f"{len(trouvailles)} trouvaille(s) ({'arbre et historique' if a.historique else 'arbre'}).")
    return 1 if trouvailles else 0


if __name__ == "__main__":
    sys.exit(main())
