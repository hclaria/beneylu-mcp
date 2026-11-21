# beneylu-mcp

Serveur MCP en lecture seule pour [Beneylu School](https://school.beneylu.com), la plateforme de liaison
parents-école. Il donne à un agent (Hermes, Claude, ...) accès au cahier de liaison, aux pancartes de classe (photos et
vidéos), aux notifications et à la messagerie d'un compte parent, avec un outil `whats_new` qui renvoie chaque nouveauté jusqu'à ce que sa
transmission aux parents soit confirmée par `ack`.

Beneylu n'a pas d'API publique : le serveur utilise l'API interne du site, qui peut changer sans prévenir.

**[Présentation](https://hclaria.github.io/beneylu-mcp/)**. Le plus simple : donner ce dépôt à ton agent Hermes et
lui demander de mettre en place la surveillance et les rappels. [`examples/hermes/`](examples/hermes/) contient la
configuration qu'un agent a trouvée seul : des pistes à adapter, pas une installation clé en main.

## Outils

| Outil | Rôle |
|---|---|
| `whats_new` | Mots nouveaux ou modifiés, nouvelles cartes des pancartes de classe, nouvelles notifications (calendrier, médiathèque), nombre de messages non lus, et un `cursor`. Pour la vérification automatique. |
| `ack(cursor)` | Confirme que les nouveautés de ce `cursor` ont été transmises : elles ne reviennent plus. Rejouable sans effet. |
| `pending` | Nouveautés renvoyées mais pas encore confirmées. Lit l'état local seulement. |
| `list_posts(page)` | Mots du cahier de liaison, avec enfant, auteur, classe et état de signature. |
| `get_post(post_id)` | Un mot complet. |
| `list_cards(board_id, limit)` | Pancartes de classe et leurs cartes (photos, vidéos, textes publiés par l'enseignant), de la plus récente à la plus ancienne. |
| `get_card_media(card_id)` | Photos et vidéos d'une carte, avec un lien de téléchargement direct valable environ une heure. |
| `get_notifications(limit)` | Fil de notifications Beneylu. |
| `list_conversations` | Conversations de la messagerie. |
| `get_conversation(conversation_id)` | Messages d'une conversation. Peut les marquer comme lus : seulement à la demande d'un parent. |
| `get_account` | Compte connecté, enfants, classes. |

Une carte de pancarte arrive dans `whats_new["cards"]` avec `media_count` ; la notification « … a publié une carte
sur la pancarte » qui l'accompagne n'est plus renvoyée par `whats_new`, puisqu'elle ne dit rien de plus
(`get_notifications` la garde). Après une mise à jour depuis une version sans pancartes, seules les cartes publiées
ensuite sont signalées : les précédentes l'ont déjà été par leur notification.

Le serveur n'écrit jamais sur Beneylu (`ack` n'écrit que dans l'état local) : le client HTTP refuse tout `POST` en dehors de la connexion et de la
recherche de noms. Il n'appelle jamais `/visit`, l'appel par lequel le site signale qu'un parent a ouvert le cahier.

## Configuration

| Variable | Rôle |
|---|---|
| `BENEYLU_USERNAME`, `BENEYLU_PASSWORD` | Identifiants du compte parent. Le serveur se connecte et renouvelle sa session seul. |
| `BENEYLU_REFRESH_TOKEN` | Secours si Beneylu demande un captcha : le `refresh_token` du `localStorage` du navigateur. |
| `BENEYLU_FIRST_RUN_DAYS` | Nombre de jours renvoyés par le tout premier `whats_new` (7 par défaut, 30 au plus, 0 pour ne rien renvoyer). |
| `BENEYLU_STATE_DIR` | Dossier de l'état local (par défaut `~/.local/state/beneylu-mcp`). |

En développement, ces variables peuvent aussi venir d'un fichier `.env` dans le dossier courant (ignoré par git).

L'état local (`state.db`, droits `0600`) garde le jeton de session, la liste des éléments déjà transmis et les
nouveautés en attente de confirmation. Le supprimer fait repartir `whats_new` de zéro : au premier appel, il ne
renvoie que les `BENEYLU_FIRST_RUN_DAYS` derniers jours
(7 par défaut).

## Transmission garantie

`whats_new` ne marque rien comme vu. Il renvoie un `cursor` ; tant que `ack(cursor)` n'a pas été appelé, chaque
nouveauté revient aux appels suivants avec `already_reported_at` (premier signalement) et `report_count`. Une
réponse perdue (délai dépassé, agent interrompu, message non envoyé) n'efface donc rien : au pire, un parent reçoit
un doublon signalé comme tel. `ack` couvre tout ce que le lot a renvoyé, y compris les nouveautés plus anciennes
encore en attente ; un `ack` tardif sur un ancien lot ne masque jamais une modification arrivée depuis. Appeler `ack`
aussi quand il n'y a rien à transmettre : c'est ce qui enregistre le premier passage et le nombre de messages non
lus.

## Hermes

Dans `~/.hermes/config.yaml` :

```yaml
mcp_servers:
  beneylu:
    command: "/Users/<moi>/.local/bin/uvx"
    args: ["--from", "git+https://github.com/hclaria/beneylu-mcp", "beneylu-mcp"]   # ou un chemin local
    env:
      BENEYLU_USERNAME: "..."
      BENEYLU_PASSWORD: "..."
      PATH: "/usr/bin:/bin"
    timeout: 60
```

Puis `/reload-mcp` dans une session Hermes. Hermes ne transmet au serveur que `env` et un environnement minimal :
le chemin complet de `uvx` et un `PATH` de base suffisent au lanceur généré par uv.

Exemple de consigne de vérification régulière :

```
/cron every 3h Appelle whats_new sur Beneylu. S'il y a un mot nouveau ou modifié, une carte de pancarte (envoie
ses photos et vidéos, via get_card_media), une notification de calendrier ou des messages non lus, préviens les deux parents avec un résumé court : ce qui change, pour quel enfant, ce qu'il
faut prévoir, et si un mot attend une signature ; signale les éléments qui ont un already_reported_at comme un
rappel. Appelle ensuite ack avec le cursor. Sinon, appelle ack et ne dis rien.
```

Avec un agent, la confirmation ne prouve que la fin du tour, pas la remise du message. Pour une garantie de bout en
bout, envoyer soi-même le résumé (par exemple par l'API d'un bot Telegram) et n'appeler `ack` qu'une fois l'envoi
accepté. C'est ce que fait la piste [`examples/hermes/`](examples/hermes/) : un script envoie et confirme, et
l'agent ne se réveille que quand un mot arrive, pour poser les rappels.

`get_conversation` peut marquer des messages comme lus pour l'école : ne pas l'utiliser dans une tâche planifiée.

## Développement

```bash
uv sync
uv run pytest
uv run python scripts/smoke.py /chemin/vers/.env   # contrôle en direct, lecture seule, état temporaire
```
