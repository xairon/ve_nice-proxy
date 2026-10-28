"""OCR (images et PDF scannés), audio en entrée, embeddings, édition, agrandissement, détourage, recherche web."""
import base64
import json
import struct
import sys
import threading
import urllib.error
import urllib.request
import uuid
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import venice_pont as vp  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PNG_B64 = base64.b64encode(PNG).decode()
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40 + b"\xff\xd9"


# --- PDF : images intégrées ---------------------------------------------------------------------------------

def _pdf(*objets_image):
    """PDF minimal dont chaque entrée est (dictionnaire d'image, flux brut)."""
    sortie = b"%PDF-1.4\n"
    for i, (dico, flux) in enumerate(objets_image, 10):
        sortie += f"{i} 0 obj\n<<{dico} /Length {len(flux)}>>\nstream\n".encode() + flux + b"\nendstream\nendobj\n"
    return sortie + b"trailer<<>>\n%%EOF"


def _image_dico(filtre, largeur=200, hauteur=100, espace="/DeviceRGB", extra=""):
    return f"/Type /XObject /Subtype /Image /Width {largeur} /Height {hauteur} /ColorSpace {espace} /BitsPerComponent 8 /Filter {filtre} {extra}"


def test_pdf_jpeg_integre_est_extrait_tel_quel():
    pdf = _pdf((_image_dico("/DCTDecode"), JPEG))
    assert vp.images_integrees_pdf(pdf) == [("image/jpeg", JPEG)]


def test_pdf_flate_sans_predicteur_devient_un_png_valide():
    brut = bytes(i % 256 for i in range(600)) * 100                       # 200 x 100, RGB, 8 bits
    pdf = _pdf((_image_dico("/FlateDecode"), zlib.compress(brut)))
    (mime, png), = vp.images_integrees_pdf(pdf)
    assert mime == "image/png" and png.startswith(b"\x89PNG\r\n\x1a\n")
    larg, haut, prof, couleur = struct.unpack(">IIBB", png[16:26])
    assert (larg, haut, prof, couleur) == (200, 100, 8, 2)
    idat = b"".join(png[i + 4:i + 4 + n] for i, n in _blocs(png, b"IDAT"))
    lignes = zlib.decompress(idat)
    assert len(lignes) == 100 * (1 + 600) and lignes[0] == 0 and lignes[1:601] == brut[:600]


def _blocs(png, nom):
    i = 8
    while i < len(png):
        n = struct.unpack(">I", png[i:i + 4])[0]
        if png[i + 4:i + 8] == nom:
            yield i + 4, n
        i += 12 + n


def test_pdf_flate_avec_predicteur_png_est_reutilise_sans_recompression():
    lignes = b"".join(b"\x00" + bytes([j]) * 600 for j in range(100))
    compresse = zlib.compress(lignes)
    pdf = _pdf((_image_dico("/FlateDecode", extra="/DecodeParms << /Predictor 15 /Colors 3 /Columns 200 >>"), compresse))
    (_, png), = vp.images_integrees_pdf(pdf)
    idat = b"".join(png[i + 4:i + 4 + n] for i, n in _blocs(png, b"IDAT"))
    assert zlib.decompress(idat) == lignes


def test_pdf_niveaux_de_gris_et_ordre_des_pages():
    gris = _image_dico("/FlateDecode", espace="/DeviceGray", largeur=120, hauteur=120)
    pdf = _pdf((gris, zlib.compress(b"\x10" * 14400)), (_image_dico("/DCTDecode"), JPEG))
    mimes = [m for m, _ in vp.images_integrees_pdf(pdf)]
    assert mimes == ["image/png", "image/jpeg"]


def test_pdf_petites_images_ignorees_et_formats_non_pris_en_charge_signales():
    logo = _pdf((_image_dico("/DCTDecode", largeur=32, hauteur=32), JPEG))
    assert vp.images_integrees_pdf(logo) == []
    fax = _pdf((_image_dico("/CCITTFaxDecode"), b"\x00" * 10))
    with pytest.raises(vp.EntreeInvalide, match="CCITTFaxDecode"):
        vp.images_integrees_pdf(fax)


