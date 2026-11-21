import importlib.util
import json
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


CARD = {
    "id": "c1",
    "change": "new",
    "already_reported_at": None,
    "board": "VIE DE LA CLASSE",
    "author": "Mme Rivière",
    "date": "2026-11-20T19:30:00+01:00",
    "description": "Arc-en-ciel entre deux averses",
    "text": "",
    "media_count": 2,
}
TEXT_CARD = {**CARD, "id": "c2", "description": "Sortie au parc vendredi", "media_count": 0}


class FakeMcp:
    calls: list = []
    posts: list = [POST]
    cards: list = []

    def __init__(self):
        FakeMcp.calls = []

    def tool(self, name, args=None):
        FakeMcp.calls.append((name, args))
        if name == "whats_new":
            return {"posts": list(FakeMcp.posts), "notifications": [], "cards": list(FakeMcp.cards), "cursor": "c1"}
        if name == "get_card_media":
            return {"media": [
                {"media_id": 1, "name": "a.jpg", "mime_type": "image/jpeg", "download_url": "https://m/1"},
                {"media_id": 2, "name": "b.mp4", "mime_type": "video/mp4", "download_url": "https://m/2"},
                {"media_id": 3, "name": "c.pdf", "mime_type": "application/pdf", "download_url": "https://m/3"},
            ]}
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
    monkeypatch.setattr(FakeMcp, "cards", [])
    monkeypatch.setattr(mod, "Mcp", FakeMcp)
    monkeypatch.setattr(mod, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(mod.urllib.request, "urlretrieve", lambda url, path: open(path, "wb").write(url.encode()))
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


def test_card_media_sent_to_every_parent_before_ack(script, monkeypatch):
    monkeypatch.setattr(FakeMcp, "cards", [CARD, TEXT_CARD])
    monkeypatch.setattr(script, "CHATS", {"A": "1", "B": "2"})
    texts, uploads = [], []
    monkeypatch.setattr(script, "send", lambda token, chat, text: texts.append((chat, text)))
    monkeypatch.setattr(script, "tg_upload", lambda token, method, fields, files: uploads.append(
        (fields["chat_id"], method, json.loads(fields["media"]), sorted(files))))
    script.main()
    assert [u[:2] for u in uploads] == [("1", "sendMediaGroup"), ("2", "sendMediaGroup")]
    album = uploads[0][2]
    assert [m["type"] for m in album] == ["photo", "video"]  # the PDF is not a photo or video
    assert "Arc-en-ciel" in album[0]["caption"] and "caption" not in album[1]
    assert all("Sortie au parc" in t for _, t in texts)  # card without media rides with the text summary
    assert FakeMcp.calls.count(("get_card_media", {"card_id": "c1"})) == 1  # downloaded once for all parents
    assert acked()
    assert '"kind": "pancarte"' in open(script.LOG, encoding="utf-8").read()


def test_no_ack_when_media_upload_fails(script, monkeypatch, capsys):
    monkeypatch.setattr(FakeMcp, "posts", [])
    monkeypatch.setattr(FakeMcp, "cards", [CARD])

    def refuse(*args):
        raise RuntimeError("Telegram a refusé sendMediaGroup")

    monkeypatch.setattr(script, "tg_upload", refuse)
    script.main()
    assert not acked()
    assert capsys.readouterr().out.startswith("ÉTAT : ÉCHEC")


def test_single_photo_goes_with_its_caption(script, monkeypatch, tmp_path):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(script, "tg_upload", lambda token, method, fields, files: calls.append((method, fields, files)))
    script.send_card("t", "1", CARD, [(str(photo), "image/jpeg")])
    assert calls[0][0] == "sendPhoto" and "Arc-en-ciel" in calls[0][1]["caption"] and "photo" in calls[0][2]
