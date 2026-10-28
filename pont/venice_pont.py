"""Pont OpenAI -> Venice (chemin web) pour OmniRoute.

Le jeton Clerk (60 s) est miné depuis le cookie __client ; api.venice.ai le refuse (401),
outerface.venice.ai l'accepte. Les outils sont émulés : définitions dans le prompt système,
réponse JSON {"tool_calls": [...]} retransformée en tool_calls OpenAI.
"""
import base64
import glob
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

CLERK = "https://clerk.venice.ai/v1"
CLERK_VERSION = {"__clerk_api_version": "2025-04-10"}
OUTERFACE = "https://outerface.venice.ai/api/inference/chat"
AGENTS = "https://outerface.venice.ai/api/inference/chat/agents/venice"
SESSION = "https://venice.ai/api/user/session"
API_WEB = "https://outerface.venice.ai/api"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
EN_TETES_WEB = {"User-Agent": UA, "Origin": "https://venice.ai", "Referer": "https://venice.ai/"}


# --- client HTTP minimal (bibliothèque standard seule : le pont n'a aucune dépendance) ------------------------------

class ErreurReseau(Exception):
    """Connexion impossible ou coupée."""


class DelaiDepasse(ErreurReseau):
    """Aucune réponse dans le délai."""


class ErreurHTTP(Exception):
    def __init__(self, reponse):
        super().__init__(f"HTTP {reponse.status_code}")
        self.response = reponse


class Reponse:
    def __init__(self, brute):
        self.raw = brute  # http.client.HTTPResponse ou urllib.error.HTTPError : `.headers.get_all()` lit les Set-Cookie
        self.status_code, self.headers = brute.status if hasattr(brute, "status") else brute.code, brute.headers
        self.encoding = "utf-8"  # Venice répond text/html sans charset : le décodage reste en UTF-8
        self._contenu = None

    @property
    def content(self):
        if self._contenu is None:
            try:
                self._contenu = self.raw.read()
            except (OSError, ValueError) as e:  # TimeoutError, connexion coupée, IncompleteRead
                raise _erreur_reseau(e) from None
        return self._contenu

    def lire(self):
        return self.content

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ErreurHTTP(self)

    def iter_lines(self, decode_unicode=False):
        try:
            for ligne in iter(self.raw.readline, b""):
                ligne = ligne.rstrip(b"\r\n")
                yield ligne.decode("utf-8", "replace") if decode_unicode else ligne
        except (OSError, ValueError) as e:
            raise _erreur_reseau(e) from None

    def iter_content(self, taille=65536):
        try:
            for bloc in iter(lambda: self.raw.read(taille), b""):
                yield bloc
        except (OSError, ValueError) as e:
            raise _erreur_reseau(e) from None

    def close(self):
        self.raw.close()


def _erreur_reseau(e):
    cause = getattr(e, "reason", e)
    if isinstance(cause, (socket.timeout, TimeoutError)):
        return DelaiDepasse("délai dépassé")
    return ErreurReseau(str(cause)[:200])


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _multipart(champs, fichiers):
    limite = uuid.uuid4().hex
    corps = b""
    for nom, valeur in (champs or {}).items():
        corps += f'--{limite}\r\nContent-Disposition: form-data; name="{nom}"\r\n\r\n{valeur}\r\n'.encode()
    for nom, (fichier, octets, *mime) in (fichiers or {}).items():
        corps += (f'--{limite}\r\nContent-Disposition: form-data; name="{nom}"; filename="{fichier}"\r\n'
                  f"Content-Type: {mime[0] if mime else 'application/octet-stream'}\r\n\r\n").encode() + octets + b"\r\n"
    return corps + f"--{limite}--\r\n".encode(), f"multipart/form-data; boundary={limite}"


def requete(methode, url, params=None, corps_json=None, data=None, files=None, headers=None, timeout=60,
            stream=False, suivre_redirections=True):
    """Requête HTTP(S) : Reponse (statut >= 400 compris, sans exception) ; ErreurReseau / DelaiDepasse sinon."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    entetes, corps = {"Accept-Encoding": "identity", **(headers or {})}, None
    if files:
        corps, entetes["Content-Type"] = _multipart(data, files)
    elif corps_json is not None:
        corps, entetes["Content-Type"] = json.dumps(corps_json, ensure_ascii=False).encode(), "application/json"
    elif methode == "POST":
        corps = b""
    ouvreur = urllib.request.build_opener(*([] if suivre_redirections else [_SansRedirection]))
    try:
        brute = ouvreur.open(urllib.request.Request(url, data=corps, headers=entetes, method=methode), timeout=timeout)
    except urllib.error.HTTPError as e:
        brute = e
    except (urllib.error.URLError, OSError) as e:
        raise _erreur_reseau(e) from None
    r = Reponse(brute)
    if not stream:
        r.lire()  # lit tout de suite : les erreurs réseau remontent ici
        r.close()
    return r


class Session:
    """En-têtes communs et cookies conservés d'un appel à l'autre (les Set-Cookie du serveur les mettent à jour)."""

    def __init__(self):
        self.headers, self.cookies = {}, {}

    def _appeler(self, methode, url, params=None, timeout=30, headers=None):
        entetes = {**self.headers, **(headers or {})}
        if self.cookies:
            entetes["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        r = requete(methode, url, params=params, headers=entetes, timeout=timeout)
        for brut in r.headers.get_all("Set-Cookie") or []:
            attributs = [a.strip() for a in brut.split(";")]
            nom, _, valeur = attributs[0].partition("=")
            if valeur == "" or "max-age=0" in (a.lower() for a in attributs[1:]):
                self.cookies.pop(nom.strip(), None)
            else:
                self.cookies[nom.strip()] = valeur
        return r

    def get(self, url, **kw):
        return self._appeler("GET", url, **kw)

    def post(self, url, **kw):
        return self._appeler("POST", url, **kw)


class CookieExpire(Exception):
    """Le cookie __client n'ouvre plus de session : reconnexion nécessaire sur venice.ai."""


class JetonClerk:
    def __init__(self, mint, marge=15):
        self._mint, self._marge = mint, marge
        self._jeton, self._exp, self._cookie_ok = None, 0.0, None
        self._verrou = threading.Lock()

    def obtenir(self):
        with self._verrou:
            if self._jeton and time.time() < self._exp - self._marge:
                return self._jeton
            try:
                self._jeton, self._exp = self._mint()
            except CookieExpire:
                self._jeton, self._cookie_ok = None, False
                raise
            self._cookie_ok = True
            return self._jeton

    def invalider(self):
        with self._verrou:
            self._jeton, self._exp = None, 0.0

    def etat(self):
        return {"cookie_ok": self._cookie_ok, "jeton_valide_jusqu_a": self._exp}


def _nouveau_cookie(reponse):
    """Valeur d'un Set-Cookie __client, None si Clerk ne fait pas tourner le cookie (cas mesuré le 28/10/2026)."""
    for brut in reponse.raw.headers.get_all("Set-Cookie") or []:
        nom, _, reste = brut.partition("=")
        if nom.strip() == "__client":
            return reste.split(";")[0]
    return None


def _session_web(cookie):
    s = Session()
    s.headers.update(EN_TETES_WEB)
    s.cookies["__client"] = cookie
    return s


class SourceClerk:
    """Cookie __client + appels Clerk. Écrit atomiquement une valeur renvoyée par Clerk (verrou), sans redémarrage."""

    SEUIL_JOURS = 30

    def __init__(self, cookie, fichier_env, session_factory=None):
        self.cookie, self._fichier = cookie, fichier_env
        self._fabrique = session_factory
        self._verrou = threading.Lock()
        self._meta = {"cookie_cree_le": None, "cookie_expire_le": None, "session_expire_le": None,
                      "dernier_renouvellement": None, "derniere_touche": None}

    def _session(self):
        return self._fabrique() if self._fabrique else _session_web(self.cookie)

    def _verifier(self, r, quoi):
        if r.status_code in (401, 403, 404):
            raise CookieExpire(f"{quoi} {r.status_code}")
        r.raise_for_status()

    def _client(self, s):
        r = s.get(f"{CLERK}/client", params=CLERK_VERSION, timeout=30)
        self._verifier(r, "client")
        self._noter_cookie(r)
        rep = r.json().get("response") or {}
        sid = rep.get("last_active_session_id")
        if not sid:
            raise CookieExpire("aucune session active")
        self._meta["cookie_cree_le"] = (rep.get("created_at") or 0) / 1000 or None
        self._meta["cookie_expire_le"] = (rep.get("cookie_expires_at") or 0) / 1000 or None
        for ses in rep.get("sessions") or []:
            if ses.get("id") == sid and ses.get("expire_at"):
                self._meta["session_expire_le"] = ses["expire_at"] / 1000
        return sid

    def _noter_cookie(self, reponse):
        nouveau = _nouveau_cookie(reponse)
        if not nouveau:
            return
        with self._verrou:
            if nouveau == self.cookie:
                return
            self.cookie = nouveau
            self._ecrire_fichier(nouveau)
            self._meta["dernier_renouvellement"] = time.time()

    def _ecrire_fichier(self, valeur):
        import tempfile
        chemin = os.path.expanduser(self._fichier)
        lignes = open(chemin).read().splitlines()
        sortie, vu = [], False
        for ligne in lignes:
            if ligne.startswith("VENICE_CLERK_CLIENT="):
                if not vu:
                    sortie.append("VENICE_CLERK_CLIENT=" + valeur)
                vu = True
            else:
                sortie.append(ligne)
        if not vu:
            sortie.append("VENICE_CLERK_CLIENT=" + valeur)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(chemin), suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(sortie) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, chemin)

    def mint(self):
        s = self._session()
        sid = self._client(s)
        r = s.post(f"{CLERK}/client/sessions/{sid}/tokens", params=CLERK_VERSION, timeout=30)
        self._verifier(r, "jeton")
        self._noter_cookie(r)
        jwt = r.json()["jwt"]
        p = jwt.split(".")[1]
        return jwt, float(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["exp"])

    def toucher(self):
        s = self._session()
        sid = self._client(s)
        r = s.post(f"{CLERK}/client/sessions/{sid}/touch", params=CLERK_VERSION, timeout=30)
        self._verifier(r, "touch")
        self._noter_cookie(r)
        self._meta["derniere_touche"] = time.time()

    def etat(self):
        e = dict(self._meta)
        exp = e["cookie_expire_le"]
        e["cookie_jours_restants"] = round((exp - time.time()) / 86400, 1) if exp else None
        e["cookie_bientot_expire"] = bool(exp) and e["cookie_jours_restants"] < self.SEUIL_JOURS
        e["cookie_age_jours"] = round((time.time() - e["cookie_cree_le"]) / 86400, 2) if e["cookie_cree_le"] else None
        return e


