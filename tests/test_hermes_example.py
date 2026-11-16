import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "examples" / "hermes" / "beneylu_whats_new.py"

POST = {
    "id": "p1",
    "change": "updated",
    "already_reported_at": "2026-11-17T13:12:00+01:00",
    "children": ["Lou"],
    "author": "Mme Rivière",
    "date": "2026-11-17T13:12:00+01:00",
    "text": "Sortie au musée jeudi 26/11.",
    "url": "https://school.beneylu.com/p1",
}


class FakeMcp:
    calls: list

    def __init__(self):
        FakeMcp.calls = []

    def tool(self, name, args=None):
        FakeMcp.calls.append((name, args))
        if name == "whats_new":
            return {"posts": [POST], "notifications": [], "cursor": "c1"}
        return {}

    def close(self):
        pass


@pytest.fixture
def script(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("beneylu_whats_new", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "Mcp", FakeMcp)
    monkeypatch.setattr(mod, "LOG", str(tmp_path / "sent_log.json"))
    monkeypatch.setattr(mod, "bot_token", lambda: "token")
    return mod


def test_render_marks_updated_and_resent_posts(script):
    text = script.render({"posts": [POST]})
    assert "Rappel" in text
    assert "Mot modifié" in text


def test_no_ack_when_no_recipient(script, monkeypatch, capsys):
    monkeypatch.setattr(script, "CHATS", {})
    script.main()
    assert ("ack", {"cursor": "c1"}) not in FakeMcp.calls
    assert capsys.readouterr().out.startswith("ÉTAT : ÉCHEC")


def test_ack_after_successful_send(script, monkeypatch):
    sent = []
    monkeypatch.setattr(script, "CHATS", {"A": "1"})
    monkeypatch.setattr(script, "send", lambda token, chat, text: sent.append(chat))
    script.main()
    assert sent == ["1"]
    assert ("ack", {"cursor": "c1"}) in FakeMcp.calls


def test_monitor_output_is_stable(script, capsys):
    log = {"sent": [{"id": "p1", "text": "x"}], "error": None}
    script.print_monitor(log)
    first = capsys.readouterr().out
    script.print_monitor(log)
    assert capsys.readouterr().out == first