def test_pdf_sans_image_donne_une_liste_vide():
    assert vp.images_integrees_pdf(b"%PDF-1.4\n1 0 obj<<>>endobj") == []


def test_pages_pdf_prefere_pdftoppm_puis_les_images_integrees(monkeypatch, tmp_path):
    pdf = _pdf((_image_dico("/DCTDecode"), JPEG))
    monkeypatch.setattr(vp.shutil, "which", lambda n: None)
    assert vp.pages_pdf(pdf) == [("image/jpeg", JPEG)]

    appels = []

    def faux_run(cmd, **kw):
        appels.append(cmd)
        sortie = Path(cmd[-1])
        (sortie.parent / (sortie.name + "-1.png")).write_bytes(PNG)
        (sortie.parent / (sortie.name + "-2.png")).write_bytes(PNG + b"2")

        class R:
            returncode = 0
        return R()
    monkeypatch.setattr(vp.shutil, "which", lambda n: "/usr/bin/pdftoppm")
    monkeypatch.setattr(vp.subprocess, "run", faux_run)
    assert vp.pages_pdf(pdf) == [("image/png", PNG), ("image/png", PNG + b"2")]
    assert appels[0][0] == "/usr/bin/pdftoppm" and "-png" in appels[0]


def test_pages_pdf_repli_sur_les_images_integrees_si_pdftoppm_echoue(monkeypatch):
    panne = OSError("pas de dossier temporaire")
    pdf = _pdf((_image_dico("/DCTDecode"), JPEG))
    monkeypatch.setattr(vp.shutil, "which", lambda n: "/usr/bin/pdftoppm")

    def casse(*a, **k):
        raise panne
    monkeypatch.setattr(vp.subprocess, "run", casse)
    assert vp.pages_pdf(pdf) == [("image/jpeg", JPEG)]


def test_pages_pdf_repli_si_pdftoppm_depasse_son_delai(monkeypatch):
    pdf = _pdf((_image_dico("/DCTDecode"), JPEG))
    monkeypatch.setattr(vp.shutil, "which", lambda n: "/usr/bin/pdftoppm")

    def lent(*a, **k):
        raise vp.subprocess.TimeoutExpired("pdftoppm", 1)
    monkeypatch.setattr(vp.subprocess, "run", lent)
    assert vp.pages_pdf(pdf) == [("image/jpeg", JPEG)]


def test_pages_pdf_aucun_moyen_de_rendu(monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda n: None)
    with pytest.raises(vp.EntreeInvalide, match="poppler"):
        vp.pages_pdf(b"%PDF-1.4\nrien")


# --- serveur ------------------------------------------------------------------------------------------------

class _Jeton:
    def obtenir(self):
        return "j"

    def etat(self):
        return {"cookie_ok": True}


