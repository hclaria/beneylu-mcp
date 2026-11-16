# beneylu-mcp

Serveur MCP en lecture seule pour [Beneylu School](https://school.beneylu.com), la plateforme de liaison
parents-école. Il donne à un agent (Hermes, Claude, ...) accès au cahier de liaison, aux notifications et à la
messagerie d'un compte parent, avec un outil `whats_new` qui ne renvoie chaque nouveauté qu'une fois.

Beneylu n'a pas d'API publique : le serveur utilise l'API interne du site, qui peut changer sans prévenir.

## Outils

| Outil | Rôle |
|---|---|
| `whats_new` | Mots nouveaux ou modifiés, nouvelles notifications (pancarte, calendrier), nombre de messages non lus, depuis le dernier appel. Pour la vérification automatique. |
| `list_posts(page)` | Mots du cahier de liaison, avec enfant, auteur, classe et état de signature. |
| `get_post(post_id)` | Un mot complet. |
| `get_notifications(limit)` | Fil de notifications Beneylu. |
| `list_conversations` | Conversations de la messagerie. |
| `get_conversation(conversation_id)` | Messages d'une conversation. Peut les marquer comme lus : seulement à la demande d'un parent. |
| `get_account` | Compte connecté, enfants, classes. |

Le serveur ne fait jamais d'écriture : le client HTTP refuse tout `POST` en dehors de la connexion et de la
recherche de noms. Il n'appelle jamais `/visit`, l'appel par lequel le site signale qu'un parent a ouvert le cahier.

## Configuration

| Variable | Rôle |
|---|---|
| `BENEYLU_USERNAME`, `BENEYLU_PASSWORD` | Identifiants du compte parent. Le serveur se connecte et renouvelle sa session seul. |
| `BENEYLU_REFRESH_TOKEN` | Secours si Beneylu demande un captcha : le `refresh_token` du `localStorage` du navigateur. |
| `BENEYLU_STATE_DIR` | Dossier de l'état local (par défaut `~/.local/state/beneylu-mcp`). |

En développement, ces variables peuvent aussi venir d'un fichier `.env` dans le dossier courant (ignoré par git).

L'état local (`state.db`, droits `0600`) garde le jeton de session et la liste des éléments déjà vus. Le supprimer
fait repartir `whats_new` de zéro : au premier appel, il ne renvoie que les 7 derniers jours.

## Hermes

Dans `~/.hermes/config.yaml` :

```yaml
mcp_servers:
  beneylu:
    command: "/Users/<moi>/.local/bin/uvx"
    args: ["--from", "/chemin/vers/beneylu-mcp", "beneylu-mcp"]
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
/cron every 3h Appelle whats_new sur Beneylu. S'il y a un mot nouveau ou modifié, une notification de calendrier
ou des messages non lus, préviens les deux parents avec un résumé court : ce qui change, pour quel enfant, ce qu'il
faut prévoir, et si un mot attend une signature. Sinon, ne dis rien.
```

`get_conversation` peut marquer des messages comme lus pour l'école : ne pas l'utiliser dans une tâche planifiée.

## Développement

```bash
uv sync
uv run pytest
uv run python scripts/smoke.py /chemin/vers/.env   # contrôle en direct, lecture seule, état temporaire
```
