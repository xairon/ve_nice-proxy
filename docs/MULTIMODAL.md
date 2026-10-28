# Multimodal : images, fichiers, voix

Cartographié le 28/10/2026 par lecture du code JavaScript de venice.ai (routes et schémas de requête), puis **un essai par capacité**, solde Venice (`veniceCredits`, `/api/user/session`) lu avant et après : **285 avant et après chaque essai, aucun débit**. Ce qui suit est ce que le pont expose ; les coûts sont ceux de l'abonnement Pro.

| Capacité | Route du pont | Route du site | Testé |
|---|---|---|---|
| Image en entrée | `POST /v1/chat/completions` (`content` en liste) | `/api/inference/chat`, champ `imagePath` | oui, 8 modèles |
| Fichier en entrée | idem, partie `file` | `/api/inference/text_parser` puis texte dans le prompt | oui (texte, PDF texte) |
| Image en sortie | `POST /v1/images/generations` | `/api/inference/image` | oui, `z-image-turbo` |
| Voix en sortie | `POST /v1/audio/speech` | `/api/inference/tts` | oui, 11 modèles (9 retenus) |
| Voix en entrée | `POST /v1/audio/transcriptions` | `/api/inference/asr` | oui |
| Quotas du jour | `GET /quotas` (clé du pont) | `/api/inference/rate-limits` | oui |
| Vidéo, musique | **non exposé** | `/api/inference/video/*`, `/music/*` | devis seulement |

## Image en entrée (vision)

Format OpenAI standard, accepté tel quel :

```json
{"model":"qwen-3-8-27b","messages":[{"role":"user","content":[
  {"type":"text","text":"Que vois-tu ?"},
  {"type":"image_url","image_url":{"url":"data:image/png;base64,iVBOR..."}}]}]}
```

- Le site ne reçoit pas d'URL : il attend le **base64 brut** (sans `data:...;base64,`) dans `imagePath` du message. Le pont fait la conversion, et **télécharge lui-même** une URL `https://` (pas de redirection, adresse publique seulement : loopback, réseaux privés et tailnet refusés ; maximum 10 Mo par image, 8 images par message). Types : PNG, JPEG, WebP.
- Comme le site, seules les images du **dernier message qui en porte** sont renvoyées ; les anciennes sont ignorées sans téléchargement.
- Modèles : voir [MODELES.md](MODELES.md). Un autre modèle répond `400 modele_sans_vision` (la route « agents » : Kimi, DeepSeek, n'a pas de vision ici).
- Limite connue : entre la vérification de l'adresse et le téléchargement, un DNS qui change n'est pas couvert ; n'exposez pas le pont à des clients non fiables ([SECURITE.md](SECURITE.md)).

## Fichiers

Partie OpenAI `{"type":"file","file":{"filename":"facture.pdf","file_data":"data:application/pdf;base64,..."}}`. Le pont envoie le fichier à `text_parser` (0 crédit) et glisse le texte dans le message au format du site (`The following content is from a file named ...`). Texte brut et PDF avec couche texte : essayés. **PDF scanné : HTTP 400** côté site, relayé en 400 (pas d'OCR). `file_id` n'est pas pris en charge. Maximum 20 Mo.

## Génération d'images

```bash
curl -s http://127.0.0.1:8700/v1/images/generations -H "Authorization: Bearer $VENICE_PONT_CLE" \
  -H 'Content-Type: application/json' -d '{"model":"z-image-turbo","prompt":"une pomme rouge","size":"1024x1024","n":1}'
```

- Réponse `{"created":..., "data":[{"b64_json":"..."}]}` ; **toujours en base64** (`response_format: url` est ignoré). PNG. En-tête `X-Venice-Quota-Image-Restant`.
- `size` : multiple de 8 ou 16 selon le modèle, borné à 256..1280 (arrondi vers le bas). `n` de 1 à 4 (un appel par image, une seed différente). `negative_prompt` pour les modèles qui l'acceptent. Noms OpenAI (`dall-e-3`, `gpt-image-1`) → `z-image-turbo`.
- **Coût** : 0 crédit avec les 6 modèles sans pièce (`z-image-turbo` mesuré : 985 puis 984 images restantes sur le quota Pro de 1 000/jour). Le site affiche un « devis » de 2 crédits pour ce modèle : c'est le prix de repli quand le quota est épuisé ; le pont n'envoie **jamais** le champ `acceptCreditFallback`, et refuse (`429 quota_images_epuise`) quand il reste moins de 5 images au quota.
- Les 36 autres modèles d'image sont payants (devis 3 crédits et plus) : refusés en 403 sauf `autoriser_debit: true` (non essayé : réglages de taille et de pas supposés).
- Limiteur : 10 images par minute (`VENICE_PONT_MAX_IMAGES_PAR_MIN`). Contenu refusé ou flouté par Venice : `400 content_policy_violation`.

## Voix

- **Synthèse** `/v1/audio/speech` : `input` (4 096 caractères au plus), `voice`, `response_format` (`mp3` ou `wav`), `speed` (0,75 à 2, borné). `tts-1` et `tts-1-hd` → `tts-kokoro`. Les noms de voix OpenAI (`alloy`…) n'existent pas chez Venice : ils prennent la **voix française** `ff_siwis` (changeable avec `VENICE_PONT_VOIX`) ; un nom de voix Kokoro (`af_sky`, `am_adam`…) passe tel quel. `tts-inworld-1-5-max` et `tts-gradium-v1` ne font que du wav (mp3 → 400 de Venice).
- **Transcription** `/v1/audio/transcriptions` (multipart, comme OpenAI) : un seul modèle, Parakeet TDT 0.6B v3, multilingue. Formats `json` et `text`, `verbose_json` **sans segments**. **`srt` et `vtt` refusés** : la route ne renvoie aucun horodatage (essayé en multipart et en JSON). Maximum 25 Mo. `language`, `prompt`, `temperature` ignorés.
- Aller-retour mesuré : « Le pont Venice sait maintenant parler et écouter. » → « Le pont-venise sait maintenant parler et écouter. ».
- Limiteur : 30 appels par minute (`VENICE_PONT_MAX_VOIX_PAR_MIN`). Mesures faites avec de courts textes : un long texte n'a pas été chiffré, le garde-fou « solde » ([SECURITE.md](SECURITE.md)) alerte si le solde baisse.

## Vidéo et musique (non exposées)

Cartographiées sans rien générer : `POST /api/inference/video/quote` (devis), `/video/queue` puis `/video/retrieve` (file d'attente), `/music/queue`. **Les 141 modèles vidéo et les 20 modèles musique sont payants.** Devis mesuré : 55 crédits (≈ 0,55 $) pour 5 s de Wan 2.7 en 720p. Le pont ne les expose pas : une génération serait un débit imprévisible. À ajouter seulement avec un plafond de crédits par requête.

## Quotas du jour (lecture seule)

`GET /quotas` renvoie `/api/inference/rate-limits` : `chat` (≈ 10 000/jour, 9 497 restantes lors du test), `conversation`, `image` (1 000), `inpaint` (1 000), `scrape` (70). Le pont les rafraîchit toutes les 10 minutes et les affiche dans `/health`.