@pytest.fixture
def serveur(monkeypatch):
    j = {"chat": [], "asr": [], "emb": [], "edit": [], "up": [], "bg": [], "parser": []}

    def faux_discuter(jeton, corps):
        j["chat"].append(corps)
        dernier = corps["prompt"][-1]
        reponse = "TEXTE LU" if "imagePath" in dernier else "réponse"
        return iter([json.dumps({"kind": "content", "content": reponse})])

    def faux_asr(jeton, octets, nom, mime, timestamps):
        j["asr"].append((nom, mime, len(octets)))
        return {"text": "bonjour depuis l'audio"}

    def faux_parser(jeton, nom, octets):
        j["parser"].append(nom)
        if octets.startswith(b"%PDF-scan"):
            raise vp.EntreeInvalide(f"fichier {nom} : illisible ou sans texte extractible (PDF scanné ?)")
        return "texte natif"

    monkeypatch.setattr(vp, "discuter", faux_discuter)
    monkeypatch.setattr(vp, "transcrire_venice", faux_asr)
    monkeypatch.setattr(vp, "analyser_fichier_venice", faux_parser)
    monkeypatch.setattr(vp, "pages_pdf", lambda octets: [("image/png", PNG), ("image/png", PNG + b"p2")])
    monkeypatch.setattr(vp, "embeddings_venice", lambda jeton, entrees: j["emb"].append(entrees) or {
        "object": "list", "model": "text-embedding-bge-m3", "usage": {"prompt_tokens": 3, "total_tokens": 3},
        "data": [{"index": i, "object": "embedding", "embedding": [0.1, 0.2]} for i, _ in enumerate(entrees)]})

    def faux_edit(jeton, modele, prompt, octets, nom, mime):
        j["edit"].append((modele, prompt, nom, mime))
        return PNG, "image/png", {"x-ratelimit-remaining": "900", "x-ratelimit-type": "inpaint"}
    monkeypatch.setattr(vp, "editer_image_venice", faux_edit)
    monkeypatch.setattr(vp, "agrandir_venice", lambda jeton, octets, nom, mime, echelle: j["up"].append(echelle) or (PNG, "image/png", {}))
    monkeypatch.setattr(vp, "detourer_venice", lambda jeton, data_url: j["bg"].append(data_url[:22]) or (PNG, "image/png", {}))

    quotas = vp.SuiviQuotas(lambda: {"image": {"remaining": 900}, "inpaint": {"remaining": 900}})
    srv = vp.ServeurPont(("127.0.0.1", 0), vp.fabriquer_handler(
        _Jeton(), "cle", None, limiteur=vp.LimiteurDebit(100), limiteur_images=vp.LimiteurDebit(4), limiteur_voix=vp.LimiteurDebit(100),
        quotas=quotas))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def requete(chemin, corps=None, brut=None, type_contenu="application/json", cle="cle"):
        donnees = brut if brut is not None else (None if corps is None else json.dumps(corps).encode())
        req = urllib.request.Request(base + chemin, data=donnees, method="GET" if donnees is None else "POST",
                                     headers={"Authorization": "Bearer " + cle, "Content-Type": type_contenu})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    yield requete, j, quotas
    srv.shutdown()


def _multipart(champs, fichiers):
    limite = "----" + uuid.uuid4().hex
    corps = b""
    for k, v in champs.items():
        corps += f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, (nom, octets, mime) in fichiers.items():
        corps += (f'--{limite}\r\nContent-Disposition: form-data; name="{k}"; filename="{nom}"\r\nContent-Type: {mime}\r\n\r\n').encode() + octets + b"\r\n"
    return corps + f"--{limite}--\r\n".encode(), f"multipart/form-data; boundary={limite}"


def _json(b):
    return json.loads(b)


# --- OCR ----------------------------------------------------------------------------------------------------

def test_ocr_d_une_image_data_url(serveur):
    requete, j, _ = serveur
    st, corps, _ = requete("/v1/ocr", {"image": "data:image/png;base64," + PNG_B64})
    rep = _json(corps)
    assert st == 200 and rep["text"] == "TEXTE LU" and rep["pages"] == ["TEXTE LU"]
    c = j["chat"][0]
    assert c["modelId"] == "qwen-3-8-27b" and c["prompt"][-1]["imagePath"] == [PNG_B64] and "Transcris" in c["prompt"][-1]["content"]
    assert c["temperature"] == 0


def test_ocr_d_un_pdf_scanne_page_par_page(serveur):
    requete, j, _ = serveur
    pdf = b"%PDF-scan"
    st, corps, _ = requete("/v1/ocr", {"file_data": "data:application/pdf;base64," + base64.b64encode(pdf).decode(), "filename": "scan.pdf"})
    rep = _json(corps)
    assert st == 200 and rep["pages"] == ["TEXTE LU", "TEXTE LU"] and rep["text"] == "TEXTE LU\n\n--- page 2 ---\n\nTEXTE LU"
    assert len(j["chat"]) == 2


def test_ocr_en_multipart(serveur):
    requete, j, _ = serveur
    corps, ct = _multipart({"model": "qwen3-vl-235b-a22b"}, {"file": ("t.png", PNG, "image/png")})
    st, rep, _ = requete("/v1/ocr", brut=corps, type_contenu=ct)
    assert st == 200 and _json(rep)["text"] == "TEXTE LU" and j["chat"][0]["modelId"] == "qwen3-vl-235b-a22b"


def test_ocr_refuse_un_modele_sans_vision_et_une_entree_vide(serveur):
    requete, j, _ = serveur
    assert requete("/v1/ocr", {"image": "data:image/png;base64," + PNG_B64, "model": "aion-labs-aion-3-0"})[0] == 400
    assert requete("/v1/ocr", {})[0] == 400
    assert j["chat"] == []


