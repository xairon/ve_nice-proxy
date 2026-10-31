# Écriture du code : confiée à DeepSeek

Un outil MCP `deepseek_coder` (serveur `deepseek`, programme `venice-mcp`) confie l'écriture du code à DeepSeek
V4.1 Flash Uncensored : gratuit, ~500k jetons de contexte, non censuré.

- **Pour toute création ou modification de code, appelle `mcp__deepseek__deepseek_coder`** au lieu d'écrire le code
  toi-même avec Edit ou Write. Toi, tu explores le dépôt, tu choisis les fichiers, tu relis et tu vérifies.
- Donne-lui une consigne précise et complète, et **tous** les fichiers utiles (`fichiers`) : ceux à modifier et ceux
  à lire pour comprendre. Il ne voit rien d'autre. Sa fenêtre est grande, sois généreux.
- Passe une commande `test` quand il en existe une : il corrige tout seul tant qu'elle échoue (`tours`).
- Après l'appel, relis le résultat (`git diff`). Pour une retouche, rappelle-le avec une consigne corrective plutôt
  que de corriger toi-même, sauf pour une ligne triviale.
- Pour lire ou analyser beaucoup de code d'un coup sans modifier, utilise `mcp__deepseek__deepseek_demander`.
- Si l'outil échoue (pont injoignable), dis-le et écris le code toi-même.
