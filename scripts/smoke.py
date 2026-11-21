"""Contrôle en direct, en lecture seule, avec un état temporaire.

Usage : uv run python scripts/smoke.py [chemin/vers/.env]
N'affiche que des comptes, jamais le contenu des mots.
"""

import sys
import tempfile
from datetime import datetime
from pathlib import Path

from beneylu_mcp.client import BeneyluClient
from beneylu_mcp.config import load_settings
from beneylu_mcp.service import BeneyluService
from beneylu_mcp.state import StateStore


def main() -> None:
    dotenv = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".env")
    settings = load_settings(dotenv=dotenv)
    with tempfile.TemporaryDirectory() as tmp:
        state = StateStore(Path(tmp) / "state.db")
        client = BeneyluClient(settings, state)
        service = BeneyluService(
            client, state, settings.base_url, lambda: datetime.now().astimezone(), settings.first_run_days
        )
        try:
            account = service.account()
            posts = service.list_posts()
            first = posts["posts"][0]["id"] if posts["posts"] else None
            new = service.whats_new()
            again = service.whats_new()  # not acknowledged: everything comes back
            service.ack(again["cursor"])
            after_ack = service.whats_new()
            print(f"enfants : {', '.join(c['first_name'] for c in account['children'])}")
            print(f"classes et écoles : {len(account['groups'])}")
            print(
                f"mots page 1 : {len(posts['posts'])} sur {posts['total_pages']} pages, "
                f"à signer : {sum(1 for p in posts['posts'] if p['pending_signature_for'])}"
            )
            print(
                f"whats_new (premier appel) : {len(new['posts'])} mots, {len(new['notifications'])} notifications, "
                f"{len(new['cards'])} cartes, "
                f"{new['unread_messages']} messages non lus"
            )
            print(f"whats_new (sans ack) : {len(again['posts'])} mots, {len(again['notifications'])} notifications")
            print(f"whats_new (après ack) : {len(after_ack['posts'])} mots, {len(after_ack['notifications'])} notifications")
            print(f"notifications : {len(service.notifications())}")
            cards = service.list_cards(limit=5)
            print(f"pancartes : {len(cards['boards'])}, dernières cartes : {len(cards['cards'])}")
            with_media = next((c for c in cards["cards"] if c["media_count"]), None)
            if with_media:
                media = service.get_card_media(with_media["id"])["media"]
                print(f"get_card_media : {len(media)} fichier(s), lien présent : {all(m['download_url'] for m in media)}")
            print(f"conversations : {len(service.conversations() or [])}")
            if first:
                print(f"get_post retrouve le premier mot : {service.get_post(first)['id'] == first}")
        finally:
            client.close()


if __name__ == "__main__":
    main()