def test_ocr_limite_le_nombre_de_pages(serveur, monkeypatch):
    requete, j, _ = serveur
    monkeypatch.setattr(vp, "OCR_PAGES_MAX", 1)
    pdf = base64.b64encode(b"%PDF-scan").decode()
    st, corps, _ = requete("/v1/ocr", {"file_data": "data:application/pdf;base64," + pdf})
    assert st == 200 and len(_json(corps)["pages"]) == 1 and _json(corps)["tronque"] is True


def test_pdf_scanne_en_piece_jointe_est_lu_automatiquement(serveur):
    requete, j, _ = serveur
    pdf = "data:application/pdf;base64," + base64.b64encode(b"%PDF-scan").decode()
    msg = [{"type": "file", "file": {"filename": "scan.pdf", "file_data": pdf}}, {"type": "text", "text": "Résume"}]
    st, corps, _ = requete("/v1/chat/completions", {"model": "qwen-3-8-27b", "messages": [{"role": "user", "content": msg}]})
    assert st == 200
    envoye = j["chat"][-1]["prompt"][0]
    assert envoye["isFile"] is True and "TEXTE LU" in envoye["content"] and envoye["content"].endswith("Résume")


def test_pdf_avec_texte_ne_declenche_pas_l_ocr(serveur):
    requete, j, _ = serveur
    pdf = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 texte").decode()
    msg = [{"type": "file", "file": {"filename": "n.pdf", "file_data": pdf}}]
    assert requete("/v1/chat/completions", {"model": "qwen-3-8-27b", "messages": [{"role": "user", "content": msg}]})[0] == 200
    assert "texte natif" in j["chat"][-1]["prompt"][0]["content"] and len(j["chat"]) == 1


def test_image_en_piece_jointe_fichier_est_lue_par_ocr(serveur):
    requete, j, _ = serveur
    png = "data:image/png;base64," + PNG_B64
    msg = [{"type": "file", "file": {"filename": "photo.png", "file_data": png}}]
    st, *_ = requete("/v1/chat/completions", {"model": "qwen-3-8-27b", "messages": [{"role": "user", "content": msg}]})
    assert st == 200 and "TEXTE LU" in j["chat"][-1]["prompt"][0]["content"] and j["parser"] == []


# --- audio en entrée ----------------------------------------------------------------------------------------

def test_audio_en_entree_est_transcrit_puis_injecte(serveur):
    requete, j, _ = serveur
    audio = base64.b64encode(b"RIFFfake").decode()
    msg = [{"type": "text", "text": "Que dit-il ?"}, {"type": "input_audio", "input_audio": {"data": audio, "format": "wav"}}]
    st, *_ = requete("/v1/chat/completions", {"model": "qwen-3-8-27b", "messages": [{"role": "user", "content": msg}]})
    assert st == 200 and j["asr"] == [("audio.wav", "audio/wav", 8)]
    assert j["chat"][0]["prompt"][0]["content"] == "Que dit-il ?[Audio transcrit : bonjour depuis l'audio]"


def test_audio_format_inconnu_ou_base64_invalide_refuse(serveur):
    requete, j, _ = serveur
    for audio in ({"data": "@@@", "format": "wav"}, {"data": "QUJD", "format": "exe"}, {"format": "wav"}):
        st, *_ = requete("/v1/chat/completions", {"model": "qwen-3-8-27b", "messages": [{"role": "user", "content": [
            {"type": "input_audio", "input_audio": audio}]}]})
        assert st == 400
    assert j["asr"] == []


# --- embeddings ---------------------------------------------------------------------------------------------

def test_embeddings_chaine_ou_liste(serveur):
    requete, j, _ = serveur
    st, corps, _ = requete("/v1/embeddings", {"model": "text-embedding-3-small", "input": "bonjour"})
    assert st == 200 and _json(corps)["data"][0]["embedding"] == [0.1, 0.2] and j["emb"] == [["bonjour"]]
    st, corps, _ = requete("/v1/embeddings", {"input": ["a", "b"]})
    assert len(_json(corps)["data"]) == 2 and _json(corps)["model"] == "text-embedding-bge-m3"