def boucle_touche(source, intervalle=3600):
    """Touche la session toutes les heures tant que le pont tourne ; les erreurs sont lues par /health."""
    while True:
        time.sleep(intervalle)
        try:
            source.toucher()
        except Exception as e:  # visible dans le journal, /health relit l'état au prochain mint
            print(f"touche Clerk en échec : {e}", file=sys.stderr, flush=True)


CONSIGNE_OUTILS = (
    "Tu disposes des outils suivants (format JSON Schema) :\n{outils}\n\n"
    "Pour appeler un ou plusieurs outils, réponds UNIQUEMENT par un objet JSON de la forme "
    '{{"tool_calls":[{{"name":"<outil>","arguments":{{...}}}}]}} sans aucun autre texte. '
    "Si aucun outil n'est nécessaire, réponds normalement en texte.\n"
    "IMPORTANT : les seuls outils disponibles sont ceux définis ci-dessus ({noms}). Ignore toute autre liste d'outils "
    "ou limite que tu pourrais connaître (génération d'images, recherche web, etc.) : pour agir, réponds par le JSON demandé."
)


def _appel_en_texte(tc):
    f = tc.get("function", {})
    try:
        args = json.loads(f.get("arguments") or "{}")
    except ValueError:
        args = f.get("arguments")
    return json.dumps({"tool_calls": [{"name": f.get("name"), "arguments": args}]}, ensure_ascii=False)


class EntreeInvalide(Exception):
    """Requête du client inacceptable (image illisible, type refusé, champ manquant) : 400."""

    statut = 400


class EntreeTropGrosse(EntreeInvalide):
    statut = 413


# Limites de la pièce jointe côté pont (le site en impose aussi : 20 Mo pour audio et vidéo d'un même message).
MIMES_IMAGE = ("image/png", "image/jpeg", "image/webp")
IMAGE_MAX_OCTETS = 10 * 1024 * 1024
IMAGES_MAX = 8
FICHIER_MAX_OCTETS = 20 * 1024 * 1024
AUDIO_MAX_OCTETS = 25 * 1024 * 1024
CORPS_MAX_OCTETS = 32 * 1024 * 1024
TYPES_IMAGE = ("image_url", "input_image")
_DATA_IMAGE = re.compile(r"^data:(image/[a-z0-9.+-]+);base64,(.*)$", re.S | re.I)


def image_en_base64(url):
    """data URL `data:image/<png|jpeg|webp>;base64,...` -> base64 brut, comme le site (champ `imagePath`)."""
    m = _DATA_IMAGE.match(url or "") if isinstance(url, str) else None
    if not m:
        raise EntreeInvalide("image : data URL data:image/<type>;base64,... ou adresse https attendue")
    mime, brut = m.group(1).lower(), m.group(2).strip()
    if mime not in MIMES_IMAGE:
        raise EntreeInvalide(f"image : type {mime} refusé (png, jpeg, webp)")
    try:
        octets = base64.b64decode(brut, validate=True)
    except ValueError:
        raise EntreeInvalide("image : base64 invalide") from None
    if not octets:
        raise EntreeInvalide("image : vide")
    if len(octets) > IMAGE_MAX_OCTETS:
        raise EntreeInvalide(f"image trop lourde ({len(octets)} octets, maximum {IMAGE_MAX_OCTETS})")
    return base64.b64encode(octets).decode()


def adresse_publique(hote):
    """Vrai seulement pour une adresse routable sur Internet : ni boucle locale, ni privée, ni tailnet (100.64/10)."""
    try:
        ip = ipaddress.ip_address(hote)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


def telecharger_image(url):
    """(type MIME, octets) d'une image https publique : pas de redirection, adresse résolue vérifiée, taille plafonnée.

    Limite connue : Venice et ce pont résolvent le nom chacun de leur côté (un DNS qui change entre les deux n'est pas couvert)."""
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        raise EntreeInvalide("image : seules les adresses https sont téléchargées")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        raise EntreeInvalide("image : adresse introuvable") from None
    if not infos or not all(adresse_publique(i[4][0]) for i in infos):
        raise EntreeInvalide("image : adresse non publique refusée")
    r = requete("GET", url, stream=True, timeout=30, suivre_redirections=False, headers={"User-Agent": UA})
    try:
        if r.status_code != 200:
            raise EntreeInvalide(f"image : téléchargement refusé ({r.status_code})")
        morceaux, total = [], 0
        for bloc in r.iter_content(65536):
            total += len(bloc)
            if total > IMAGE_MAX_OCTETS:
                raise EntreeInvalide(f"image trop lourde (maximum {IMAGE_MAX_OCTETS} octets)")
            morceaux.append(bloc)
    finally:
        r.close()
    return r.headers.get("content-type", "").split(";")[0].strip().lower(), b"".join(morceaux)


def analyser_fichier_venice(jeton, nom, octets):
    """Texte d'un fichier joint (route `text_parser` du site, 0 crédit). Un PDF scanné sans texte est refusé (400)."""
    for essai in (1, 2):
        r = requete("POST", f"{API_WEB}/inference/text_parser", timeout=120, files={"file": (nom, octets)},
                    headers={**EN_TETES_WEB, "Referer": "https://venice.ai/chat", "Authorization": "Bearer " + jeton.obtenir()})
        if r.status_code == 401 and essai == 1:
            jeton.invalider()
            continue
        if r.status_code == 400:
            raise EntreeInvalide(f"fichier {nom} : illisible ou sans texte extractible (PDF scanné ?)")
        if r.status_code != 200:
            raise RuntimeError(f"Venice {r.status_code}: {r.text[:200]}")
        return r.json().get("text", "")


class MediasHorsLigne:
    """Résolveur par défaut de construire_corps_venice : aucune pièce jointe sans résolveur explicite."""

    def image(self, url):
        raise EntreeInvalide("image : pièces jointes non résolues dans ce contexte")

    def fichier(self, nom, octets):
        raise EntreeInvalide("fichier : pièces jointes non résolues dans ce contexte")

    def audio(self, octets, format_audio):
        raise EntreeInvalide("audio : pièces jointes non résolues dans ce contexte")


# --- PDF scannés : pages en images (OCR) --------------------------------------------------------------------

OCR_MODELE = os.environ.get("VENICE_PONT_OCR_MODELE", "qwen-3-8-27b")
OCR_PAGES_MAX = int(os.environ.get("VENICE_PONT_OCR_PAGES", "20"))
OCR_PROMPT = ("Transcris fidèlement tout le texte visible dans cette image, dans l'ordre de lecture, sans commentaire ni mise en forme "
              "ajoutée. Réponds uniquement par le texte ; si aucun texte n'est visible, réponds par une chaîne vide.")
_OBJET_FLUX = re.compile(rb"obj\s*<<(.*?)>>\s*stream\r?\n", re.S)
_FILTRES_PDF = re.compile(rb"/(FlateDecode|DCTDecode|CCITTFaxDecode|JBIG2Decode|JPXDecode|LZWDecode|ASCII85Decode|ASCIIHexDecode|RunLengthDecode)")
IMAGE_PDF_MIN = 100  # en dessous, logo ou filet : pas une page


def _entier_pdf(dico, cle):
    m = re.search(cle + rb"\s+(\d+)(?!\s+\d+\s+R)", dico)
    return int(m.group(1)) if m else None


def _png(largeur, hauteur, couleurs, idat):
    def bloc(nom, donnees):
        return struct.pack(">I", len(donnees)) + nom + donnees + struct.pack(">I", zlib.crc32(nom + donnees) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", largeur, hauteur, 8, 2 if couleurs == 3 else 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", ihdr) + bloc(b"IDAT", idat) + bloc(b"IEND", b"")


def _image_pdf(dico, flux, largeur, hauteur):
    """(type MIME, octets) d'une image intégrée à un PDF, ou le nom du filtre non pris en charge."""
    filtre = re.search(rb"/Filter\s*(\[[^\]]*\]|/\w+)", dico)
    filtres = [f.decode() for f in _FILTRES_PDF.findall(filtre.group(1))] if filtre else []
    if filtres == ["DCTDecode"]:
        return "image/jpeg", flux
    if filtres == ["FlateDecode", "DCTDecode"]:
        return "image/jpeg", zlib.decompress(flux)
    if filtres != ["FlateDecode"]:
        return "/".join(filtres) or "sans filtre"
    espace = re.search(rb"/ColorSpace\s*/(\w+)", dico)
    couleurs = {b"DeviceRGB": 3, b"DeviceGray": 1}.get(espace.group(1) if espace else b"")
    if not couleurs or _entier_pdf(dico, b"/BitsPerComponent") != 8:
        return "FlateDecode (espace colorimétrique ou profondeur non pris en charge)"
    predicteur = _entier_pdf(dico, b"/Predictor") or 1
    if predicteur >= 10:  # lignes déjà filtrées comme en PNG : le flux sert tel quel d'IDAT
        if _entier_pdf(dico, b"/Columns") != largeur or (_entier_pdf(dico, b"/Colors") or 1) != couleurs:
            return "FlateDecode (prédicteur inattendu)"
        return "image/png", _png(largeur, hauteur, couleurs, flux)
    if predicteur != 1:
        return "FlateDecode (prédicteur TIFF)"
    brut = zlib.decompress(flux)
    ligne = largeur * couleurs
    if len(brut) != ligne * hauteur:
        return "FlateDecode (taille inattendue)"
    return "image/png", _png(largeur, hauteur, couleurs, zlib.compress(b"".join(b"\x00" + brut[i:i + ligne] for i in range(0, len(brut), ligne))))


