# Multimodal : matrice complète, routes, coûts mesurés

Cartographié le 28/10/2026 par lecture du code JavaScript de venice.ai (routes et schémas de requête), puis **un essai par capacité exposée**, solde Venice (`veniceCredits`, `/api/user/session`) lu avant et après : **285 avant et après chaque essai, aucun débit**. Le solde lu sans cache (`?bustBalanceCache=true`) est identique.

## Matrice entrée / sortie

Légende : **exposé** = le pont le sert, essayé en réel ; **trouvé, non exposé** = la route existe, rien d'utile à 0 crédit ou non essayé ; **payant** = débite des crédits, refusé par défaut ; **impossible** = pas de voie.

| Modalité | Entrée | Sortie |
|---|---|---|
| **Texte** | exposé : `/v1/chat/completions` (chat classique ~39k, route agents 262k à 524k) | exposé : texte, flux SSE rejoué, appels d'outils émulés |
| **Image** | exposé : vision (`image_url`, 8 modèles) ; **OCR** `/v1/ocr` et lecture automatique d'une image envoyée comme fichier | exposé : génération `/v1/images/generations` (6 modèles) ; édition `/v1/images/edits` (2 modèles) ; agrandissement ×2 et ×4 `/v1/images/upscale` ; détourage `/v1/images/remove-background` |
| **Fichiers** | exposé : texte, Markdown, CSV, JSON, code, PDF avec texte (essayés) ; DOCX, PPTX, XLSX, XLS, EPUB annoncés par le site (non essayés) | — |
| **PDF scanné** | exposé : **OCR automatique** page par page (`pdftoppm` si installé, sinon images JPEG ou RGB/gris intégrées au PDF) | — |
| **Audio** | exposé : transcription `/v1/audio/transcriptions` ; **`input_audio` dans un message** (transcrit par Parakeet puis injecté). Aucune voie directe sans pièce : les modèles qui lisent l'audio (Gemini, Qwen Omni…) sont **payants** | exposé : synthèse `/v1/audio/speech` (9 modèles, mp3 ou wav) |
| **Embeddings** | exposé : `/v1/embeddings` (bge-m3, 1 024 dimensions) | — |
| **Recherche web** | exposé : `web_search`, `web_scrape`, `x_search`, `web_search_options` | citations `^n^` dans le texte |
| **Vidéo** | **payant** : 141 modèles, aucun sans pièce ; devis de 55 crédits pour 5 s de Wan 2.7 en 720p. Abandonné : non exposé | **payant** (idem) |
| **Musique** | **payant** : 20 modèles, aucun sans pièce, file d'attente `/music/queue` | **payant** |
| Édition avec masque, édition multi-images (`multi-edit`) | trouvé, non exposé : modèles payants ; non essayé | — |
| Clonage de voix, changeur de voix | trouvé, non exposé (`/audio/voices`, `/audio/voice-changer/*`) ; non essayé | — |
| Personnages | trouvé, non exposé : `/api/characters/me` répond `[]` (aucun personnage sur ce compte) ; le chat accepte un `characterId` que le pont ne transmet pas | — |
| Mémoire, dossiers, historique | trouvé, non exposé : conversations chiffrées de bout en bout (`encrypted_conversation/retrieve`), sans liste utilisable ; le pont est sans état | — |
| Raisonnement | exposé : `reasoning_effort: "none"` coupe la réflexion (testé), toute autre valeur la laisse active | — |
| Prompt système Venice | exposé : désactivé par défaut, `include_venice_system_prompt: true` le réactive (testé) | — |

## Image en entrée (vision)

Format OpenAI standard, accepté tel quel :

```json
{"model":"qwen-3-8-27b","messages":[{"role":"user","content":[
  {"type":"text","text":"Que vois-tu ?"},
  {"type":"image_url","image_url":{"url":"data:image/png;base64,iVBOR..."}}]}]}
```

