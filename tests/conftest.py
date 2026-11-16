import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from beneylu_mcp.client import BeneyluError
from beneylu_mcp.service import BeneyluService
from beneylu_mcp.state import StateStore

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://school.beneylu.com"
P = "01AAAAAAAAAAAAAAAAAAAAAAA"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def raw_post(post_id: str) -> dict:
    for page in ("posts_page1.json", "posts_page2.json", "posts_page3.json"):
        for post in load(page)["posts"]:
            if post["id"] == post_id:
                return post
    raise KeyError(post_id)


class Clock:
    def __init__(self, iso: str = "2026-11-16T12:00:00+01:00"):
        self.value = datetime.fromisoformat(iso)

    def set(self, iso: str) -> None:
        self.value = datetime.fromisoformat(iso)

    def __call__(self) -> datetime:
        return self.value


class FakeClient:
    def __init__(self):
        self.pages = {n: load(f"posts_page{n}.json") for n in (1, 2, 3)}
        self.notification_list = load("notifications.json")
        self.unread = 0
        self.failing: set[tuple[str, str]] = set()
        self.calls: list[tuple[str, str, dict]] = []

    def calls_keys(self):
        return [(m, path, tuple(sorted(params.items()))) for m, path, params in self.calls]

    def get_json(self, path, params=None):
        params = dict(params or {})
        self.calls.append(("GET", path, params))
        if ("GET", path) in self.failing:
            raise BeneyluError(f"Beneylu a répondu 503 sur {path}.")
        if path == "/api/auth/users/me":
            return load("me.json")
        if path == "/api/auth/groups/classrooms-and-schools":
            return load("groups.json")
        if path == "/api/family/posts":
            assert params["status"] == "published"
            return copy.deepcopy(self.pages[params["page"]])
        if path == "/api/notification/notifications-in-app":
            return copy.deepcopy(self.notification_list)
        if path == "/api/chat/family/count":
            return self.unread
        if path == "/api/chat/family/conversations":
            return []
        if path.startswith("/api/chat/family/conversations/"):
            return {"messages": []}
        raise AssertionError(f"unexpected GET {path}")

    def post_json(self, path, body):
        self.calls.append(("POST", path, {}))
        if path == "/api/auth/users/lookup":
            return [u for u in load("users_lookup.json") if u["id"] in body["ids"]]
        raise AssertionError(f"unexpected POST {path}")

    def _post(self, post_id):
        for page in self.pages.values():
            for post in page["posts"]:
                if post["id"] == post_id:
                    return post
        raise KeyError(post_id)

    def edit_post(self, post_id, content):
        self._post(post_id)["content"] = content

    def add_signature(self, post_id, by, child):
        self._post(post_id)["postSignatures"].append(
            {"signedById": by, "signedForId": child, "createdAt": "2026-11-16T08:00:00+01:00", "value": "signature"}
        )

    def fail(self, method, path):
        self.failing.add((method, path))

    def set_unread(self, n):
        self.unread = n


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def fake():
    return FakeClient()


@pytest.fixture
def svc(tmp_path, fake, clock):
    return BeneyluService(fake, StateStore(tmp_path / "state.db"), BASE, clock)