def images_integrees_pdf(pdf):
    """Images de page d'un PDF scanné, dans l'ordre du fichier, sans aucune bibliothèque : JPEG repris tel quel, Flate RGB ou gris en PNG.

    CCITT, JBIG2, JPEG 2000 et les palettes ne sont pas décodés : l'erreur nomme alors le filtre."""
    pages, refus = [], []
    for m in _OBJET_FLUX.finditer(pdf):
        dico = m.group(1)
        if not re.search(rb"/Subtype\s*/Image", dico):
            continue
        largeur, hauteur = _entier_pdf(dico, b"/Width"), _entier_pdf(dico, b"/Height")
        if not largeur or not hauteur or min(largeur, hauteur) < IMAGE_PDF_MIN:
            continue
        debut, longueur = m.end(), _entier_pdf(dico, b"/Length")
        if longueur is not None and pdf[debut + longueur:debut + longueur + 12].lstrip().startswith(b"endstream"):
            flux = pdf[debut:debut + longueur]
        else:
            flux = pdf[debut:pdf.find(b"endstream", debut)].rstrip(b"\r\n")
        try:
            res = _image_pdf(dico, flux, largeur, hauteur)
        except zlib.error:
            res = "flux corrompu"
        (refus.append(res) if isinstance(res, str) else pages.append(res))
    if refus and not pages:
        raise EntreeInvalide(f"PDF scanné : filtre d'image non pris en charge ({', '.join(sorted(set(refus)))}) ; installer poppler-utils (pdftoppm)")
    return pages


def pages_pdf(pdf):
    """Pages d'un PDF en images : `pdftoppm` (poppler) à 150 dpi s'il est installé, sinon les images intégrées au PDF."""
    outil = shutil.which("pdftoppm")
    if outil:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                source, sortie = os.path.join(tmp, "in.pdf"), os.path.join(tmp, "p")
                with open(source, "wb") as f:
                    f.write(pdf)
                r = subprocess.run([outil, "-r", "150", "-png", "-f", "1", "-l", str(OCR_PAGES_MAX + 1), source, sortie],
                                   capture_output=True, timeout=180)
                fichiers = sorted(glob.glob(sortie + "-*.png"), key=lambda c: int(re.search(r"-(\d+)\.png$", c).group(1)))
                if r.returncode == 0 and fichiers:
                    return [("image/png", open(c, "rb").read()) for c in fichiers]
        except (OSError, subprocess.SubprocessError) as e:  # pas de dossier temporaire (conteneur en lecture seule), délai dépassé...
            print(f"pdftoppm inutilisable ({e}) : repli sur les images intégrées au PDF", file=sys.stderr, flush=True)
    pages = images_integrees_pdf(pdf)
    if not pages:
        raise EntreeInvalide("PDF scanné : aucun rendu possible (installer poppler-utils pour `pdftoppm`, ou joindre les pages en images)")
    return pages


FORMATS_AUDIO = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "ogg": "audio/ogg", "flac": "audio/flac", "webm": "audio/webm"}


def _type_image(octets):
    if octets.startswith(b"\x89PNG"):
        return "image/png"
    if octets.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if octets[:4] == b"RIFF" and octets[8:12] == b"WEBP":
        return "image/webp"
    return None


class PlafondAtteint(EntreeInvalide):
    statut = 429


class Medias:
    """Résolveurs des pièces jointes d'un message : image (data URL ou https), fichier (texte, PDF, OCR), audio (transcription)."""

    def __init__(self, jeton, limiteur=None, limiteur_voix=None):
        self._jeton, self._limiteur, self._limiteur_voix = jeton, limiteur, limiteur_voix
        self._transcriptions, self._verrou = {}, threading.Lock()

    def _reserver(self, limiteur):
        if limiteur:
            ok, attente = limiteur.essayer()
            if not ok:
                raise PlafondAtteint(f"plafond du pont atteint, réessayer dans {attente} s")

    def image(self, url):
        if isinstance(url, str) and url.startswith("https://"):
            mime, octets = telecharger_image(url)
            return image_en_base64(f"data:{mime};base64,{base64.b64encode(octets).decode()}")
        return image_en_base64(url)

    def ocr_image(self, b64, modele=None):
        """Texte d'une image par un modèle vision sans pièce (0 crédit)."""
        self._reserver(self._limiteur)
        corps = construire_corps_venice(modele or OCR_MODELE, [{"role": "user", "content": OCR_PROMPT}], None,
                                        {"temperature": 0, "reasoning_effort": "none"})
        corps["prompt"][-1]["imagePath"] = [b64]
        return "".join(morceaux_contenu(discuter(self._jeton, corps))).strip()

    def ocr_pdf(self, octets, modele=None):
        """(textes par page, tronqué) d'un PDF scanné ; au plus OCR_PAGES_MAX pages."""
        pages = pages_pdf(octets)
        textes = []
        for mime, page in pages[:OCR_PAGES_MAX]:
            textes.append(self.ocr_image(image_en_base64(f"data:{mime};base64,{base64.b64encode(page).decode()}"), modele))
        return textes, len(pages) > OCR_PAGES_MAX

    def fichier(self, nom, octets):
        if _type_image(octets):  # une image envoyée comme fichier : lue par OCR
            return self.ocr_image(image_en_base64(f"data:{_type_image(octets)};base64,{base64.b64encode(octets).decode()}"))
        pdf = octets.lstrip()[:5] == b"%PDF-"
        try:
            texte = analyser_fichier_venice(self._jeton, nom, octets)
        except EntreeInvalide:
            if not pdf:
                raise
            texte = ""
        if texte.strip() or not pdf:
            return texte
        textes, tronque = self.ocr_pdf(octets)
        return texte_des_pages(textes) + (f"\n\n[… tronqué après {OCR_PAGES_MAX} pages]" if tronque else "")

    def audio(self, octets, format_audio):
        """Texte d'un audio joint (Parakeet, route de transcription du site) ; une transcription déjà faite est réutilisée."""
        import hashlib
        cle = hashlib.sha256(octets).hexdigest()
        with self._verrou:
            if cle in self._transcriptions:
                return self._transcriptions[cle]
        self._reserver(self._limiteur_voix)
        texte = transcrire_venice(self._jeton, octets, f"audio.{format_audio}", FORMATS_AUDIO[format_audio], False).get("text", "")
        with self._verrou:
            if len(self._transcriptions) >= 64:
                self._transcriptions.pop(next(iter(self._transcriptions)))
            self._transcriptions[cle] = texte
        return texte


def texte_des_pages(textes):
    return "".join(t if i == 0 else f"\n\n--- page {i + 1} ---\n\n{t}" for i, t in enumerate(textes))


def contient_images(messages):
    return any(isinstance(m.get("content"), list) and any(isinstance(p, dict) and p.get("type") in TYPES_IMAGE for p in m["content"])
               for m in messages)


def _url_image(partie):
    u = partie.get("image_url", partie.get("url"))
    return u.get("url") if isinstance(u, dict) else u


def _donnees_fichier(partie, medias):
    f = partie.get("file") or {}
    if not f.get("file_data"):
        raise EntreeInvalide("fichier : file_data (data URL base64) requis, file_id n'est pas pris en charge")
    brut = f["file_data"].split("base64,", 1)[-1]
    try:
        octets = base64.b64decode(brut, validate=True)
    except ValueError:
        raise EntreeInvalide("fichier : base64 invalide") from None
    if len(octets) > FICHIER_MAX_OCTETS:
        raise EntreeInvalide(f"fichier trop lourd (maximum {FICHIER_MAX_OCTETS} octets)")
    nom = f.get("filename") or "fichier"
    return nom, medias.fichier(nom, octets)


def _transcrire_audio(partie, medias):
    a = partie.get("input_audio") or {}
    if a.get("format") not in FORMATS_AUDIO or not isinstance(a.get("data"), str):
        raise EntreeInvalide(f"audio : input_audio {{data en base64, format parmi {', '.join(FORMATS_AUDIO)}}} attendu")
    try:
        octets = base64.b64decode(a["data"], validate=True)
    except ValueError:
        raise EntreeInvalide("audio : base64 invalide") from None
    if len(octets) > AUDIO_MAX_OCTETS:
        raise EntreeTropGrosse(f"audio de {len(octets)} octets, maximum {AUDIO_MAX_OCTETS}")
    return medias.audio(octets, a["format"])


def _decouper(contenu, medias, avec_images):
    """Contenu d'un message OpenAI (chaîne ou liste de parties) -> (texte, images base64, textes de fichiers joints)."""
    if not isinstance(contenu, list):
        return contenu or "", [], []
    texte, images, fichiers = [], [], []
    for p in contenu:
        if not isinstance(p, dict):
            continue
        genre = p.get("type")
        if genre in TYPES_IMAGE:
            if avec_images:
                images.append(medias.image(_url_image(p)))
        elif genre == "file":
            fichiers.append(_donnees_fichier(p, medias))
        elif genre == "input_audio":
            texte.append(f"[Audio transcrit : {_transcrire_audio(p, medias)}]")
        else:
            texte.append(p.get("text", ""))
    return "".join(texte), images, fichiers


