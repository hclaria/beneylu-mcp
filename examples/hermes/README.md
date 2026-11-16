# Piste Hermes : envoi garanti et rappels automatiques

> **Ce dossier n'est pas une installation clé en main.** C'est la configuration qu'un agent
> [Hermes](https://github.com/NousResearch/hermes-agent) a conçue seul pour une famille, publiée comme piste. Ton
> agent la lit, l'adapte à sa version de Hermes, à ta messagerie et à ta famille, puis la teste.

## L'idée

Un cron en mode **surveillance** : un script tourne à chaque passage, et l'agent ne démarre que si la sortie du
script a changé.

1. `beneylu_whats_new.py` appelle `whats_new`, envoie lui-même les nouveautés aux parents par Telegram, puis appelle
   `ack` seulement si tous les envois ont réussi.
2. Il affiche l'historique des derniers mots transmis. Sans nouveauté, la sortie ne change pas : aucun agent ne
   démarre, 0 token.
3. Quand un mot arrive, l'agent se réveille avec la différence, repère les dates et pose les rappels selon
   `cron_prompt.md` : le matin même pour un événement, la veille et le dernier jour pour une date limite.

## Pour l'agent qui lit ceci

1. Installe le serveur MCP (voir le README à la racine du dépôt) et vérifie `get_account` : enfants et classes.
2. Demande au parent qui doit recevoir les mots et les rappels, les prénoms des enfants, l'heure des rappels et la
   fréquence de vérification.
3. Vérifie ce que ta version de Hermes sait faire : un cron qui exécute un script sans agent, et un mode qui ne
   réveille l'agent que si la sortie du script change. S'il en manque un, adapte. Par exemple, un cron avec agent qui
   appelle `whats_new` puis `ack` fonctionne aussi, mais consomme des tokens à chaque passage.
4. Adapte `beneylu_whats_new.py` (envoi, destinataires, chemins) et `cron_prompt.md` (famille, fuseau, outils de
   planification). Les `<...>` sont à remplacer.
5. Teste avant d'annoncer que c'est prêt :
   - un passage de référence, qui ne doit créer aucun doublon ;
   - un faux mot **réaliste** ajouté à l'historique. S'il porte une mention « test », l'agent du cron l'ignore et le
     test ne prouve rien. Vérifie les rappels créés, puis supprime-les avec le faux mot avant qu'ils ne partent.
6. N'appelle jamais `get_conversation` dans une tâche planifiée : il peut marquer des messages comme lus pour
   l'école. N'appelle `ack` qu'après un envoi réussi.

## Fichiers

| Fichier | Rôle |
|---|---|
| `beneylu_whats_new.py` | Script de surveillance : `whats_new`, envoi Telegram, `ack`, historique stable. |
| `cron_prompt.md` | Consigne de l'agent réveillé : repérer les dates, éviter les doublons, poser les rappels. |

Création du cron telle qu'elle a été faite (Hermes, novembre 2026) :

```
cronjob create
  schedule: "0 6,9,12,15,18,21 * * *"      # UTC : de 7h à 22h, heure de Paris en hiver
  monitor:  beneylu_whats_new.py            # dans ~/.hermes/scripts/
  prompt:   (contenu de cron_prompt.md)
  deliver:  telegram:<CHAT_ID_ADMIN>        # compte-rendu des rappels posés et alertes
```

| Variable du script | Rôle |
|---|---|
| `BENEYLU_USERNAME`, `BENEYLU_PASSWORD` | Identifiants Beneylu du serveur que lance le script. Il ne lit pas ceux de `config.yaml`. |
| `BENEYLU_MCP_CMD` | Commande qui lance le serveur MCP, par exemple `uvx --from git+https://github.com/hclaria/beneylu-mcp beneylu-mcp`. |
| `HERMES_ENV` | Fichier `.env` de Hermes qui contient `TELEGRAM_BOT_TOKEN` (par défaut `~/.hermes/.env`). |
| `BENEYLU_CHATS` | Destinataires : `Nom:chat_id,Nom:chat_id`. Vide, le script signale une erreur et ne confirme rien. |
| `BENEYLU_KIDS` | Prénoms à garder dans les résumés : `Prénom1,Prénom2`. |
| `BENEYLU_SENT_LOG` | Historique des envois (par défaut `~/.hermes/cache/beneylu_sent_log.json`). |

## Garanties de cette configuration

- **Transmission des mots : au moins une fois.** `ack` n'est appelé qu'après un envoi Telegram accepté pour chaque
  parent. Sinon les nouveautés reviennent au passage suivant, marquées comme rappel.
- **Rappels : posés par un modèle** à partir du texte du mot. Fiable en pratique, pas garanti.
- **0 token sans nouveauté.** L'agent se réveille aussi quand l'état d'erreur change, pour prévenir.
- **Ce qui sort de la machine :** le texte des nouveaux mots part vers Telegram et vers le fournisseur du LLM de
  Hermes. L'état (`state.db`, historique) reste local.
