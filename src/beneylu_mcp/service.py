from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any

from .client import BeneyluError
from .models import (
    Lookups,
    notification_from_api,
    parse_dt,
    post_date,
    post_fingerprint,
    post_from_api,
)
from .state import StateStore

WINDOW = timedelta(days=30)
FIRST_RUN_WINDOW = timedelta(days=7)
POSTS_PATH = "/api/family/posts"
NOTIFICATIONS_PATH = "/api/notification/notifications-in-app"
CHAT_PATH = "/api/chat/family"


class BeneyluService:
    def __init__(self, client, state: StateStore, base_url: str, now: Callable[[], datetime]):
        self.client = client
        self.state = state
        self.base_url = base_url
        self._now = now
        self._me: dict | None = None
        self._groups: dict[int, str] | None = None
        self._users: dict[int, str] = {}

    def account(self) -> dict:
        me = self._account_raw()
        return {
            "name": me.get("displayName"),
            "children": [{"id": c["id"], "first_name": c.get("firstName")} for c in me.get("children") or []],
            "groups": list(self._group_labels().values()),
        }

    def list_posts(self, page: int = 1) -> dict:
        data = self._posts_page(page)
        now = self._now()
        raws = [r for r in data.get("posts") or [] if post_date(r) <= now]
        lk = self._lookups(raws)
        return {
            "page": int(data.get("currentPage") or page),
            "total_pages": int(data.get("totalPages") or 1),
            "posts": [post_from_api(r, lk, self.base_url) for r in raws],
        }

    def get_post(self, post_id: str) -> dict:
        page = 1
        while True:
            data = self._posts_page(page)
            for raw in data.get("posts") or []:
                if raw["id"] == post_id:
                    return post_from_api(raw, self._lookups([raw]), self.base_url)
            if page >= int(data.get("totalPages") or 1):
                raise BeneyluError(f"Mot introuvable : {post_id}.")
            page += 1

    def notifications(self, limit: int = 20) -> list[dict]:
        raws = self.client.get_json(NOTIFICATIONS_PATH) or []
        return [notification_from_api(n, self.base_url) for n in raws[: max(limit, 0)]]

    def conversations(self) -> Any:
        return self.client.get_json(f"{CHAT_PATH}/conversations")

    def conversation(self, conversation_id: str) -> Any:
        return self.client.get_json(f"{CHAT_PATH}/conversations/{conversation_id}/messages")

    def whats_new(self) -> dict:
        now = self._now()
        start = now - WINDOW
        first_run = self.state.get("initialized") is None
        report_start = now - FIRST_RUN_WINDOW if first_run else start

        # Read everything before touching the state, so a failure loses nothing.
        posts = self._posts_in_window(start, now)
        notifications = [
            n
            for n in self.client.get_json(NOTIFICATIONS_PATH) or []
            if n.get("appName") != "FAMILY" and start <= parse_dt(n["createdAt"]) <= now
        ]
        unread = _as_int(self.client.get_json(f"{CHAT_PATH}/count"))
        lk = self._lookups(posts)

        seen: list[tuple[str, str, str]] = []
        new_posts = []
        for raw in posts:
            fingerprint = post_fingerprint(raw)
            change = self._change("post", raw["id"], fingerprint)
            seen.append(("post", raw["id"], fingerprint))
            if change and post_date(raw) >= report_start:
                new_posts.append({**post_from_api(raw, lk, self.base_url), "change": change})
        new_notifications = []
        for raw in notifications:
            change = self._change("notification", raw["id"], raw["id"])
            seen.append(("notification", raw["id"], raw["id"]))
            if change and parse_dt(raw["createdAt"]) >= report_start:
                new_notifications.append({**notification_from_api(raw, self.base_url), "change": change})
        previous_unread = int(self.state.get("chat_unread") or 0)

        self.state.mark_seen(seen)
        self.state.set("chat_unread", str(unread))
        self.state.set("initialized", "1")
        return {
            "first_run": first_run,
            "checked_at": now.isoformat(),
            "posts": new_posts,
            "notifications": new_notifications,
            "unread_messages": unread,
            "unread_messages_increased": unread > previous_unread,
        }

    def _change(self, source: str, item_id: str, fingerprint: str) -> str | None:
        previous = self.state.seen_fingerprint(source, item_id)
        if previous is None:
            return "new"
        return None if previous == fingerprint else "updated"

    def _posts_in_window(self, start: datetime, now: datetime) -> list[dict]:
        kept, page = [], 1
        while True:
            data = self._posts_page(page)
            raws = data.get("posts") or []
            kept += [r for r in raws if start <= post_date(r) <= now]
            if not raws or page >= int(data.get("totalPages") or 1) or min(map(post_date, raws)) < start:
                return kept
            page += 1

    def _posts_page(self, page: int) -> dict:
        return self.client.get_json(POSTS_PATH, {"page": page, "status": "published"}) or {}

    def _account_raw(self) -> dict:
        if self._me is None:
            self._me = self.client.get_json("/api/auth/users/me") or {}
        return self._me

    def _group_labels(self) -> dict[int, str]:
        if self._groups is None:
            groups = self.client.get_json("/api/auth/groups/classrooms-and-schools") or []
            self._groups = {g["id"]: g.get("label") or "" for g in groups}
        return self._groups

    def _lookups(self, raws: Iterable[dict]) -> Lookups:
        ids: set[int] = set()
        for raw in raws:
            ids.add(raw.get("authorId"))
            ids.update(s.get("signedById") for s in raw.get("postSignatures") or [])
        missing = sorted(i for i in ids - self._users.keys() if isinstance(i, int))
        if missing:
            for user in self.client.post_json("/api/auth/users/lookup", {"ids": missing}) or []:
                self._users[user["id"]] = user.get("displayName") or ""
            for user_id in missing:
                self._users.setdefault(user_id, "")
        children = {c["id"]: c.get("firstName") or "" for c in self._account_raw().get("children") or []}
        return Lookups(users=self._users, groups=self._group_labels(), children=children)


def _as_int(value: Any) -> int:
    if isinstance(value, dict):
        value = value.get("count", 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