def construire_corps_venice(modele, messages, outils, params, medias=None):
    medias = medias or MediasHorsLigne()
    # Comme le site : seules les images du dernier message qui en porte sont rejouées ; les anciennes sont écartées sans téléchargement.
    derniere = max((i for i, m in enumerate(messages) if contient_images([m])), default=-1)
    systeme, prompt = [], []
    for i, m in enumerate(messages):
        role, contenu = m.get("role"), m.get("content")
        contenu, images, fichiers = _decouper(contenu, medias, role == "user" and i == derniere)
        if len(images) > IMAGES_MAX:
            raise EntreeInvalide(f"trop d'images dans un message ({len(images)}, maximum {IMAGES_MAX} images)")
        if role == "system":
            systeme.append(contenu or "")
        elif role == "tool":
            prompt.append({"role": "user", "content": f"Résultat de l'outil (appel {m.get('tool_call_id', '')}) : {contenu}"})
        elif role == "assistant" and m.get("tool_calls"):
            texte = "\n".join(_appel_en_texte(tc) for tc in m["tool_calls"])
            prompt.append({"role": "assistant", "content": texte})
        else:
            item = {"role": role, "content": contenu or ""}
            if fichiers:  # format du site : le texte du fichier d'abord, puis la question
                joints = "\n\n".join(f"The following content is from a file named {nom}: {texte}" for nom, texte in fichiers)
                item.update(content=f"{joints}  {contenu}" if contenu else joints, isFile=True)
            if images:
                item["imagePath"] = images
            prompt.append(item)
    if outils:
        definitions = [o.get("function", o) for o in outils]
        systeme.append(CONSIGNE_OUTILS.format(
            outils=json.dumps(definitions, ensure_ascii=False), noms=", ".join(str(d.get("name")) for d in definitions)))
    corps = {
        "requestId": uuid.uuid4().hex[:7],
        "conversationType": "text",
        "type": "text",
        "modelId": modele,
        "prompt": prompt,
        "systemPrompt": "\n\n".join(s for s in systeme if s),
        "clientProcessingTime": 5,
        "includeVeniceSystemPrompt": bool(params.get("include_venice_system_prompt", False)),
        "isCharacter": False,
        "webEnabled": bool(params.get("web_search", False)) or "web_search_options" in params,
        "webScrapeEnabled": bool(params.get("web_scrape", False)),
        "xSearchEnabled": bool(params.get("x_search", False)),
        "temperature": params.get("temperature", 0.3),
        "topP": params.get("top_p", 0.9),
        "maxTokens": params.get("max_tokens") or params.get("max_completion_tokens") or 4096,
    }
    if "reasoning_effort" in params:  # « none » coupe la réflexion (champ web `reasoning`)
        corps["reasoning"] = params["reasoning_effort"] != "none"
    return corps


_PENSEE = re.compile(r"<think>.*?</think>", re.S)
_CLOTURE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def extraire_appels(texte, outils):
    """(contenu, tool_calls) : tool_calls non None si le texte est un appel d'outil valide."""
    if not outils or not texte:
        return texte, None
    noms = {o.get("function", o).get("name") for o in outils}
    brut = _PENSEE.sub("", texte).strip()
    m = _CLOTURE.match(brut)
    if m:
        brut = m.group(1)
    try:
        obj, _fin = json.JSONDecoder().raw_decode(brut)  # un modèle peut enchaîner du texte après l'appel
    except ValueError:
        return texte, None
    liste = obj.get("tool_calls") if isinstance(obj, dict) else None
    if not liste or not all(isinstance(t, dict) and t.get("name") in noms for t in liste):
        return texte, None
    appels = []
    for t in liste:
        args = t.get("arguments", {})
        appels.append({
            "id": "call_" + uuid.uuid4().hex[:24],
            "type": "function",
            "function": {"name": t["name"], "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)},
        })
    return None, appels


def morceaux_contenu(lignes):
    for ligne in lignes:
        if not ligne:
            continue
        try:
            o = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(o, dict) and o.get("kind") == "content" and "content" in o:
            yield o["content"]


def reponse_openai(modele, contenu, appels, jetons=0):
    msg = {"role": "assistant", "content": contenu}
    if appels:
        msg["tool_calls"] = appels
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:24], "object": "chat.completion",
        "created": int(time.time()), "model": modele,
        "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if appels else "stop"}],
        "usage": {"prompt_tokens": jetons, "completion_tokens": 0, "total_tokens": jetons},
    }


def morceaux_sse(rep):
    """Chunks `chat.completion.chunk` d'une réponse complète. Appel d'outil en forme canonique OpenAI :
    id et nom avec arguments vides, puis les arguments seuls, puis la fin (un client qui concatène les
    arguments ne les voit qu'une fois)."""
    ch = rep["choices"][0]
    base = {"id": rep["id"], "object": "chat.completion.chunk", "created": rep["created"], "model": rep["model"]}

    def morceau(delta, fin=None):
        return {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}

    appels = ch["message"].get("tool_calls")
    if not appels:
        return [morceau({"role": "assistant", "content": ch["message"]["content"] or ""}),
                morceau({}, ch["finish_reason"])]
    entetes = [{"index": i, "id": tc["id"], "type": tc["type"],
                "function": {"name": tc["function"]["name"], "arguments": ""}} for i, tc in enumerate(appels)]
    args = [{"index": i, "function": {"arguments": tc["function"]["arguments"]}} for i, tc in enumerate(appels)]
    return [morceau({"role": "assistant", "tool_calls": entetes}), morceau({"tool_calls": args}),
            morceau({}, ch["finish_reason"])]


def cle_valide(entete, cle):
    if not cle or not entete or not entete.startswith("Bearer "):
        return False
    return hmac.compare_digest(entete[7:], cle)


def lire_env(chemin):
    out = {}
    for ligne in open(os.path.expanduser(chemin)):
        if "=" in ligne and not ligne.lstrip().startswith("#"):
            k, v = ligne.strip().split("=", 1)
            out[k] = v
    return out


def discuter(jeton, corps):
    """Itérateur de lignes NDJSON ; rejoue une fois avec un jeton neuf sur 401."""
    for essai in (1, 2):
        r = requete("POST", OUTERFACE, corps_json=corps, stream=True, timeout=180, headers={
            **EN_TETES_WEB, "Referer": "https://venice.ai/chat", "Authorization": "Bearer " + jeton.obtenir()})
        if r.status_code == 401 and essai == 1:
            jeton.invalider()
            r.close()
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Venice {r.status_code}: {r.text[:200]}")
        return r.iter_lines(decode_unicode=True)  # Venice répond text/html sans charset : le décodage est en UTF-8


MODELES_AGENT = set(filter(None, os.environ.get(
    "VENICE_PONT_AGENTS", "deepseek-v4-1-flash-uncensored,kimi-k2-5").split(",")))


def est_agent(modele):
    """Modèles servis seulement par la route « agents » (absents du chat classique)."""
    return modele in MODELES_AGENT


def _item_agent(role, texte):
    return {"type": "message", "role": role, "id": uuid.uuid4().hex[:11], "status": "completed",
            "content": [{"type": "output_text", "text": texte, "annotations": []}]}


def messages_agent(corps):
    """Corps du chat classique -> messages de la route agents (le système devient un 1er message utilisateur)."""
    msgs = []
    if corps.get("systemPrompt"):
        msgs.append(_item_agent("user", "[System]\n" + corps["systemPrompt"]))
    for m in corps["prompt"]:
        msgs.append(_item_agent(m["role"], m["content"]))
    return msgs


def lire_flux_agent(lignes):
    """Flux SSE de la route agents -> (texte, jetons totaux du contexte, système imposé par Venice compris)."""
    evenement, texte, jetons = None, [], 0
    for ligne in lignes:
        if ligne.startswith("event:"):
            evenement = ligne[6:].strip()
        elif ligne.startswith("data:"):
            try:
                d = json.loads(ligne[5:])
            except ValueError:
                continue
            if evenement == "response.output_text.delta":
                if str(d.get("item_id", "")).startswith("rs_"):  # raisonnement : pas dans la réponse
                    continue
                texte.append(d.get("delta", ""))
            elif evenement == "response.output_text.done":
                jetons = (d.get("context_metadata") or {}).get("total_tokens", jetons)
            elif evenement in ("response.failed", "response.error", "error"):
                err = (d.get("response") or d).get("error") or d
                raise RuntimeError(f"Venice agent: {json.dumps(err, ensure_ascii=False)[:200]}")
    return "".join(texte), jetons


def discuter_agent(jeton, modele, corps):
    """Appelle la route agents ; rejoue une fois avec un jeton neuf sur 401. Renvoie (texte, jetons)."""
    for essai in (1, 2):
        r = requete("POST", AGENTS, params={"agentModelId": modele}, stream=True, timeout=300,
                    corps_json={"clientTools": [], "input": {"messages": messages_agent(corps)}},
                    headers={**EN_TETES_WEB, "Referer": "https://venice.ai/chat",
                             "Accept": "text/event-stream", "x-venice-locale": "en",
                             "Authorization": "Bearer " + jeton.obtenir()})
        if r.status_code == 401 and essai == 1:
            jeton.invalider()
            r.close()
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Venice {r.status_code}: {r.text[:200]}")
        return lire_flux_agent(r.iter_lines(decode_unicode=True))


