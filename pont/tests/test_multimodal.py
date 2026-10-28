"""Multimodal : images en entrée (vision), fichiers, images en sortie, voix (TTS et ASR)."""
import base64
import json
import sys
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import venice_pont as vp  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PNG_B64 = base64.b64encode(PNG).decode()
PNG_URL = "data:image/png;base64," + PNG_B64


class MediasFaux:
    """Remplace le réseau : télécharge une image et extrait le texte d'un fichier."""

    def __init__(self):
        self.telechargements, self.fichiers = [], []

    def image(self, url):
        if url.startswith("https://"):
            self.telechargements.append(url)
            return PNG_B64
        return vp.image_en_base64(url)

    def fichier(self, nom, octets):
        self.fichiers.append((nom, octets))
        return "texte du fichier"


def _msg(*parties, role="user"):
    return {"role": role, "content": list(parties)}


def _image(url=PNG_URL):
    return {"type": "image_url", "image_url": {"url": url}}


def _texte(t):
    return {"type": "text", "text": t}


# --- entrée image -----------------------------------------------------------------------------------------

def test_image_data_url_devient_image_path_en_base64_brut():
    corps = vp.construire_corps_venice("qwen-3-8-27b", [_msg(_texte("Décris"), _image())], None, {}, MediasFaux())
    assert corps["prompt"] == [{"role": "user", "content": "Décris", "imagePath": [PNG_B64]}]


def test_image_https_est_telechargee_par_le_pont():
    medias = MediasFaux()
    corps = vp.construire_corps_venice("m", [_msg(_texte("?"), _image("https://exemple.org/a.png"))], None, {}, medias)
    assert medias.telechargements == ["https://exemple.org/a.png"]
    assert corps["prompt"][0]["imagePath"] == [PNG_B64]


def test_url_sous_forme_de_chaine_est_acceptee():
    corps = vp.construire_corps_venice("m", [_msg({"type": "image_url", "image_url": PNG_URL})], None, {}, MediasFaux())
    assert corps["prompt"][0]["imagePath"] == [PNG_B64]


def test_seul_le_dernier_message_avec_image_garde_ses_images():
    msgs = [_msg(_texte("a"), _image()), {"role": "assistant", "content": "vu"}, _msg(_texte("b"), _image())]
    corps = vp.construire_corps_venice("m", msgs, None, {}, MediasFaux())
    assert [("imagePath" in m) for m in corps["prompt"]] == [False, False, True]


def test_texte_sans_image_reste_une_chaine():
    corps = vp.construire_corps_venice("m", [_msg(_texte("a"), _texte("b"))], None, {}, MediasFaux())
    assert corps["prompt"] == [{"role": "user", "content": "ab"}]


@pytest.mark.parametrize("url", [
    "data:image/svg+xml;base64," + PNG_B64,        # SVG : refusé comme dans le site
    "data:text/plain;base64," + PNG_B64,
    "data:image/png;base64,@@@pas-du-base64@@@",
    "data:image/png;base64,",
    "ftp://exemple.org/a.png",
    "file:///etc/passwd",
])
def test_image_invalide_est_refusee(url):
    with pytest.raises(vp.EntreeInvalide):
        vp.image_en_base64(url)


def test_image_trop_lourde_est_refusee(monkeypatch):
    monkeypatch.setattr(vp, "IMAGE_MAX_OCTETS", 10)
    with pytest.raises(vp.EntreeInvalide, match="trop lourde"):
        vp.image_en_base64(PNG_URL)


def test_trop_d_images_sont_refusees(monkeypatch):
    monkeypatch.setattr(vp, "IMAGES_MAX", 2)
    with pytest.raises(vp.EntreeInvalide, match="images"):
        vp.construire_corps_venice("m", [_msg(_image(), _image(), _image())], None, {}, MediasFaux())


def test_audio_direct_n_est_pas_pris_en_charge():
    with pytest.raises(vp.EntreeInvalide, match="audio"):
        vp.construire_corps_venice("m", [_msg({"type": "input_audio", "input_audio": {"data": "x", "format": "wav"}})],
                                   None, {}, MediasFaux())


