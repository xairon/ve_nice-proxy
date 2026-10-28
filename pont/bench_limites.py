"""Banc des limites (concurrence, contexte, débit) de deux modèles Venice par le pont.

Prudent : s'arrête au premier refus (429, 403, message de limite) sans insister.
Appelle le pont directement (pas OmniRoute), donc le plafond 20 req/min des clients n'intervient pas.
Solde lu dans la charge utile du jeton de /api/user/session (bundledCreditsUsage).
Usage : python3 bench_limites.py <modele> <concurrence|contexte|debit>   (résultats en JSON sur stdout)
"""
import base64
import json
import os
import random
import statistics
import sys
import threading
import time

import requests

import venice_pont as v

PONT = os.environ.get("VENICE_PONT_URL", "http://127.0.0.1:8700")
ENV = os.path.expanduser("~/.config/venice/venice.env")
MOTS = [m.strip() for m in open("/usr/share/dict/american-english", encoding="utf-8") if m.strip().isalpha()]


class Arret(Exception):
    """Premier signe de limite : on ne poursuit pas la phase."""


def cle_pont():
    return open(os.path.expanduser("~/.config/venice/pont-cle"), encoding="utf-8").read().strip()


def solde():
    env = v.lire_env(ENV)
    jeton = v.JetonClerk(v.SourceClerk(env["VENICE_CLERK_CLIENT"], ENV).mint)
    tok = requests.get("https://venice.ai/api/user/session", timeout=20,
                       headers={**v.EN_TETES_WEB, "Authorization": "Bearer " + jeton.obtenir()}).json()["token"]
    p = tok.split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))["bundledCreditsUsage"]["availableCredits"]


def appeler(modele, contenu, max_tokens=24):
    t0 = time.time()
    try:
        r = requests.post(PONT + "/v1/chat/completions", timeout=(10, 240),
                          headers={"Authorization": "Bearer " + cle_pont()},
                          json={"model": modele, "max_tokens": max_tokens, "temperature": 0,
                                "messages": [{"role": "user", "content": contenu}]})
        code, texte = r.status_code, r.text
    except Exception as e:  # noqa: BLE001 - toute erreur réseau est une donnée du banc
        code, texte = 0, repr(e)
    sortie, jetons = "", 0
    if code == 200:
        try:
            rep = json.loads(texte)
            sortie = rep["choices"][0]["message"]["content"] or ""
            jetons = rep["usage"]["total_tokens"]
        except (ValueError, KeyError, IndexError):
            sortie = texte[:200]
    return {"code": code, "s": round(time.time() - t0, 2), "sortie": sortie.strip()[:80], "jetons_venice": jetons,
            "erreur": "" if code == 200 else texte[:200]}


def concurrence(modele):
    res = []
    for n in (2, 4, 8, 16):
        sorties = [None] * n

        def tache(i, sorties=sorties):
            sorties[i] = appeler(modele, "Réponds seulement : ok", 8)
        fils = [threading.Thread(target=tache, args=(i,)) for i in range(n)]
        [f.start() for f in fils]
        [f.join() for f in fils]
        codes = sorted({s["code"] for s in sorties})
        lat = [s["s"] for s in sorties]
        res.append({"rafale": n, "codes": codes, "lat_min": min(lat), "lat_med": statistics.median(lat),
                    "lat_max": max(lat), "erreurs": [s["erreur"] for s in sorties if s["code"] != 200][:2]})
        print(json.dumps(res[-1], ensure_ascii=False), flush=True)
        if codes != [200]:
            res.append({"arret": f"rafale {n}"})
            break
        time.sleep(20)
    return res


def remplissage(jetons_estimes):
    rnd = random.Random(7)
    return " ".join(rnd.choice(MOTS) for _ in range(jetons_estimes * 4 // 9))  # ~9 caractères/mot, 4 car./jeton


def contexte(modele, tailles):
    res = []
    for k in tailles:
        secret = "ZEBRE-" + str(random.randint(1000, 9999))
        texte = (f"Le code secret est {secret}. Retiens-le.\n\n" + remplissage(k * 1000)
                 + "\n\nQuel est le code secret donné tout au début ? Réponds uniquement le code.")
        r = appeler(modele, texte, 24)
        r.update({"k_jetons_estimes": k, "retrouve": secret in r["sortie"]})
        res.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
        if r["code"] != 200:
            res.append({"arret": f"{k}k"})
            break
        time.sleep(8)
    return res


def debit(modele, total=60, duree=180):
    res = []
    t0 = time.time()
    for i in range(total):
        cible = t0 + i * duree / total
        time.sleep(max(0, cible - time.time()))
        r = appeler(modele, f"Réponds seulement le nombre {i}.", 8)
        res.append(r)
        if r["code"] != 200:
            print(json.dumps({"arret": f"requête {i}", **r}, ensure_ascii=False), flush=True)
            break
    lat = [r["s"] for r in res if r["code"] == 200]
    tiers = max(1, len(lat) // 3)
    return {"envoyees": len(res), "ok": len(lat), "codes": sorted({r["code"] for r in res}),
            "lat_tiers": [round(statistics.median(lat[a:a + tiers]), 2) for a in (0, tiers, 2 * tiers)] if lat else [],
            "lat_max": max(lat) if lat else None, "duree_s": round(time.time() - t0)}


if __name__ == "__main__":
    modele, phase = sys.argv[1], sys.argv[2]
    avant = solde()
    if phase == "concurrence":
        sortie = concurrence(modele)
    elif phase == "contexte":
        tailles = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [35, 40, 45, 50, 80, 120, 200]
        sortie = contexte(modele, tailles)
    else:
        sortie = debit(modele)
    print(json.dumps({"modele": modele, "phase": phase, "solde_avant": avant, "solde_apres": solde(),
                      "resultat": sortie}, ensure_ascii=False))