# Modèles sans pièce = illimités avec Pro (relevé dans le sélecteur de venice.ai, banc du 28/10/2026 : 0 crédit débité).
# Tout autre modèle est refusé (403) sauf débit volontaire : `autoriser_debit: true` dans la requête, ou VENICE_PONT_AUTORISER_PAYANTS=1.
GRATUITS = set(filter(None, os.environ.get(
    "VENICE_PONT_GRATUITS",
    "qwen-3-8-27b,venice-uncensored-1-2,gemma4-uncensored,olafangensan-glm-4.7-flash-heretic,"
    "venice-uncensored-role-play,aion-labs-aion-3-0,deepseek-v4-1-flash-uncensored,kimi-k2-5,"
    "qwen3-6-27b,qwen3-5-35b-a3b,google-gemma-4-26b-a4b-it,google-gemma-4-31b-it,qwen3-vl-235b-a22b").split(",")))
AUTORISER_PAYANTS = os.environ.get("VENICE_PONT_AUTORISER_PAYANTS") == "1"

# Modèles qui lisent une image sans débit (28/10/2026 : un dessin décrit par chacun, solde 285 avant et après).
# venice-uncensored-role-play renvoie une 500 avec une image ; la route agents (Kimi, DeepSeek) n'a pas de vision ici.
VISION_GRATUITS = ("qwen-3-8-27b", "qwen3-6-27b", "qwen3-5-35b-a3b", "google-gemma-4-26b-a4b-it",
                   "google-gemma-4-31b-it", "gemma4-uncensored", "venice-uncensored-1-2", "qwen3-vl-235b-a22b")

# Images sans pièce (`usesCredits: false` dans le catalogue web ; z-image-turbo mesuré le 28/10/2026 : 0 crédit, quota Pro 1 000/jour).
# diviseur : multiple imposé à la largeur et à la hauteur ; pas : défaut du site ; negatif : accepte un prompt négatif.
IMAGES_GRATUITES = {
    "z-image-turbo": {"diviseur": 8, "pas": 8, "negatif": False, "prompt_max": 7500},
    "chroma": {"diviseur": 8, "pas": 10, "negatif": False, "prompt_max": 7500},
    "stable-diffusion-3.5-rev2": {"diviseur": 16, "pas": 25, "negatif": True, "prompt_max": 1500},
    "lustify-sdxl": {"diviseur": 8, "pas": 20, "negatif": True, "prompt_max": 1500},
    "lustify-v8": {"diviseur": 8, "pas": 30, "negatif": True, "prompt_max": 1500},
    "wai-illu": {"diviseur": 16, "pas": 25, "negatif": True, "prompt_max": 1500},
}
IMAGE_DEFAUT = "z-image-turbo"
ALIAS_IMAGES = {"dall-e-2": IMAGE_DEFAUT, "dall-e-3": IMAGE_DEFAUT, "gpt-image-1": IMAGE_DEFAUT, "default": IMAGE_DEFAUT}
IMAGES_MAX_PAR_REQUETE = 4
QUOTA_IMAGE_MINIMUM = 5

# Voix : tous mesurés à 0 crédit le 28/10/2026 (texte de 15 caractères). Valeur = format par défaut (inworld et gradium : wav seulement).
# tts-orpheus et tts-chatterbox-hd ont expiré (120 s) : exclus.
TTS_GRATUITS = {"tts-kokoro": "mp3", "tts-qwen3-0-6b": "mp3", "tts-qwen3-1-7b": "mp3", "tts-xai-v1": "mp3",
                "tts-gemini-3-1-flash": "mp3", "tts-elevenlabs-turbo-v2-5": "mp3", "tts-minimax-speech-02-hd": "mp3",
                "tts-inworld-1-5-max": "wav", "tts-gradium-v1": "wav"}
TTS_DEFAUT = "tts-kokoro"
ALIAS_TTS = {"tts-1": TTS_DEFAUT, "tts-1-hd": TTS_DEFAUT, "gpt-4o-mini-tts": TTS_DEFAUT}
# Les noms de voix OpenAI n'existent pas chez Venice : ils prennent la voix par défaut (française, Kokoro ff_siwis ;
# les voix anglaises af_*, am_*, bf_*, bm_* lisent mal le français). Une voix Kokoro nommée passe telle quelle.
VOIX_OPENAI = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse")
VOIX_DEFAUT = os.environ.get("VENICE_PONT_VOIX", "ff_siwis")
# Édition d'image (route `inpaint` du site) : les 2 modèles sans pièce du catalogue, mesurés le 28/10/2026 (0 crédit, quota « inpaint » 1 000/jour).
EDITS_GRATUITES = {"qwen-edit-uncensored": {}, "firered-image-edit": {}}
EDIT_DEFAUT = "qwen-edit-uncensored"
ALIAS_EDITS = {"dall-e-2": EDIT_DEFAUT, "gpt-image-1": EDIT_DEFAUT, "default": EDIT_DEFAUT}
EDITS_MAX_PAR_REQUETE = 2
ECHELLES_UPSCALE = (2, 4)     # mesurées à 0 crédit sur une image de 512 px
EMBEDDING_MODELE = "text-embedding-bge-m3"
EMBEDDINGS_MAX_ENTREES = 64
EMBEDDINGS_MAX_CARACTERES = 8000
TTS_MAX_CARACTERES = 4096
ASR_MODELE = "nvidia/parakeet-tdt-0.6b-v3"
FORMATS_ASR = ("json", "text", "verbose_json", "srt", "vtt")


def modele_autorise(modele, req):
    return AUTORISER_PAYANTS or modele in GRATUITS or req.get("autoriser_debit") is True


class LimiteurDebit:
    """Plafond de requêtes sur une fenêtre glissante : un agent en boucle ne doit pas donner au compte Pro un motif de robot."""

    def __init__(self, maximum, fenetre=60, horloge=time.time):
        self._max, self._fenetre, self._horloge = maximum, fenetre, horloge
        self._instants, self._verrou = [], threading.Lock()

    def essayer(self, n=1):
        """(True, 0) si les n requêtes passent (toutes ou aucune) ; (False, secondes à attendre) sinon."""
        with self._verrou:
            maintenant = self._horloge()
            self._instants = [t for t in self._instants if maintenant - t < self._fenetre]
            if len(self._instants) + n > self._max:
                return False, max(1, math.ceil(self._fenetre - (maintenant - self._instants[0]))) if self._instants else 1
            self._instants.extend([maintenant] * n)
            return True, 0


def decoder_solde(jwt):
    """Solde total (`veniceCredits`) dans la charge utile du jeton de /api/user/session."""
    p = jwt.split(".")[1]
    return float(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["veniceCredits"])


def lire_solde(jeton):
    r = requete("GET", SESSION, timeout=30, headers={**EN_TETES_WEB, "Authorization": "Bearer " + jeton.obtenir()})
    r.raise_for_status()
    return decoder_solde(r.json()["token"])


class SuiviCredits:
    """Garde-fou crédits : alerte si le solde passe sous la référence (un modèle à pièce a débité).

    La référence monte avec une recharge (forfait mensuel) et se remet au solde courant sur acquittement. Elle survit
    à un redémarrage (fichier). `alerte` est lue par /health puis par une sonde externe."""

    SEUIL = 0.5

    def __init__(self, lecteur, fichier=None, horloge=time.time):
        self._lecteur, self._fichier, self._horloge = lecteur, fichier, horloge
        self._verrou = threading.Lock()
        self._e = {"courant": None, "reference": None, "lu_le": None, "erreur": None}
        try:
            self._e["reference"] = json.loads(open(fichier).read())["reference"] if fichier else None
        except (OSError, ValueError, KeyError):
            pass

    def _ecrire(self):
        if not self._fichier:
            return
        tmp = str(self._fichier) + ".tmp"
        with open(tmp, "w") as f:
            f.write(json.dumps({"reference": self._e["reference"]}))
        os.replace(tmp, self._fichier)

    def rafraichir(self):
        try:
            courant = self._lecteur()
        except Exception as e:  # une lecture ratée ne doit ni lever une fausse alerte ni arrêter le pont
            with self._verrou:
                self._e["erreur"] = str(e)[:200]
            return self.etat()
        with self._verrou:
            self._e.update(courant=courant, lu_le=self._horloge(), erreur=None)
            if self._e["reference"] is None or courant > self._e["reference"]:
                self._e["reference"] = courant
                self._ecrire()
        return self.etat()

    def acquitter(self):
        with self._verrou:
            if self._e["courant"] is not None:
                self._e["reference"] = self._e["courant"]
                self._ecrire()
        return self.etat()

    def etat(self):
        with self._verrou:
            e = dict(self._e)
        debit = (e["reference"] - e["courant"]) if e["reference"] is not None and e["courant"] is not None else 0
        return {**e, "debit": debit, "alerte": debit >= self.SEUIL}


def boucle_credits(suivi, intervalle=600):
    while True:
        suivi.rafraichir()
        time.sleep(intervalle)


class ErreurVenice(Exception):
    """Réponse d'erreur de Venice à relayer : un 400 reste un 400, un 429 un 429, le reste devient 502."""

    def __init__(self, statut, message):
        super().__init__(message)
        self.statut = statut if statut in (400, 429, 504) else 502


def _appeler_venice(jeton, methode, chemin, **kw):
    """Appel d'une route du site ; rejoue une fois avec un jeton neuf sur 401. Renvoie la réponse HTTP (statut 200 garanti)."""
    lecture = kw.pop("lecture", 120)
    for essai in (1, 2):
        try:
            r = requete(methode, f"{API_WEB}{chemin}", timeout=lecture, **kw,
                        headers={**EN_TETES_WEB, "Referer": "https://venice.ai/chat", "Authorization": "Bearer " + jeton.obtenir()})
        except DelaiDepasse:
            raise ErreurVenice(504, "Venice n'a pas répondu à temps") from None
        if r.status_code == 401 and essai == 1:
            jeton.invalider()
            continue
        if r.status_code != 200:
            try:
                detail = r.json().get("error") or r.text
            except ValueError:
                detail = r.text
            raise ErreurVenice(r.status_code, f"Venice {r.status_code}: {str(detail)[:200]}")
        return r