def test_sans_resolveur_une_image_est_refusee_proprement():
    with pytest.raises(vp.EntreeInvalide):
        vp.construire_corps_venice("m", [_msg(_image())], None, {})


@pytest.mark.parametrize("hote,attendu", [
    ("127.0.0.1", False), ("10.0.0.5", False), ("192.168.1.2", False), ("100.64.0.1", False),
    ("169.254.169.254", False), ("::1", False), ("fd00::1", False), ("8.8.8.8", True), ("1.1.1.1", True),
])
def test_adresse_publique(hote, attendu):
    assert vp.adresse_publique(hote) is attendu


def test_telechargement_refuse_http_et_hotes_prives():
    with pytest.raises(vp.EntreeInvalide):
        vp.telecharger_image("http://exemple.org/a.png")
    with pytest.raises(vp.EntreeInvalide, match="adresse"):
        vp.telecharger_image("https://127.0.0.1/a.png")
    with pytest.raises(vp.EntreeInvalide, match="adresse"):
        vp.telecharger_image("https://100.64.0.1:8700/a.png")


# --- entrée fichier ---------------------------------------------------------------------------------------

def test_fichier_texte_est_injecte_comme_le_fait_le_site():
    medias = MediasFaux()
    donnees = "data:application/pdf;base64," + base64.b64encode(b"%PDF-contenu").decode()
    part = {"type": "file", "file": {"filename": "facture.pdf", "file_data": donnees}}
    corps = vp.construire_corps_venice("m", [_msg(part, _texte("Résume"))], None, {}, medias)
    assert medias.fichiers == [("facture.pdf", b"%PDF-contenu")]
    m = corps["prompt"][0]
    assert m["isFile"] is True and "imagePath" not in m
    assert m["content"] == "The following content is from a file named facture.pdf: texte du fichier  Résume"


def test_fichier_par_identifiant_est_refuse():
    with pytest.raises(vp.EntreeInvalide, match="file_id"):
        vp.construire_corps_venice("m", [_msg({"type": "file", "file": {"file_id": "file-1"}})], None, {}, MediasFaux())


# --- serveur ----------------------------------------------------------------------------------------------

class _Jeton:
    def obtenir(self):
        return "j"

    def etat(self):
        return {"cookie_ok": True}


@pytest.fixture
def serveur(monkeypatch, tmp_path):
    journal = {"chat": [], "image": [], "tts": [], "asr": []}

    def faux_discuter(jeton, corps):
        journal["chat"].append(corps)
        return iter(['{"kind":"content","content":"je vois un pixel"}'])

    def faux_image(jeton, corps):
        journal["image"].append(corps)
        return PNG, "image/png", {"x-ratelimit-remaining": "900", "x-venice-is-content-violation": "false",
                                  "x-venice-is-blurred": "false"}

    def faux_tts(jeton, corps):
        journal["tts"].append(corps)
        return b"ID3-audio", "audio/mpeg" if corps.get("response_format", "mp3") == "mp3" else "audio/wav"

    def faux_asr(jeton, octets, nom, mime, timestamps):
        journal["asr"].append((octets, nom, mime, timestamps))
        res = {"text": "bonjour le monde"}
        if timestamps:
            res["timestamps"] = [{"start": 0.0, "end": 1.2, "text": "bonjour"}, {"start": 1.2, "end": 2.5, "text": "le monde"}]
        return res

    for nom, f in (("discuter", faux_discuter), ("generer_image_venice", faux_image),
                   ("synthese_vocale_venice", faux_tts), ("transcrire_venice", faux_asr)):
        monkeypatch.setattr(vp, nom, f)
    medias = MediasFaux()
    quotas = vp.SuiviQuotas(lambda: {"image": {"remaining": 900, "resetAt": 1}, "chat": {"remaining": 9000, "resetAt": 1}})
    srv = vp.ServeurPont(("127.0.0.1", 0), vp.fabriquer_handler(
        _Jeton(), "cle", None, limiteur=vp.LimiteurDebit(100), suivi=None,
        limiteur_images=vp.LimiteurDebit(3), limiteur_voix=vp.LimiteurDebit(3), quotas=quotas, medias=medias))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def requete(chemin, corps=None, cle="cle", brut=None, type_contenu="application/json"):
        donnees = brut if brut is not None else (None if corps is None else json.dumps(corps).encode())
        req = urllib.request.Request(base + chemin, data=donnees, method="GET" if donnees is None else "POST",
                                     headers={"Authorization": "Bearer " + cle, "Content-Type": type_contenu})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    yield requete, journal, quotas, medias
    srv.shutdown()


