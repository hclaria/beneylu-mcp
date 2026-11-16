import asyncio
import json

import pytest
from mcp import Client

from beneylu_mcp.server import build_server, main
from conftest import P

EXPECTED = {
    "whats_new",
    "list_posts",
    "get_post",
    "get_notifications",
    "list_conversations",
    "get_conversation",
    "get_account",
}


@pytest.fixture
def server(svc):
    return build_server(svc)


def list_tools(server):
    async def run():
        async with Client(server) as c:
            return (await c.list_tools()).tools

    return asyncio.run(run())


def call(server, name, args=None):
    async def run():
        async with Client(server) as c:
            return await c.call_tool(name, args or {})

    return asyncio.run(run())


def text_of(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


def test_tools_exposed(server):
    assert {t.name for t in list_tools(server)} == EXPECTED


def test_all_tools_are_read_only(server):
    assert all(t.annotations and t.annotations.read_only_hint for t in list_tools(server))


def test_guidance_in_descriptions(server):
    d = {t.name: t.description for t in list_tools(server)}
    assert "automatique" in d["whats_new"]
    assert "lu" in d["whats_new"]
    assert "demande d'un parent" in d["get_conversation"]


def test_call_returns_json(server):
    result = call(server, "whats_new")
    assert not result.is_error
    body = json.loads(text_of(result))
    assert body["first_run"] is True
    assert body["posts"][0]["pending_signature_for"] == ["Basile"]


def test_tool_arguments(server):
    assert json.loads(text_of(call(server, "get_post", {"post_id": P + "1"})))["id"] == P + "1"
    assert json.loads(text_of(call(server, "list_posts", {"page": 2})))["page"] == 2
    assert len(json.loads(text_of(call(server, "get_notifications", {"limit": 1})))["notifications"]) == 1


def test_beneylu_error_is_reported_not_masked(server, fake):
    fake.fail("GET", "/api/notification/notifications-in-app")
    result = call(server, "whats_new")
    assert result.is_error
    assert "Beneylu a répondu 503" in text_of(result)


def test_main_without_credentials_exits_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for key in ("BENEYLU_USERNAME", "BENEYLU_PASSWORD", "BENEYLU_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "BENEYLU_USERNAME" in captured.err
    assert captured.out == ""