def test_embeddings_refus(serveur):
    requete, j, _ = serveur
    for corps in ({}, {"input": []}, {"input": [1]}, {"input": "x" * 20000}, {"input": ["a"] * 100}, {"input": "a", "encoding_format": "base64"}):
        assert requete("/v1/embeddings", corps)[0] == 400, corps
    assert j["emb"] == []


# --- édition, agrandissement, détourage ----------------------------------------------------------------------

def test_edition_multipart_renvoie_b64_json_et_note_le_quota(serveur):
    requete, j, quotas = serveur
    corps, ct = _multipart({"prompt": "pomme verte", "model": "gpt-image-1"}, {"image": ("p.png", PNG, "image/png")})
    st, rep, entetes = requete("/v1/images/edits", brut=corps, type_contenu=ct)
    assert st == 200 and base64.b64decode(_json(rep)["data"][0]["b64_json"]) == PNG
    assert j["edit"] == [("qwen-edit-uncensored", "pomme verte", "p.png", "image/png")]
    assert quotas.restant("inpaint") == 900 and entetes["X-Venice-Quota-Inpaint-Restant"] == "900"


def test_edition_en_json_et_modele_firered(serveur):
    requete, j, _ = serveur
    st, *_ = requete("/v1/images/edits", {"model": "firered-image-edit", "prompt": "bleu", "image": "data:image/png;base64," + PNG_B64})
    assert st == 200 and j["edit"][0][0] == "firered-image-edit"


def test_edition_refus(serveur):
    requete, j, quotas = serveur
    corps, ct = _multipart({"prompt": "x", "model": "flux-2-pro-edit"}, {"image": ("p.png", PNG, "image/png")})
    assert requete("/v1/images/edits", brut=corps, type_contenu=ct)[0] == 403
    corps, ct = _multipart({"prompt": "x"}, {})
    assert requete("/v1/images/edits", brut=corps, type_contenu=ct)[0] == 400
    corps, ct = _multipart({}, {"image": ("p.png", PNG, "image/png")})
    assert requete("/v1/images/edits", brut=corps, type_contenu=ct)[0] == 400
    quotas.noter("inpaint", 2)
    corps, ct = _multipart({"prompt": "x"}, {"image": ("p.png", PNG, "image/png")})
    st, rep, _ = requete("/v1/images/edits", brut=corps, type_contenu=ct)
    assert st == 429 and _json(rep)["error"]["code"] == "quota_images_epuise" and j["edit"] == []


def test_agrandissement_et_detourage(serveur):
    requete, j, _ = serveur
    corps, ct = _multipart({"scale": "2"}, {"image": ("p.png", PNG, "image/png")})
    st, rep, _ = requete("/v1/images/upscale", brut=corps, type_contenu=ct)
    assert st == 200 and base64.b64decode(_json(rep)["data"][0]["b64_json"]) == PNG and j["up"] == [2]
    st, rep, _ = requete("/v1/images/remove-background", {"image": "data:image/png;base64," + PNG_B64})
    assert st == 200 and j["bg"] == ["data:image/png;base64,"]
    corps, ct = _multipart({"scale": "16"}, {"image": ("p.png", PNG, "image/png")})
    assert requete("/v1/images/upscale", brut=corps, type_contenu=ct)[0] == 400


def test_les_modeles_d_edition_sont_listes(serveur):
    requete, *_ = serveur
    ids = {m["id"]: m["owned_by"] for m in _json(requete("/v1/images/models")[1])["data"]}
    assert ids["qwen-edit-uncensored"] == "venice-image-edit" and ids["z-image-turbo"] == "venice-image"


# --- recherche web ------------------------------------------------------------------------------------------

def test_web_search_options_openai_active_la_recherche():
    corps = vp.construire_corps_venice("m", [{"role": "user", "content": "x"}], None, {"web_search_options": {}})
    assert corps["webEnabled"] is True and corps["webScrapeEnabled"] is False
    corps = vp.construire_corps_venice("m", [{"role": "user", "content": "x"}], None, {"web_scrape": True, "x_search": True})
    assert corps["webScrapeEnabled"] is True and corps["xSearchEnabled"] is True and corps["webEnabled"] is False