def _json(corps):
    return json.loads(corps)


def _chat(modele, contenu, **extra):
    return {"model": modele, "messages": [{"role": "user", "content": contenu}], **extra}


def test_serveur_transmet_l_image_a_un_modele_vision(serveur):
    requete, journal, *_ = serveur
    st, corps, _ = requete("/v1/chat/completions", _chat("qwen-3-8-27b", [_texte("Quoi ?"), _image()]))
    assert st == 200 and _json(corps)["choices"][0]["message"]["content"] == "je vois un pixel"
    assert journal["chat"][0]["prompt"][0]["imagePath"] == [PNG_B64]


def test_serveur_refuse_une_image_sur_un_modele_sans_vision(serveur):
    requete, journal, *_ = serveur
    st, corps, _ = requete("/v1/chat/completions", _chat("aion-labs-aion-3-0", [_image()]))
    assert st == 400 and _json(corps)["error"]["code"] == "modele_sans_vision" and journal["chat"] == []


def test_serveur_refuse_une_image_sur_la_route_agents(serveur):
    requete, journal, *_ = serveur
    st, corps, _ = requete("/v1/chat/completions", _chat("kimi-k2-5", [_image()]))
    assert st == 400 and _json(corps)["error"]["code"] == "modele_sans_vision"


def test_serveur_signale_une_image_illisible_en_400(serveur):
    requete, *_ = serveur
    st, corps, _ = requete("/v1/chat/completions", _chat("qwen-3-8-27b", [_image("data:image/png;base64,@@@")]))
    assert st == 400 and _json(corps)["error"]["code"] == "entree_invalide"


def test_serveur_refuse_un_corps_trop_gros(serveur, monkeypatch):
    requete, *_ = serveur
    monkeypatch.setattr(vp, "CORPS_MAX_OCTETS", 100)
    st, corps, _ = requete("/v1/chat/completions", _chat("qwen-3-8-27b", "x" * 500))
    assert st == 413


def test_les_modeles_vision_sont_annonces(serveur):
    requete, *_ = serveur
    modeles = {m["id"]: m for m in _json(requete("/v1/models")[1])["data"]}
    assert modeles["qwen-3-8-27b"]["vision"] is True and modeles["aion-labs-aion-3-0"]["vision"] is False


# --- sortie image -----------------------------------------------------------------------------------------

def test_dimensions_multiples_du_diviseur_et_bornees():
    assert vp.dimensions_depuis_size("1024x1024", 8) == (1024, 1024)
    assert vp.dimensions_depuis_size("1000x700", 16) == (992, 688)
    assert vp.dimensions_depuis_size(None, 8) == (1024, 1024)
    assert vp.dimensions_depuis_size("auto", 8) == (1024, 1024)
    assert vp.dimensions_depuis_size("99999x99999", 8) == (1280, 1280)
    assert vp.dimensions_depuis_size("10x10", 8) == (256, 256)
    with pytest.raises(vp.EntreeInvalide):
        vp.dimensions_depuis_size("grand", 8)


def test_generation_renvoie_du_b64_json_et_le_quota(serveur):
    requete, journal, *_ = serveur
    st, corps, entetes = requete("/v1/images/generations", {"model": "z-image-turbo", "prompt": "une pomme", "size": "512x512"})
    rep = _json(corps)
    assert st == 200 and base64.b64decode(rep["data"][0]["b64_json"]) == PNG and "created" in rep
    c = journal["image"][0]
    assert (c["modelId"], c["prompt"], c["width"], c["height"], c["format"]) == ("z-image-turbo", "une pomme", 512, 512, "png")
    assert "acceptCreditFallback" not in c            # jamais de repli sur les crédits
    assert entetes["X-Venice-Quota-Image-Restant"] == "900"


