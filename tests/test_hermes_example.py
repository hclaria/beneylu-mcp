import importlib.util
import os
import sys
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
    calls: list = []
    posts: list = [POST]

    def __init__(self):
        FakeMcp.calls = []

    def tool(self, name, args=None):
        FakeMcp.calls.append((name, args))
        if name == "whats_new":
            return {"posts": list(FakeMcp.posts), "notifications": [], "cursor": "c1"}
        return {}

    def close(self):
        pass


def load_script():
    spec = importlib.util.spec_from_file_location("beneylu_whats_new", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def script(tmp_path, monkeypatch):
    mod = load_script()
    monkeypatch.setattr(FakeMcp, "posts", [POST])
    monkeypatch.setattr(mod, "Mcp", FakeMcp)
    monkeypatch.setattr(mod, "LOG", str(tmp_path / "sent_log.json"))
    monkeypatch.setattr(mod, "bot_token", lambda: "token")
    monkeypatch.setattr(mod, "send", lambda token, chat, text: None)
    monkeypatch.setattr(mod, "CHATS", {"A": "1"})
    return mod


def acked():
    return ("ack", {"cursor": "c1"}) in FakeMcp.calls


def test_render_marks_updated_and_resent_posts(script):
    text = script.render({"posts": [POST]})
    assert "Rappel" in text
    assert "Mot modifié" in text


def test_no_ack_when_no_recipient(script, monkeypatch, capsys):
    monkeypatch.setattr(script, "CHATS", {})
    script.main()
    assert not acked()
    assert capsys.readouterr().out.startswith("ÉTAT : ÉCHEC")


def test_ack_after_successful_send(script, monkeypatch):
    sent = []
    monkeypatch.setattr(script, "send", lambda token, chat, text: sent.append(chat))
    script.main()
    assert sent == ["1"]
    assert acked()


def test_quiet_runs_give_identical_output(script, monkeypatch, capsys):
    script.main()
    capsys.readouterr()
    monkeypatch.setattr(FakeMcp, "posts", [])
    script.main()
    first = capsys.readouterr().out
    script.main()
    assert capsys.readouterr().out == first
    assert '"id": "p1"' in first


def test_creates_missing_log_folder(script, monkeypatch, tmp_path):
    log = tmp_path / "missing" / "cache" / "sent_log.json"
    monkeypatch.setattr(script, "LOG", str(log))
    script.main()
    assert '"p1"' in log.read_text(encoding="utf-8")
    assert acked()


def test_no_ack_when_history_cannot_be_saved(script, monkeypatch):
    real_save = script.save_log
    calls = []

    def flaky_save(log):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disque plein")
        real_save(log)

    monkeypatch.setattr(script, "save_log", flaky_save)
    script.main()
    assert not acked()


def test_history_is_private(script):
    script.main()
    assert os.stat(script.LOG).st_mode & 0o777 == 0o600


def test_server_error_is_reported(monkeypatch):
    mod = load_script()
    monkeypatch.setattr(mod, "RUN", [sys.executable, "-c",
                                     "import sys; sys.stderr.write('Identifiants Beneylu manquants\\n'); sys.exit(1)"])
    with pytest.raises(RuntimeError, match="Identifiants Beneylu manquants"):
        mod.Mcp()
