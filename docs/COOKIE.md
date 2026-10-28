# Récupérer le cookie `__client`

Le pont a besoin d'**une seule valeur** : le cookie `__client` du domaine `venice.ai`, posé par le service d'authentification (Clerk) quand vous vous connectez. Il vaut environ **un an** (le statut affiche les jours restants). Il donne accès à votre compte : traitez-le comme un mot de passe.

## Chrome / Edge / Brave

1. Ouvrez <https://venice.ai> et **connectez-vous** avec le compte à brancher.
2. Ouvrez les outils de développement : touche **F12** (ou clic droit > Inspecter).
3. Onglet **Application** (si invisible : le chevron `»` en haut à droite de la fenêtre des outils).
4. Dans le panneau de gauche : **Stockage > Cookies**, puis `https://venice.ai` **et** `https://clerk.venice.ai`. Le pont envoie le cookie à `clerk.venice.ai` : c'est probablement là qu'il se trouve (le site `venice.ai` en garde parfois une copie).
5. Dans la liste, repérez la ligne dont le **Nom** est `__client` (deux tirets bas au début). Si plusieurs lignes ressemblent à `__client_uat…`, ce ne sont pas elles.
6. Cliquez sur la ligne : la valeur apparaît dans le bandeau du bas. Elle commence par **`eyJ`** et fait plus de 400 caractères. **Double-cliquez** dans la colonne « Valeur » pour la sélectionner en entier, puis copiez (Ctrl+C).

## Firefox

1. Connectez-vous sur <https://venice.ai>, touche **F12**.
2. Onglet **Stockage** > **Cookies** > `https://venice.ai` puis `https://clerk.venice.ai`.
3. Ligne `__client` : copiez la colonne **Valeur** (clic droit > Copier la valeur).

## Safari

Réglages > Avancé > cocher « Afficher le menu Développement » ; Développement > Afficher l'inspecteur web > Stockage > Cookies.

## Si le cookie est introuvable

- Regardez les deux domaines (`venice.ai` et `clerk.venice.ai`) dans la même liste.
- Il est marqué `HttpOnly` : l'inspecteur le montre quand même (c'est `document.cookie` qui ne le montre pas, ne l'utilisez pas).
- Connectez-vous en navigation normale (une fenêtre privée fonctionne aussi, mais le cookie disparaît à la fermeture de la fenêtre côté navigateur : ce n'est pas un problème, Clerk l'a déjà émis).

## Le donner au pont

```bash
./venice-setup login
# collez la valeur (rien ne s'affiche), Entrée
```

Ou, pour ne pas coller dans un terminal : mettre la valeur **seule** dans un fichier lisible par vous seul (`chmod 600`), puis `./venice-setup login --cookie-fichier ce-fichier`, puis **supprimer ce fichier**.

La commande vérifie le cookie auprès de Clerk et affiche votre solde. Messages possibles :

| Message | Sens |
|---|---|
| `Cookie valide. Solde de crédits : N` | tout va bien |
| `Cookie refusé par Clerk : aucune session active` | cookie périmé, incomplet, ou non connecté : reconnectez-vous et recopiez |
| `Ce cookie semble trop court` | copie partielle |

## Renouvellement et expiration

- Le pont « touche » la session toutes les heures et prend note si Clerk renvoie un cookie renouvelé (il le réécrit alors dans le fichier de secrets, de façon atomique).
- Quand le cookie meurt (déconnexion volontaire sur le site, changement de mot de passe, expiration) : `/health` répond **503 `cookie_expire`**. Reconnectez-vous sur venice.ai et relancez `venice-setup login` (la clé du pont est conservée, vos clients n'ont rien à changer), puis `systemctl --user restart venice-pont`.
- Se déconnecter sur le site invalide très probablement la session du cookie (comportement habituel de Clerk, non vérifié ici) : après avoir récupéré le cookie, évitez de cliquer sur « Se déconnecter » dans ce navigateur.

## Ne jamais

- le coller dans un dépôt Git, un ticket, une conversation ;
- l'enregistrer ailleurs que dans un fichier en mode 600 ;
- le partager : il donne accès à l'abonnement, aux conversations et aux crédits.