def test_generation_modele_par_defaut_et_alias_openai(serveur):
    requete, journal, *_ = serveur
    assert requete("/v1/images/generations", {"prompt": "x"})[0] == 200
    assert requete("/v1/images/generations", {"model": "dall-e-3", "prompt": "x"})[0] == 200
    assert [c["modelId"] for c in journal["image"]] == ["z-image-turbo", "z-image-turbo"]


def test_generation_n_images_font_n_appels(serveur):
    requete, journal, *_ = serveur
    st, corps, _ = requete("/v1/images/generations", {"prompt": "x", "n": 2})
    assert st == 200 and len(_json(corps)["data"]) == 2 and len(journal["image"]) == 2
    assert journal["image"][0]["seed"] != journal["image"][1]["seed"]


def test_generation_refuse_un_modele_a_pieces_sans_appeler_venice(serveur):
    requete, journal, *_ = serveur
    st, corps, _ = requete("/v1/images/generations", {"model": "flux-2-pro", "prompt": "x"})
    assert st == 403 and _json(corps)["error"]["code"] == "modele_payant_refuse" and journal["image"] == []


def test_generation_exige_un_prompt(serveur):
    requete, *_ = serveur
    assert requete("/v1/images/generations", {"model": "z-image-turbo"})[0] == 400
    assert requete("/v1/images/generations", {"prompt": "x", "n": 9})[0] == 400


def test_generation_negative_prompt_seulement_si_le_modele_le_gere(serveur):
    requete, journal, *_ = serveur
    requete("/v1/images/generations", {"model": "lustify-sdxl", "prompt": "x", "negative_prompt": "flou"})
    requete("/v1/images/generations", {"model": "z-image-turbo", "prompt": "x", "negative_prompt": "flou"})
    assert journal["image"][0]["negativePrompt"] == "flou" and "negativePrompt" not in journal["image"][1]


def test_generation_limiteur_propre(serveur):
    requete, journal, *_ = serveur
    for _ in range(3):
        assert requete("/v1/images/generations", {"prompt": "x"})[0] == 200
    st, corps, entetes = requete("/v1/images/generations", {"prompt": "x"})
    assert st == 429 and int(entetes["Retry-After"]) >= 1 and len(journal["image"]) == 3


def test_generation_refuse_quand_le_quota_pro_est_epuise(serveur):
    requete, journal, quotas, _ = serveur
    quotas.noter("image", 2)
    st, corps, _ = requete("/v1/images/generations", {"prompt": "x"})
    assert st == 429 and _json(corps)["error"]["code"] == "quota_images_epuise" and journal["image"] == []


def test_generation_violation_de_contenu_est_un_400(serveur, monkeypatch):
    requete, *_ = serveur
    monkeypatch.setattr(vp, "generer_image_venice", lambda j, c: (b"", "image/png", {"x-venice-is-content-violation": "true"}))
    st, corps, _ = requete("/v1/images/generations", {"prompt": "x"})
    assert st == 400 and _json(corps)["error"]["code"] == "content_policy_violation"


def test_generation_exige_la_cle(serveur):
    requete, *_ = serveur
    assert requete("/v1/images/generations", {"prompt": "x"}, cle="mauvaise")[0] == 401


def test_liste_des_modeles_d_image(serveur):
    requete, *_ = serveur
    ids = {m["id"] for m in _json(requete("/v1/images/models")[1])["data"]}
    assert ids == set(vp.IMAGES_GRATUITES) and "z-image-turbo" in ids and "flux-2-pro" not in ids


# --- voix : synthèse --------------------------------------------------------------------------------------

def test_synthese_renvoie_l_audio(serveur):
    requete, journal, *_ = serveur
    st, corps, entetes = requete("/v1/audio/speech", {"model": "tts-1", "input": "Bonjour", "voice": "alloy"})
    assert st == 200 and corps == b"ID3-audio" and entetes["Content-Type"] == "audio/mpeg"
    c = journal["tts"][0]
    assert c["model"] == "tts-kokoro" and c["input"] == "Bonjour" and c["voice"] == "ff_siwis" and c["response_format"] == "mp3"