def generer_image_venice(jeton, corps):
    """(octets, type MIME, en-têtes utiles) d'une image générée par `/api/inference/image` du site."""
    r = _appeler_venice(jeton, "POST", "/inference/image", corps_json=corps, lecture=240)
    genre = r.headers.get("content-type", "").split(";")[0]
    if not genre.startswith("image/"):
        raise ErreurVenice(502, f"Venice n'a pas renvoyé d'image ({genre}) : {r.text[:150]}")
    return r.content, genre, {k.lower(): v for k, v in r.headers.items() if k.lower().startswith(("x-ratelimit", "x-venice"))}


def synthese_vocale_venice(jeton, corps):
    """(octets, type MIME) de la synthèse vocale `/api/inference/tts` (le site rejoue les réponses vides)."""
    for _ in range(2):
        r = _appeler_venice(jeton, "POST", "/inference/tts", corps_json=corps, lecture=90)
        if r.content:
            return r.content, r.headers.get("content-type", "audio/mpeg").split(";")[0]
    raise ErreurVenice(502, "Venice a renvoyé un audio vide")


def transcrire_venice(jeton, octets, nom, mime, timestamps):
    """Réponse JSON de `/api/inference/asr` : {text} (+ timestamps [{start, end, text}] si demandés)."""
    r = _appeler_venice(jeton, "POST", "/inference/asr", files={"file": (nom, octets, mime)}, lecture=180,
                        data={"model": ASR_MODELE, "responseFormat": "json", "timestamps": "true" if timestamps else "false"})
    return r.json()


def _image_reponse(r):
    genre = r.headers.get("content-type", "").split(";")[0]
    if not genre.startswith("image/"):
        raise ErreurVenice(502, f"Venice n'a pas renvoyé d'image ({genre}) : {r.text[:150]}")
    return r.content, genre, {k.lower(): v for k, v in r.headers.items() if k.lower().startswith(("x-ratelimit", "x-venice"))}


def editer_image_venice(jeton, modele, prompt, octets, nom, mime):
    """Édition d'une image selon un texte (`/api/inference/inpaint`) : (octets, type MIME, en-têtes utiles)."""
    return _image_reponse(_appeler_venice(jeton, "POST", "/inference/inpaint", data={"modelId": modele, "prompt": prompt},
                                          files={"file": (nom, octets, mime)}, lecture=240))


def agrandir_venice(jeton, octets, nom, mime, echelle):
    """Agrandissement sans prompt (`/api/inference/enhance`)."""
    return _image_reponse(_appeler_venice(jeton, "POST", "/inference/enhance", data={"scale": str(echelle), "enhance": "false"},
                                          files={"file": (nom, octets, mime)}, lecture=240))


def detourer_venice(jeton, data_url):
    """Suppression de l'arrière-plan (`/api/inference/background-remove`) : PNG avec transparence."""
    return _image_reponse(_appeler_venice(jeton, "POST", "/inference/background-remove", corps_json={"image_url": data_url}, lecture=120))


def embeddings_venice(jeton, entrees):
    """Vecteurs denses (`/api/app/memoria/embeddings`, bge-m3) déjà au format OpenAI ; `skipImportance` évite une erreur 500."""
    return _appeler_venice(jeton, "POST", "/app/memoria/embeddings", lecture=60,
                           corps_json={"encoding_format": "float", "input": entrees, "skipImportance": True}).json()


def lire_quotas_venice(jeton):
    """Quotas du jour du compte (`/api/inference/rate-limits`) : {chat, conversation, image, inpaint, scrape} -> {remaining, resetAt}."""
    return _appeler_venice(jeton, "GET", "/inference/rate-limits", lecture=30).json()


class SuiviQuotas:
    """Dernier quota connu par catégorie (lu sur demande et noté à chaque image générée)."""

    def __init__(self, lecteur, horloge=time.time):
        self._lecteur, self._horloge, self._verrou = lecteur, horloge, threading.Lock()
        self._q, self._lu_le, self._erreur = {}, None, None

    def rafraichir(self):
        try:
            lu = self._lecteur()
        except Exception as e:  # une lecture ratée ne doit pas arrêter le pont
            with self._verrou:
                self._erreur = str(e)[:200]
            return self.etat()
        with self._verrou:
            self._q, self._lu_le, self._erreur = dict(lu), self._horloge(), None
        return self.etat()

    def noter(self, categorie, restant):
        with self._verrou:
            self._q.setdefault(categorie, {})["remaining"] = restant

    def restant(self, categorie):
        with self._verrou:
            return (self._q.get(categorie) or {}).get("remaining")

    def etat(self):
        with self._verrou:
            return {**self._q, "lu_le": self._lu_le, "erreur": self._erreur}


def boucle_quotas(quotas, intervalle=600):
    while True:
        quotas.rafraichir()
        time.sleep(intervalle)


def dimensions_depuis_size(size, diviseur):
    """`size` OpenAI (« 1024x768 ») -> (largeur, hauteur) arrondies au multiple imposé, bornées à 256..1280."""
    if size in (None, "", "auto"):
        return 1024, 1024
    m = re.fullmatch(r"(\d{1,5})x(\d{1,5})", str(size))
    if not m:
        raise EntreeInvalide("size : forme « 1024x1024 » attendue")

    def borner(v):
        return min(1280, max(256, int(v))) // diviseur * diviseur
    return borner(m.group(1)), borner(m.group(2))


def corps_image(req, modele, reglages):
    prompt = req.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise EntreeInvalide("prompt : texte non vide requis")
    if len(prompt) > reglages["prompt_max"]:
        raise EntreeInvalide(f"prompt : {reglages['prompt_max']} caractères au plus pour {modele}")
    largeur, hauteur = dimensions_depuis_size(req.get("size"), reglages["diviseur"])
    corps = {"modelId": modele, "prompt": prompt, "width": largeur, "height": hauteur, "steps": reglages["pas"],
             "hideWatermark": True, "matureFilter": False, "format": "png", "embedExifMetadata": False, "type": "image",
             "variants": 1, "clientProcessingTime": 5}
    if reglages["negatif"] and isinstance(req.get("negative_prompt"), str):
        corps["negativePrompt"] = req["negative_prompt"]
    return corps  # jamais acceptCreditFallback : un quota épuisé n'a pas à s'acheter en crédits


