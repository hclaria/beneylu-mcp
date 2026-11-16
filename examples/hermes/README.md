# Recette Hermes : envoi garanti et rappels automatiques

Un cron [Hermes](https://github.com/NousResearch/hermes-agent) en mode **surveillance** : un script tourne à chaque
passage, et l'agent ne démarre que si la sortie du script a changé.

1. `beneylu_whats_new.py` appelle `whats_new`, envoie lui-même les nouveautés aux parents par Telegram, puis appelle
   `ack` seulement si tous les envois ont réussi.
2. Il affiche l'historique des derniers mots transmis. Sans nouveauté, la sortie ne change pas : aucun agent ne
   démarre, 0 token.
3. Quand un mot arrive, l'agent se réveille avec la différence, repère les dates et pose les rappels avec
   `cron_prompt.md` : le matin même pour un événement, la veille et le dernier jour pour une date limite.

## Installation

Copier `beneylu_whats_new.py` dans `~/.hermes/scripts/`, remplacer les `<...>` de `cron_prompt.md`, puis créer le
cron dans Hermes :

```
cronjob create
  schedule: "0 6,9,12,15,18,21 * * *"      # UTC : de 7h à 22h, heure de Paris en hiver
  monitor:  beneylu_whats_new.py
  prompt:   (contenu de cron_prompt.md)
  deliver:  telegram:<CHAT_ID_ADMIN>        # compte-rendu des rappels posés et alertes
```

| Variable | Rôle |
|---|---|
| `BENEYLU_MCP_CMD` | Commande qui lance le serveur MCP, par exemple `uvx --from git+https://github.com/hclaria/beneylu-mcp beneylu-mcp`. |
| `HERMES_ENV` | Fichier `.env` de Hermes qui contient `TELEGRAM_BOT_TOKEN` (par défaut `~/.hermes/.env`). |
| `BENEYLU_CHATS` | Destinataires : `Nom:chat_id,Nom:chat_id`. Vide, le script signale une erreur et ne confirme rien. |
| `BENEYLU_KIDS` | Prénoms à garder dans les résumés : `Prénom1,Prénom2`. |
| `BENEYLU_SENT_LOG` | Historique des envois (par défaut `~/.hermes/cache/beneylu_sent_log.json`). |

## Garanties réelles

- **Transmission des mots : au moins une fois.** `ack` n'est appelé qu'après un envoi Telegram accepté pour chaque
  parent. Sinon les nouveautés reviennent au passage suivant, marquées comme rappel.
- **Rappels : posés par un modèle** à partir du texte du mot. Fiable en pratique, pas garanti.
- **0 token sans nouveauté.** L'agent se réveille aussi quand l'état d'erreur change, pour te prévenir.
- **Ce qui sort de la machine :** le texte des nouveaux mots part vers Telegram et vers le fournisseur du LLM de
  Hermes. L'état (`state.db`, historique) reste local.
- Le script n'appelle jamais `get_conversation` : rien n'est marqué comme lu côté école.