def test_synthese_sans_voix_prend_la_voix_francaise(serveur):
    requete, journal, *_ = serveur
    requete("/v1/audio/speech", {"input": "Salut"})
    requete("/v1/audio/speech", {"model": "tts-xai-v1", "input": "Salut", "voice": "alloy"})
    assert journal["tts"][0]["voice"] == "ff_siwis" and journal["tts"][1]["voice"] == "alloy"


def test_synthese_voix_inconnue_passe_telle_quelle(serveur):
    requete, journal, *_ = serveur
    requete("/v1/audio/speech", {"model": "tts-kokoro", "input": "Salut", "voice": "ff_siwis", "speed": 9})
    assert journal["tts"][0]["voice"] == "ff_siwis" and journal["tts"][0]["speed"] == 2


def test_synthese_formats_wav_et_refus_des_autres(serveur):
    requete, journal, *_ = serveur
    st, _, entetes = requete("/v1/audio/speech", {"input": "x", "response_format": "wav"})
    assert st == 200 and entetes["Content-Type"] == "audio/wav"
    assert requete("/v1/audio/speech", {"input": "x", "response_format": "opus"})[0] == 400


def test_synthese_modele_wav_seulement_prend_wav_par_defaut(serveur):
    requete, journal, *_ = serveur
    requete("/v1/audio/speech", {"model": "tts-inworld-1-5-max", "input": "x"})
    assert journal["tts"][0]["response_format"] == "wav"


def test_synthese_refuse_un_modele_inconnu_et_un_texte_trop_long(serveur):
    requete, journal, *_ = serveur
    assert requete("/v1/audio/speech", {"model": "tts-payant", "input": "x"})[0] == 403
    assert requete("/v1/audio/speech", {"input": "x" * 5000})[0] == 400
    assert requete("/v1/audio/speech", {"model": "tts-kokoro"})[0] == 400
    assert journal["tts"] == []


def test_synthese_et_transcription_partagent_le_limiteur_voix(serveur):
    requete, journal, *_ = serveur
    for _ in range(3):
        assert requete("/v1/audio/speech", {"input": "x"})[0] == 200
    assert requete("/v1/audio/speech", {"input": "x"})[0] == 429


# --- voix : transcription ---------------------------------------------------------------------------------

def _multipart(champs, nom_fichier="voix.mp3", contenu=b"\x00\xffbinaire\r\n--", mime="audio/mpeg"):
    limite = "----" + uuid.uuid4().hex
    corps = b""
    for k, v in champs.items():
        corps += f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    if nom_fichier:
        corps += (f'--{limite}\r\nContent-Disposition: form-data; name="file"; filename="{nom_fichier}"\r\n'
                  f"Content-Type: {mime}\r\n\r\n").encode() + contenu + b"\r\n"
    corps += f"--{limite}--\r\n".encode()
    return corps, f"multipart/form-data; boundary={limite}"


def test_multipart_conserve_les_octets_du_fichier():
    corps, ct = _multipart({"model": "whisper-1", "language": "fr"}, contenu=bytes(range(256)) * 4)
    champs, fichiers = vp.lire_multipart(ct, corps)
    assert champs == {"model": "whisper-1", "language": "fr"}
    assert fichiers["file"] == ("voix.mp3", "audio/mpeg", bytes(range(256)) * 4)


def test_multipart_refuse_un_type_incorrect():
    with pytest.raises(vp.EntreeInvalide):
        vp.lire_multipart("application/json", b"{}")


def test_transcription_json(serveur):
    requete, journal, *_ = serveur
    corps, ct = _multipart({"model": "whisper-1"})
    st, rep, _ = requete("/v1/audio/transcriptions", brut=corps, type_contenu=ct)
    assert st == 200 and _json(rep) == {"text": "bonjour le monde"}
    assert journal["asr"][0] == (b"\x00\xffbinaire\r\n--", "voix.mp3", "audio/mpeg", False)


def test_transcription_texte_brut(serveur):
    requete, *_ = serveur
    corps, ct = _multipart({"response_format": "text"})
    st, rep, entetes = requete("/v1/audio/transcriptions", brut=corps, type_contenu=ct)
    assert st == 200 and rep == b"bonjour le monde" and entetes["Content-Type"].startswith("text/plain")