def formater_horodatage(secondes, separateur):
    ms = int(round(secondes * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{separateur}{ms % 1000:03d}"


def formater_transcription(res, format_reponse):
    """(type de contenu, octets) d'une transcription Venice au format OpenAI demandé."""
    texte = res.get("text", "")
    segments = [{"id": i, "start": t["start"], "end": t["end"], "text": t["text"]} for i, t in enumerate(res.get("timestamps") or [])]
    if format_reponse in ("srt", "vtt") and not segments:  # mesuré le 28/10/2026 : la route ne renvoie aucun horodatage
        raise EntreeInvalide(f"{format_reponse} : Venice ne fournit pas d'horodatage sur cette route "
                             "(json, text ou verbose_json sans segments)")
    if format_reponse == "text":
        return "text/plain; charset=utf-8", texte.encode()
    if format_reponse == "verbose_json":
        corps = {"task": "transcribe", "duration": segments[-1]["end"] if segments else 0, "text": texte, "segments": segments}
        return "application/json; charset=utf-8", json.dumps(corps, ensure_ascii=False).encode()
    if format_reponse == "srt":
        blocs = [f"{s['id'] + 1}\n{formater_horodatage(s['start'], ',')} --> {formater_horodatage(s['end'], ',')}\n{s['text']}\n"
                 for s in segments]
        return "application/x-subrip; charset=utf-8", "\n".join(blocs).encode()
    if format_reponse == "vtt":
        blocs = [f"{formater_horodatage(s['start'], '.')} --> {formater_horodatage(s['end'], '.')}\n{s['text']}\n" for s in segments]
        return "text/vtt; charset=utf-8", ("WEBVTT\n\n" + "\n".join(blocs)).encode()
    return "application/json; charset=utf-8", json.dumps({"text": texte}, ensure_ascii=False).encode()


def lire_multipart(type_contenu, corps):
    """(champs texte, fichiers {nom: (nom de fichier, type MIME, octets)}) d'un formulaire multipart/form-data."""
    if not (type_contenu or "").lower().startswith("multipart/form-data"):
        raise EntreeInvalide("multipart/form-data attendu")
    msg = BytesParser(policy=policy.HTTP).parsebytes(b"Content-Type: " + type_contenu.encode() + b"\r\n\r\n" + corps)
    champs, fichiers = {}, {}
    for part in msg.iter_parts():
        nom = part.get_param("name", header="content-disposition")
        if not nom:
            continue
        octets = part.get_payload(decode=True) or b""
        if part.get_filename() is not None:
            fichiers[nom] = (part.get_filename(), part.get_content_type(), octets)
        else:
            champs[nom] = octets.decode("utf-8", "replace")
    return champs, fichiers


def lister_modeles():
    """Les modèles sans pièce : le catalogue de l'API ne connaît pas les ids web (gemma4-uncensored) ni la route agents."""
    return [{"id": m, "object": "model", "owned_by": "venice-agent" if est_agent(m) else "venice", "vision": m in VISION_GRATUITS}
            for m in sorted(GRATUITS | MODELES_AGENT)]


def lister_modeles_image():
    return ([{"id": m, "object": "model", "owned_by": "venice-image"} for m in sorted(IMAGES_GRATUITES)]
            + [{"id": m, "object": "model", "owned_by": "venice-image-edit"} for m in sorted(EDITS_GRATUITES)])


def lister_modeles_audio():
    return ([{"id": m, "object": "model", "owned_by": "venice-tts", "format_defaut": f} for m, f in sorted(TTS_GRATUITS.items())]
            + [{"id": ASR_MODELE, "object": "model", "owned_by": "venice-asr"}])


def fabriquer_handler(jeton, cle_pont, source=None, limiteur=None, suivi=None, limiteur_images=None, limiteur_voix=None,
                      quotas=None, medias=None):
    medias = medias or Medias(jeton, limiteur, limiteur_voix)

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _json(self, code, obj, entetes=None):
            self._octets(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", entetes)

        def _octets(self, code, data, type_contenu, entetes=None):
            self.send_response(code)
            for k, v in (entetes or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Type", type_contenu)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _erreur(self, code, nom, message, entetes=None):
            self._json(code, {"error": {"code": nom, "message": message}}, entetes)

        def _autorise(self):
            if cle_valide(self.headers.get("Authorization"), cle_pont):
                return True
            self._json(401, {"error": {"message": "clé du pont invalide"}})
            return False

        def _lire_corps(self):
            """Corps de la requête, ou None (413 déjà envoyé, connexion fermée) s'il dépasse CORPS_MAX_OCTETS."""
            n = int(self.headers.get("Content-Length", 0))
            if n > CORPS_MAX_OCTETS:
                self.close_connection = True
                self._erreur(413, "corps_trop_gros", f"corps de {n} octets, maximum {CORPS_MAX_OCTETS}", {"Connection": "close"})
                return None
            return self.rfile.read(n)

        def _limite(self, lim, n=1):
            """Vrai si la requête passe ; sinon répond 429 avec Retry-After."""
            if not lim:
                return True
            ok, attente = lim.essayer(n)
            if not ok:
                self._erreur(429, "plafond_pont", f"plafond du pont atteint, réessayer dans {attente} s", {"Retry-After": str(attente)})
            return ok

        def _refus_payant(self, modele, req, liste):
            """Vrai (et 403 envoyé) si le modèle n'est pas dans la liste sans pièce et que le débit n'est pas autorisé."""
            if AUTORISER_PAYANTS or modele in liste or req.get("autoriser_debit") is True:
                return False
            self._erreur(403, "modele_payant_refuse", f"{modele} n'est pas dans la liste des modèles sans pièce "
                         "(débit de crédits). Débit volontaire : autoriser_debit: true.")
            return True

        def do_GET(self):
            if self.path == "/health":
                try:
                    jeton.obtenir()
                    return self._json(200, {"ok": True, **jeton.etat(), **(source.etat() if source else {}),
                                            **({"credits": suivi.etat()} if suivi else {}),
                                            **({"quotas": quotas.etat()} if quotas else {})})
                except CookieExpire as e:
                    return self._json(503, {"ok": False, "raison": "cookie_expire", "detail": str(e)})
                except Exception as e:
                    return self._json(503, {"ok": False, "raison": "clerk_injoignable", "detail": str(e)[:200]})
            if not self._autorise():
                return
            listes = {"/v1/models": lister_modeles, "/models": lister_modeles,
                      "/v1/images/models": lister_modeles_image, "/v1/audio/models": lister_modeles_audio}
            if self.path in listes:
                try:
                    return self._json(200, {"object": "list", "data": listes[self.path]()})
                except Exception as e:
                    return self._json(502, {"error": {"message": str(e)[:200]}})
            if self.path == "/credits" and suivi:
                return self._json(200, suivi.rafraichir())
            if self.path == "/quotas" and quotas:
                return self._json(200, quotas.rafraichir())
            self._json(404, {"error": {"message": "inconnu"}})

        def do_POST(self):
            if not self._autorise():
                return
            corps = self._lire_corps()
            if corps is None:
                return
            chemin = self.path.split("?")[0]
            if chemin == "/credits/acquitter" and suivi:
                return self._json(200, suivi.acquitter())
            routes = {"/v1/chat/completions": self._chat, "/chat/completions": self._chat,
                      "/v1/images/generations": self._images, "/v1/audio/speech": self._synthese,
                      "/v1/audio/transcriptions": self._transcription, "/v1/embeddings": self._embeddings, "/v1/ocr": self._ocr,
                      "/v1/images/edits": self._edition, "/v1/images/upscale": self._agrandissement,
                      "/v1/images/remove-background": self._detourage}
            if chemin not in routes:
                return self._json(404, {"error": {"message": "inconnu"}})
            try:
                routes[chemin](corps)
            except EntreeInvalide as e:
                self._erreur(e.statut, "entree_invalide", str(e))
            except ErreurVenice as e:
                self._erreur(e.statut, "erreur_venice", str(e))
            except CookieExpire as e:
                self._json(503, {"error": {"message": "cookie Venice expiré", "detail": str(e)}})
            except Exception as e:
                self._json(502, {"error": {"message": str(e)[:300]}})

        def _json_requis(self, corps):
            try:
                req = json.loads(corps)
            except ValueError:
                raise EntreeInvalide("corps JSON invalide") from None
            if not isinstance(req, dict):
                raise EntreeInvalide("objet JSON attendu")
            return req

        def _chat(self, corps):
            req = self._json_requis(corps)
            modele = req["model"]
            if self._refus_payant(modele, req, GRATUITS):
                return
            images = contient_images(req["messages"])
            if images and (est_agent(modele) or (modele not in VISION_GRATUITS and req.get("autoriser_debit") is not True)):
                return self._erreur(400, "modele_sans_vision", f"{modele} ne lit pas les images avec ce pont. "
                                    f"Modèles vision sans pièce : {', '.join(VISION_GRATUITS)}.")
            if not self._limite(limiteur):
                return
            outils = req.get("tools") or None
            corps_venice = construire_corps_venice(modele, req["messages"], outils, req, medias)
            if est_agent(modele):
                texte, jetons = discuter_agent(jeton, modele, corps_venice)
            else:
                texte, jetons = "".join(morceaux_contenu(discuter(jeton, corps_venice))), 0
            contenu, appels = extraire_appels(texte, outils)
            rep = reponse_openai(modele, contenu, appels, jetons)
            if not req.get("stream"):
                return self._json(200, rep)
            self._sse(rep)

        def _images(self, corps):
            req = self._json_requis(corps)
            modele = ALIAS_IMAGES.get(req.get("model") or "default", req.get("model"))
            n = req.get("n", 1)
            if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= IMAGES_MAX_PAR_REQUETE:
                raise EntreeInvalide(f"n : entier de 1 à {IMAGES_MAX_PAR_REQUETE} attendu")
            reglages = IMAGES_GRATUITES.get(modele) or {"diviseur": 16, "pas": 20, "negatif": True, "prompt_max": 1500}
            corps_base = corps_image(req, modele, reglages)
            if self._refus_payant(modele, req, IMAGES_GRATUITES):
                return
            restant = quotas.restant("image") if quotas else None
            if restant is not None and restant - n < QUOTA_IMAGE_MINIMUM:
                return self._erreur(429, "quota_images_epuise", f"quota d'images du jour presque épuisé ({restant} restantes)")
            if not self._limite(limiteur_images, n):
                return
            donnees = []
            for _ in range(n):
                octets, genre, entetes = generer_image_venice(jeton, {**corps_base, "seed": secrets.randbelow(10 ** 8),
                                                                      "requestId": uuid.uuid4().hex[:7]})
                if entetes.get("x-venice-is-content-violation") == "true" or entetes.get("x-venice-is-blurred") == "true":
                    return self._erreur(400, "content_policy_violation", "Venice a refusé ou flouté l'image (contenu)")
                if quotas and entetes.get("x-ratelimit-remaining", "").isdigit():
                    quotas.noter("image", int(entetes["x-ratelimit-remaining"]))
                donnees.append({"b64_json": base64.b64encode(octets).decode()})
            reste = quotas.restant("image") if quotas else None
            self._json(200, {"created": int(time.time()), "data": donnees},
                       {"X-Venice-Quota-Image-Restant": str(reste)} if reste is not None else None)

        def _synthese(self, corps):
            req = self._json_requis(corps)
            modele = ALIAS_TTS.get(req.get("model") or "tts-1", req.get("model"))
            texte = req.get("input")
            if not isinstance(texte, str) or not texte.strip():
                raise EntreeInvalide("input : texte non vide requis")
            if len(texte) > TTS_MAX_CARACTERES:
                raise EntreeInvalide(f"input : {TTS_MAX_CARACTERES} caractères au plus")
            format_audio = req.get("response_format") or TTS_GRATUITS.get(modele, "mp3")
            if format_audio not in ("mp3", "wav"):
                raise EntreeInvalide("response_format : mp3 ou wav seulement")
            if self._refus_payant(modele, req, TTS_GRATUITS):
                return
            if not self._limite(limiteur_voix):
                return
            voix = req.get("voice")
            envoi = {"input": texte, "model": modele, "response_format": format_audio}
            if modele == TTS_DEFAUT:
                envoi["voice"] = VOIX_DEFAUT if not isinstance(voix, str) or voix in VOIX_OPENAI or not voix else voix
            elif isinstance(voix, str) and voix:
                envoi["voice"] = voix
            if isinstance(req.get("speed"), (int, float)) and not isinstance(req["speed"], bool):
                envoi["speed"] = min(2, max(0.75, req["speed"]))
            audio, genre = synthese_vocale_venice(jeton, envoi)
            self._octets(200, audio, genre)

        def _transcription(self, corps):
            champs, fichiers = lire_multipart(self.headers.get("Content-Type"), corps)
            if "file" not in fichiers:
                raise EntreeInvalide("file : fichier audio requis")
            format_reponse = champs.get("response_format") or "json"
            if format_reponse not in FORMATS_ASR:
                raise EntreeInvalide(f"response_format : {', '.join(FORMATS_ASR)}")
            nom, mime, octets = fichiers["file"]
            if len(octets) > AUDIO_MAX_OCTETS:
                raise EntreeTropGrosse(f"audio de {len(octets)} octets, maximum {AUDIO_MAX_OCTETS}")
            if not self._limite(limiteur_voix):
                return
            res = transcrire_venice(jeton, octets, nom or "voix.mp3", mime, format_reponse in ("verbose_json", "srt", "vtt"))
            genre, data = formater_transcription(res, format_reponse)
            self._octets(200, data, genre)

        def _entree_image(self, corps):
            """(champs, nom, type MIME, octets) d'une requête d'image : multipart (fichier `image`) ou JSON (`image` en data URL ou https)."""
            if (self.headers.get("Content-Type") or "").lower().startswith("multipart/form-data"):
                champs, fichiers = lire_multipart(self.headers.get("Content-Type"), corps)
                f = fichiers.get("image") or fichiers.get("image[]") or fichiers.get("file")
                if not f:
                    raise EntreeInvalide("image : fichier `image` requis")
                nom, mime, octets = f
                if len(octets) > IMAGE_MAX_OCTETS:
                    raise EntreeInvalide(f"image trop lourde ({len(octets)} octets, maximum {IMAGE_MAX_OCTETS})")
                return {k: (True if v == "true" else v) for k, v in champs.items()}, nom or "image.png", mime or "image/png", octets
            req = self._json_requis(corps)
            url = req.get("image")
            if isinstance(url, str) and url.startswith("https://"):
                mime, octets = telecharger_image(url)
            else:
                m = _DATA_IMAGE.match(url or "") if isinstance(url, str) else None
                if not m:
                    raise EntreeInvalide("image : data URL data:image/<type>;base64,... ou adresse https attendue")
                mime, octets = m.group(1).lower(), base64.b64decode(image_en_base64(url))
            return req, "image." + mime.split("/")[1], mime, octets

        def _sortie_images(self, donnees, quota=None, restant=None):
            self._json(200, {"created": int(time.time()), "data": donnees},
                       {f"X-Venice-Quota-{quota}-Restant": str(restant)} if restant is not None else None)

        def _ocr(self, corps):
            if (self.headers.get("Content-Type") or "").lower().startswith("multipart/form-data"):
                champs, fichiers = lire_multipart(self.headers.get("Content-Type"), corps)
                f = fichiers.get("file") or fichiers.get("image")
                nom, octets = (f[0], f[2]) if f else (None, None)
            else:
                champs = self._json_requis(corps)
                nom, octets = champs.get("filename") or "document", None
                donnees = champs.get("file_data") or champs.get("image")
                if isinstance(donnees, str) and donnees.startswith("https://"):
                    mime, octets = telecharger_image(donnees)
                elif isinstance(donnees, str) and donnees:
                    try:
                        octets = base64.b64decode(donnees.split("base64,", 1)[-1], validate=True)
                    except ValueError:
                        raise EntreeInvalide("ocr : base64 invalide") from None
            if not octets:
                raise EntreeInvalide("ocr : `image` (data URL ou https), `file_data` ou fichier `file` requis")
            if len(octets) > FICHIER_MAX_OCTETS:
                raise EntreeTropGrosse(f"fichier trop lourd (maximum {FICHIER_MAX_OCTETS} octets)")
            modele = champs.get("model") or OCR_MODELE
            if modele not in VISION_GRATUITS and champs.get("autoriser_debit") is not True:
                return self._erreur(400, "modele_sans_vision", f"{modele} n'est pas un modèle vision sans pièce : {', '.join(VISION_GRATUITS)}.")
            tronque = False
            if _type_image(octets):
                pages = [medias.ocr_image(base64.b64encode(octets).decode(), modele)]
            elif octets.lstrip()[:5] == b"%PDF-":
                pages, tronque = medias.ocr_pdf(octets, modele)
            else:
                pages = [analyser_fichier_venice(jeton, nom or "document", octets)]
            self._json(200, {"text": texte_des_pages(pages), "pages": pages, "tronque": tronque, "model": modele})

        def _embeddings(self, corps):
            req = self._json_requis(corps)
            entrees = req.get("input")
            entrees = [entrees] if isinstance(entrees, str) else entrees
            if (not isinstance(entrees, list) or not entrees or len(entrees) > EMBEDDINGS_MAX_ENTREES
                    or not all(isinstance(e, str) and 0 < len(e) <= EMBEDDINGS_MAX_CARACTERES for e in entrees)):
                raise EntreeInvalide(f"input : texte ou liste de 1 à {EMBEDDINGS_MAX_ENTREES} textes non vides "
                                     f"({EMBEDDINGS_MAX_CARACTERES} caractères au plus chacun)")
            if req.get("encoding_format") not in (None, "float"):
                raise EntreeInvalide("encoding_format : float seulement")
            if not self._limite(limiteur):
                return
            rep = embeddings_venice(jeton, entrees)
            self._json(200, {**rep, "model": rep.get("model", EMBEDDING_MODELE)})

        def _edition(self, corps):
            req, nom, mime, octets = self._entree_image(corps)
            prompt = req.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise EntreeInvalide("prompt : texte non vide requis")
            modele = ALIAS_EDITS.get(req.get("model") or "default", req.get("model"))
            try:
                n = int(req.get("n", 1))
            except (TypeError, ValueError):
                n = 0
            if not 1 <= n <= EDITS_MAX_PAR_REQUETE:
                raise EntreeInvalide(f"n : entier de 1 à {EDITS_MAX_PAR_REQUETE} attendu")
            if self._refus_payant(modele, req, EDITS_GRATUITES):
                return
            restant = quotas.restant("inpaint") if quotas else None
            if restant is not None and restant - n < QUOTA_IMAGE_MINIMUM:
                return self._erreur(429, "quota_images_epuise", f"quota d'éditions du jour presque épuisé ({restant} restantes)")
            if not self._limite(limiteur_images, n):
                return
            donnees = []
            for _ in range(n):
                image, _genre, entetes = editer_image_venice(jeton, modele, prompt, octets, nom, mime)
                if entetes.get("x-venice-is-content-violation") == "true":
                    return self._erreur(400, "content_policy_violation", "Venice a refusé l'image (contenu)")
                if quotas and entetes.get("x-ratelimit-remaining", "").isdigit():
                    quotas.noter("inpaint", int(entetes["x-ratelimit-remaining"]))
                donnees.append({"b64_json": base64.b64encode(image).decode()})
            self._sortie_images(donnees, "Inpaint", quotas.restant("inpaint") if quotas else None)

        def _agrandissement(self, corps):
            req, nom, mime, octets = self._entree_image(corps)
            try:
                echelle = int(req.get("scale", 2))
            except (TypeError, ValueError):
                echelle = 0
            if echelle not in ECHELLES_UPSCALE:
                raise EntreeInvalide(f"scale : {' ou '.join(map(str, ECHELLES_UPSCALE))}")
            if not self._limite(limiteur_images):
                return
            image, _genre, _entetes = agrandir_venice(jeton, octets, nom, mime, echelle)
            self._sortie_images([{"b64_json": base64.b64encode(image).decode()}])

        def _detourage(self, corps):
            _req, _nom, mime, octets = self._entree_image(corps)
            if not self._limite(limiteur_images):
                return
            image, _genre, _entetes = detourer_venice(jeton, f"data:{mime};base64,{base64.b64encode(octets).decode()}")
            self._sortie_images([{"b64_json": base64.b64encode(image).decode()}])

        def _sse(self, rep):
            morceaux = morceaux_sse(rep)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "close")
            self.end_headers()
            for m in morceaux:
                self.wfile.write(b"data: " + json.dumps(m, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.close_connection = True

    return H


class ServeurPont(ThreadingHTTPServer):
    request_queue_size = 64  # 5 par défaut : des rafales de 8 à 16 requêtes se faisaient réinitialiser
    daemon_threads = True


def main():
    fichier = os.environ.get("VENICE_PONT_ENV", "~/.config/venice-setup/defaut/venice.env")
    env = lire_env(fichier)
    source = SourceClerk(env["VENICE_CLERK_CLIENT"], fichier)
    jeton = JetonClerk(source.mint)
    hote, port = os.environ.get("VENICE_PONT_ECOUTE", "127.0.0.1:8700").split(":")
    limiteur = LimiteurDebit(int(os.environ.get("VENICE_PONT_MAX_PAR_MIN", "20")))
    suivi = SuiviCredits(lambda: lire_solde(jeton), fichier=os.path.expanduser(
        os.environ.get("VENICE_PONT_CREDITS", "~/.config/venice-setup/defaut/credits.json")))
    limiteur_images = LimiteurDebit(int(os.environ.get("VENICE_PONT_MAX_IMAGES_PAR_MIN", "10")))
    limiteur_voix = LimiteurDebit(int(os.environ.get("VENICE_PONT_MAX_VOIX_PAR_MIN", "30")))
    quotas = SuiviQuotas(lambda: lire_quotas_venice(jeton))
    srv = ServeurPont((hote, int(port)), fabriquer_handler(jeton, env["VENICE_PONT_CLE"], source, limiteur, suivi,
                                                           limiteur_images, limiteur_voix, quotas))
    threading.Thread(target=boucle_touche, args=(source,), daemon=True).start()
    threading.Thread(target=boucle_credits, args=(suivi,), daemon=True).start()
    threading.Thread(target=boucle_quotas, args=(quotas,), daemon=True).start()
    print(f"venice-pont à l'écoute sur {hote}:{port}", file=sys.stderr, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