- Le site attend le **base64 brut** dans `imagePath` du message : le pont convertit, et **télécharge lui-même** une URL `https://` (pas de redirection, adresse publique seulement : loopback, réseaux privés et tailnet refusés ; 10 Mo par image, 8 images par message). Types : PNG, JPEG, WebP.
- Comme le site, seules les images du **dernier message qui en porte** sont renvoyées.
- Modèles : voir [MODELES.md](MODELES.md). Un autre modèle répond `400 modele_sans_vision` (la route agents, Kimi et DeepSeek, n'a pas de vision ici).
- Limite connue : entre la vérification de l'adresse et le téléchargement, un DNS qui change n'est pas couvert ; n'exposez pas le pont à des clients non fiables ([SECURITE.md](SECURITE.md)).

## Fichiers et OCR

- **Fichier joint** : partie `{"type":"file","file":{"filename":"facture.pdf","file_data":"data:application/pdf;base64,..."}}`. Le texte est extrait par `text_parser` (0 crédit) et glissé dans le message au format du site. `file_id` n'est pas pris en charge ; 20 Mo au plus.
- **PDF scanné** (sans couche texte, refusé par le site en 400) : le pont bascule **automatiquement** sur l'OCR. Les pages sont obtenues par `pdftoppm` (poppler, 150 dpi) s'il est installé ; sinon par extraction des images intégrées au PDF, sans bibliothèque (JPEG repris tel quel, Flate RGB ou gris reconstruit en PNG). **CCITT, JBIG2, JPEG 2000 et palettes** ne sont pas décodés sans poppler : l'erreur le dit (`apt install poppler-utils` ; l'image Docker l'embarque). Ordre des pages = ordre du fichier. 20 pages au plus (`VENICE_PONT_OCR_PAGES`), la réponse indique `tronque`.
- **OCR** : un modèle vision sans pièce (`qwen-3-8-27b` par défaut, `VENICE_PONT_OCR_MODELE`) lit chaque page avec un prompt de transcription fidèle, température 0. Mesuré : « FACTURE 2026-042 / Total: 128,50 EUR » lu à l'identique par `qwen-3-8-27b`, `google-gemma-4-31b-it`, `qwen3-vl-235b-a22b`, `gemma4-uncensored` (0,9 à 2,1 s).
- **`POST /v1/ocr`** : JSON `{"image": "data:... ou https://...", "model": "..."}` ou `{"file_data": "data:application/pdf;base64,...", "filename": "..."}`, ou formulaire multipart (`file`). Réponse `{"text", "pages", "tronque", "model"}`.
- Chaque page coûte une requête de chat (comptée dans le plafond et dans le quota de chat du jour, environ 10 000).

## Génération, édition, agrandissement, détourage

```bash
curl -s http://127.0.0.1:8700/v1/images/generations -H "Authorization: Bearer $VENICE_PONT_CLE" \
  -H 'Content-Type: application/json' -d '{"model":"z-image-turbo","prompt":"une pomme rouge","size":"1024x1024","n":1}'
curl -s http://127.0.0.1:8700/v1/images/edits -H "Authorization: Bearer $VENICE_PONT_CLE" \
  -F image=@pomme.png -F prompt="rends la pomme verte"
```

- **Génération** : réponse `{"created", "data":[{"b64_json"}]}` (toujours en base64, PNG), en-tête `X-Venice-Quota-Image-Restant`. `size` : multiple de 8 ou 16, borné 256..1280. `n` de 1 à 4. `negative_prompt` pour les modèles qui l'acceptent. `dall-e-3`, `gpt-image-1` → `z-image-turbo`. Limiteur : 10 images par minute (`VENICE_PONT_MAX_IMAGES_PAR_MIN`).
- **Édition** (`/v1/images/edits`, formulaire multipart comme OpenAI, ou JSON avec `image` en data URL) : `qwen-edit-uncensored` (défaut) ou `firered-image-edit`. L'image doit faire au moins ~512 px (sinon 400 `IMAGE_TOO_SMALL` du site) ; la sortie est plus grande (1 024 px mesurés). Quota « inpaint » 1 000/jour, en-tête `X-Venice-Quota-Inpaint-Restant`. `n` de 1 à 2. Pas de masque.
- **Agrandissement** (`/v1/images/upscale`, `scale` 2 ou 4, 512 → 1 024 et 2 048 px mesurés) et **détourage** (`/v1/images/remove-background`, PNG avec transparence) : 0 crédit, quota non communiqué par le site.
- **Coût** : 0 crédit avec les 6 modèles d'image sans pièce et les 2 modèles d'édition. Le site affiche un « devis » de 2 crédits pour `z-image-turbo` : c'est le prix de repli quand le quota Pro est épuisé ; le pont n'envoie **jamais** `acceptCreditFallback` et refuse (`429 quota_images_epuise`) quand il reste moins de 5 images au quota.
- Les 36 autres modèles d'image sont payants (devis de 3 crédits et plus) : refusés en 403 sauf `autoriser_debit: true` (non essayé). Contenu refusé ou flouté par Venice : `400 content_policy_violation`.

## Voix

- **Synthèse** `/v1/audio/speech` : `input` (4 096 caractères au plus), `voice`, `response_format` (`mp3` ou `wav`), `speed` (0,75 à 2). `tts-1` et `tts-1-hd` → `tts-kokoro`. Les noms de voix OpenAI (`alloy`…) prennent la **voix française** `ff_siwis` (`VENICE_PONT_VOIX`) ; un nom de voix Kokoro (`af_sky`…) passe tel quel. `tts-inworld-1-5-max` et `tts-gradium-v1` ne font que du wav. `tts-orpheus` et `tts-chatterbox-hd` n'ont pas répondu en 120 s : exclus.
- **Transcription** `/v1/audio/transcriptions` (multipart, comme OpenAI) : Parakeet TDT 0.6B v3, multilingue. `json` et `text` ; `verbose_json` sans segments ; **`srt` et `vtt` refusés** (la route ne renvoie aucun horodatage, essayé en multipart et en JSON). 25 Mo au plus. `language`, `prompt`, `temperature` ignorés.
- **Audio vers un modèle** : partie OpenAI `{"type":"input_audio","input_audio":{"data":"<base64>","format":"mp3"}}` (mp3, wav, m4a, ogg, flac, webm ; seul mp3 essayé). Le pont transcrit puis injecte `[Audio transcrit : ...]` dans le message ; une transcription déjà faite est réutilisée si le client renvoie l'historique. Le modèle ne « entend » pas le ton ou la musique : c'est du texte.
- Aller-retour mesuré : « Le pont Venice sait maintenant parler et écouter. » → « Le pont-venise sait maintenant parler et écouter. ».
- Limiteur : 30 appels par minute (`VENICE_PONT_MAX_VOIX_PAR_MIN`). Mesures sur de courts textes : un long texte n'a pas été chiffré ; le garde-fou « solde » alerte si le solde baisse.

## Embeddings

`POST /v1/embeddings` : `input` (texte ou liste de 64 textes, 8 000 caractères chacun), format `float`. Le site ne propose qu'un modèle sur cette route (`text-embedding-bge-m3`, 1 024 dimensions) : tout nom de modèle envoyé (`text-embedding-3-small`…) est remplacé par celui-ci. **Piège** : sans `skipImportance: true` le site répond 500 ; le pont l'ajoute. Le catalogue web liste 9 modèles d'embedding (`usesCredits: false`) mais la route ne permet pas d'en choisir un.

## Recherche web

`web_search` (testé : citations), `web_scrape` (lecture de pages citées dans le message ; testé sur `example.com`, quota **70/jour** côté site) et `x_search` (testé) sont des champs de la requête de chat classique, désactivés par défaut. `web_search_options: {}` (champ OpenAI) active aussi la recherche web.

## Vidéo et musique (non exposées)

Cartographiées sans rien générer : `POST /api/inference/video/quote` (devis), `/video/queue` puis `/video/retrieve`, `/music/queue`. **Les 141 modèles vidéo et les 20 modèles musique sont payants.** Devis mesuré : 55 crédits (≈ 0,55 $) pour 5 s de Wan 2.7 en 720p ; l'historique de facturation montre qu'une génération vidéo a coûté 260 crédits le 28/10/2026 (`wan-3-0-image-to-video`, 2,60 $). Décision : on ne les expose pas ; à ajouter seulement avec un plafond de crédits par requête.

## Quotas du jour (lecture seule)

`GET /quotas` renvoie `/api/inference/rate-limits` : `chat` (≈ 10 000/jour), `conversation`, `image` (1 000), `inpaint` (1 000), `scrape` (70). Le pont les rafraîchit toutes les 10 minutes et les affiche dans `/health`.

## Lire le solde sans se tromper

Le jeton de `/api/user/session` contient le solde (`veniceCredits`) ; le paramètre `?bustBalanceCache=true` force la relecture (vérifié : même valeur). L'historique de facturation du compte est lisible en lecture seule : `/api/app/user/billing/usage-history` (100 dernières lignes : date, montant, devise, modèle) et `/api/user/api/historical_usage?lookback=7d`.

## Derrière une passerelle OmniRoute (3.8.x)

Mesuré le 28/10/2026 : les routes image, voix et embeddings d'OmniRoute ne reconnaissent pas un modèle d'un nœud « chat » ; le pont passe, mais il faut le déclarer ainsi.

- **Vision** : déclarer les modèles qui lisent une image (`qwen-3-8-27b`, `gemma4-uncensored`) avec `supportsVision: true` (`POST /api/provider-models`), sinon `capability_mismatch` avant tout appel.
- **Images et édition** : modèles `z-image-turbo` et `qwen-edit-uncensored` du nœud du pont, déclarés avec `supportedEndpoints: ["images"]`.
- **Voix et embeddings** : un nœud par type d'API (`apiType` `audio-speech`, `embeddings`) pointant sur le même pont et la même clé, avec le modèle déclaré (`tts-kokoro`, `text-embedding-bge-m3`) ; appeler `<préfixe-du-nœud>/<modèle>`.
- **Voix hors localhost** : `/v1/audio/*` refuse un nœud distant (400 « Invalid speech model ») tant que `AUDIO_REMOTE_PROVIDER_NODES=true` n'est pas posé sur OmniRoute.
- Les cinq appels (vision, génération, édition, voix, embeddings) ont servi à 0 crédit : solde identique avant et après.