def test_transcription_verbose_json_et_sous_titres(serveur):
    requete, journal, *_ = serveur
    corps, ct = _multipart({"response_format": "verbose_json"})
    st, rep, _ = requete("/v1/audio/transcriptions", brut=corps, type_contenu=ct)
    rep = _json(rep)
    assert rep["text"] == "bonjour le monde" and rep["duration"] == 2.5
    assert rep["segments"][1] == {"id": 1, "start": 1.2, "end": 2.5, "text": "le monde"} and journal["asr"][0][3] is True
    corps, ct = _multipart({"response_format": "srt"})
    srt = requete("/v1/audio/transcriptions", brut=corps, type_contenu=ct)[1].decode()
    assert "1\n00:00:00,000 --> 00:00:01,200\nbonjour" in srt
    corps, ct = _multipart({"response_format": "vtt"})
    vtt = requete("/v1/audio/transcriptions", brut=corps, type_contenu=ct)[1].decode()
    assert vtt.startswith("WEBVTT") and "00:00:01.200 --> 00:00:02.500" in vtt


def test_transcription_sans_horodatage_de_venice(serveur, monkeypatch):
    requete, *_ = serveur
    monkeypatch.setattr(vp, "transcrire_venice", lambda *a: {"text": "bonjour"})
    for fmt in ("srt", "vtt"):
        corps, ct = _multipart({"response_format": fmt})
        st, rep, _ = requete("/v1/audio/transcriptions", brut=corps, type_contenu=ct)
        assert st == 400 and "horodatage" in _json(rep)["error"]["message"]
    corps, ct = _multipart({"response_format": "verbose_json"})
    rep = _json(requete("/v1/audio/transcriptions", brut=corps, type_contenu=ct)[1])
    assert rep["text"] == "bonjour" and rep["segments"] == []


def test_transcription_exige_un_fichier_et_un_format_connu(serveur):
    requete, journal, *_ = serveur
    corps, ct = _multipart({}, nom_fichier=None)
    assert requete("/v1/audio/transcriptions", brut=corps, type_contenu=ct)[0] == 400
    corps, ct = _multipart({"response_format": "pdf"})
    assert requete("/v1/audio/transcriptions", brut=corps, type_contenu=ct)[0] == 400
    assert journal["asr"] == []


def test_transcription_refuse_un_fichier_trop_gros(serveur, monkeypatch):
    requete, *_ = serveur
    monkeypatch.setattr(vp, "AUDIO_MAX_OCTETS", 5)
    corps, ct = _multipart({})
    assert requete("/v1/audio/transcriptions", brut=corps, type_contenu=ct)[0] == 413


# --- quotas -----------------------------------------------------------------------------------------------

def test_quotas_notes_depuis_les_en_tetes_et_exposes(serveur):
    requete, _, quotas, _ = serveur
    quotas.rafraichir()
    requete("/v1/images/generations", {"prompt": "x"})
    assert quotas.restant("image") == 900
    rep = _json(requete("/quotas")[1])
    assert rep["image"]["remaining"] == 900 and rep["chat"]["remaining"] == 9000


def test_quotas_lecture_ratee_ne_leve_pas():
    def casse():
        raise RuntimeError("venice injoignable")
    q = vp.SuiviQuotas(casse)
    assert "injoignable" in q.rafraichir()["erreur"] and q.restant("image") is None


def test_modeles_gratuits_mesures_le_28_10_dans_les_listes():
    assert {"z-image-turbo", "chroma", "lustify-sdxl"} <= set(vp.IMAGES_GRATUITES)
    assert "flux-2-pro" not in vp.IMAGES_GRATUITES
    assert {"tts-kokoro", "tts-xai-v1"} <= set(vp.TTS_GRATUITS)
    assert {"qwen-3-8-27b", "gemma4-uncensored", "qwen3-vl-235b-a22b"} <= set(vp.VISION_GRATUITS)
    assert set(vp.VISION_GRATUITS) <= set(vp.GRATUITS)
