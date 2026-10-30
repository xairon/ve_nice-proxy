# Outils (tool calling)

Comment le pont fait utiliser des outils (lire un fichier, lancer une commande, écrire du code) à un modèle Venice, et ce qu'il faut savoir avant de brancher un agent.

## Résumé

| Question | Réponse |
|---|---|
| Tool calling natif ? | **Non** sur le chemin web (cookie `__client`). Les définitions sont **émulées dans le prompt** ; la réponse JSON est retransformée en `tool_calls` OpenAI. |
| Pourquoi ? | La route agents de Venice accepte `clientTools`, mais ne les présente pas au modèle (mesuré le 30/10/2026, six formes essayées). Le modèle ne voit que les outils internes de Venice, pas les vôtres. |
| Y a-t-il un espoir ? | L'API officielle de Venice (payante à l'usage) est le chemin prévu pour un vrai tool calling. Non testée ici. |
| Fiabilité | Bonne sur DeepSeek V4.1 Flash et Kimi K2.5 depuis la relance corrective du 30/10/2026. Variable selon le modèle. |

## Ce qui se passe concrètement

1. Votre client envoie `tools` au format OpenAI dans `/v1/chat/completions`.
2. Le pont met ces définitions (JSON Schema) dans le prompt système et demande au modèle de répondre **uniquement** par :

   ```json
   {"tool_calls":[{"name":"bash","arguments":{"command":"ls"}}]}
   ```

3. Il parse ce JSON et renvoie un `tool_calls` OpenAI normal. Votre client exécute l'outil et renvoie le résultat ; le pont le transforme en message texte pour Venice.

Le pont est **sans état** : c'est votre client qui renvoie tout l'historique à chaque tour.

## Les deux garde-fous (30/10/2026)

- **Prose avant l'appel tolérée.** « Je vais lire le fichier :\n{...} » est accepté : la phrase devient le contenu du message, l'appel est exécuté. Les noms d'outils sont vérifiés contre la liste fournie, donc un exemple cité avec un outil inconnu reste du texte.
- **Relance corrective.** Si le modèle appelle un outil **natif** de Venice, celui-ci répond « Tool not found » et le modèle rédige un refus. Le pont reconnaît ce refus et relance **une fois** avec une consigne renforcée qui force le format JSON. Une requête OpenCode capturée qui échouait donne désormais un `tool_calls` correct.

## Ce que votre client doit tolérer

- **Absence d'appel** : le modèle peut répondre en texte même quand des outils sont fournis. Traitez le texte comme une réponse finale, pas comme une erreur.
- **Arguments en chaîne JSON** : c'est le format OpenAI standard (`"arguments": "{\"command\":\"ls\"}"`).
- **Pas de streaming pendant un appel d'outil** : la réponse est mise en tampon pour analyser le JSON, puis rejouée en SSE. Sans outil, le flux est relayé au fil de l'eau.

## Contexte : quel modèle pour les agents

- **Route agents** (DeepSeek V4.1 Flash NC, Kimi K2.5) : grand contexte (annoncé 524 k / 262 k), prompt Venice imposé ≈ 15 k jetons, température ignorée. À préférer pour coder.
- **Chat classique** (Qwen 3.8 et autres) : plafond ~39 k jetons, au-delà Venice tronque **en silence**. Réglez le client à ~38 k.

Détails des modèles : [MODELES.md](MODELES.md). Ce qui n'est pas pris en charge : [LIMITES.md](LIMITES.md).

## Tester

Avec `curl` (le pont doit tourner) :

```bash
export VENICE_PONT_CLE="$(grep ^VENICE_PONT_CLE= ~/.config/venice-setup/defaut/venice.env | cut -d= -f2-)"
curl -s http://127.0.0.1:8700/v1/chat/completions \
  -H "Authorization: Bearer $VENICE_PONT_CLE" -H 'Content-Type: application/json' \
  -d '{
    "model": "deepseek-v4-1-flash-uncensored",
    "messages": [{"role": "user", "content": "Lis /etc/hostname avec l'"'"'outil read."}],
    "tools": [{"type": "function", "function": {
      "name": "read", "description": "Lit un fichier local.",
      "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}}, "required": ["filePath"]}}}]
  }'
```

Réponse attendue : `"finish_reason": "tool_calls"` et un `tool_calls` nommé `read`. Si vous recevez du texte du type « je n'ai pas d'outil », la relance a échoué : renvoyez la requête ou changez de modèle.

Avec OpenCode : `./venice-setup harness opencode --appliquer`, puis demandez « crée `notes.txt` avec trois lignes ». Le journal doit montrer un appel `write`, et le fichier doit exister.
