import logging
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .client import BeneyluClient, BeneyluError
from .config import ConfigError, load_settings
from .service import BeneyluService
from .state import StateStore

INSTRUCTIONS = (
    "Accès en lecture seule à Beneylu School, la plateforme de liaison parents-école. Le cahier de liaison "
    "(les mots de l'école) est la source principale. Pour une vérification automatique, appeler whats_new."
)
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)


def _run(fn: Callable[..., Any], *args: Any) -> Any:
    # MCPServer masks the message of any exception other than ToolError.
    try:
        return fn(*args)
    except BeneyluError as exc:
        raise ToolError(str(exc)) from None


def build_server(service: BeneyluService) -> MCPServer:
    server = MCPServer("beneylu", instructions=INSTRUCTIONS)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "Vérification automatique du cahier de liaison Beneylu : renvoie les mots nouveaux ou modifiés, les "
            "nouvelles notifications (pancarte de classe, calendrier de l'école) et le nombre de messages non lus "
            "depuis le dernier appel. Chaque nouveauté n'est renvoyée qu'une fois. Ne marque rien comme lu côté "
            "école. Au tout premier appel, seuls les 7 derniers jours sont renvoyés. Un mot dont "
            "pending_signature_for n'est pas vide attend une signature des parents."
        ),
    )
    def whats_new() -> dict:
        return _run(service.whats_new)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "Liste les mots du cahier de liaison Beneylu, 10 par page, du plus récent au plus ancien, avec "
            "l'enfant concerné, l'auteur, la classe et l'état de signature (pending_signature_for : enfants dont "
            "le mot attend encore une signature)."
        ),
    )
    def list_posts(page: int = 1) -> dict:
        return _run(service.list_posts, page)

    @server.tool(annotations=READ_ONLY, description="Renvoie un mot complet du cahier de liaison à partir de son id.")
    def get_post(post_id: str) -> dict:
        return _run(service.get_post, post_id)

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "Fil des notifications Beneylu (mots, pancarte de classe, calendrier de l'école), du plus récent au "
            "plus ancien."
        ),
    )
    def get_notifications(limit: int = 20) -> dict:
        return {"notifications": _run(service.notifications, limit)}

    @server.tool(
        annotations=READ_ONLY,
        description="Liste les conversations de la messagerie Beneylu (format brut renvoyé par Beneylu).",
    )
    def list_conversations() -> dict:
        return {"conversations": _run(service.conversations)}

    @server.tool(
        annotations=READ_ONLY,
        description=(
            "Renvoie les messages d'une conversation de la messagerie Beneylu. Peut marquer les messages comme "
            "lus pour l'école : à n'appeler qu'à la demande d'un parent, jamais en tâche de fond ni pendant une "
            "vérification automatique."
        ),
    )
    def get_conversation(conversation_id: str) -> dict:
        return {"messages": _run(service.conversation, conversation_id)}

    @server.tool(
        annotations=READ_ONLY,
        description="Compte Beneylu connecté : nom du parent, enfants et classes. Sert aussi à tester la connexion.",
    )
    def get_account() -> dict:
        return _run(service.account)

    return server


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None
    state = StateStore(settings.state_dir / "state.db")
    client = BeneyluClient(settings, state)
    service = BeneyluService(client, state, settings.base_url, lambda: datetime.now().astimezone())
    try:
        build_server(service).run()
    finally:
        client.close()
