import pytest

from beneylu_mcp.models import (
    Lookups,
    html_to_text,
    notification_from_api,
    post_date,
    post_fingerprint,
    post_from_api,
)
from conftest import BASE, P, load, raw_post


@pytest.fixture
def lk():
    me = load("me.json")
    return Lookups(
        users={u["id"]: u["displayName"] for u in load("users_lookup.json")},
        groups={g["id"]: g["label"] for g in load("groups.json")},
        children={c["id"]: c["firstName"] for c in me["children"]},
    )


@pytest.fixture
def lk_empty():
    return Lookups(users={}, groups={}, children={})


def test_html_to_text():
    assert (
        html_to_text("<p>Bonjour</p><p>Il n’y aura <strong>PAS</strong> de cantine d&#039;habitude.</p>")
        == "Bonjour\nIl n’y aura PAS de cantine d'habitude."
    )
    assert html_to_text("<ul><li>Sac</li><li>Gourde</li></ul>") == "- Sac\n- Gourde"
    assert html_to_text("a\xa0b<br>c<p></p><p></p>") == "a b\nc"


def test_post_from_api_pending_signature(lk):
    p = post_from_api(raw_post(P + "1"), lk, BASE)
    assert p["author"] == "Mme Martin"
    assert p["children"] == ["Basile"]
    assert p["groups"] == ["Classe GS1"]
    assert p["signature_required"] is True
    assert p["pending_signature_for"] == ["Basile"]
    assert p["signatures"] == []
    assert p["date"] == "2026-11-13T17:42:38+01:00"
    assert p["url"] == f"{BASE}/family-information/{P}1"
    assert p["text"] == "Bonjour\nMardi : PAS de cantine d'habitude."


def test_post_from_api_signed(lk):
    p = post_from_api(raw_post(P + "2"), lk, BASE)
    assert p["date"] == "2026-11-01T07:00:00+01:00"
    assert p["pending_signature_for"] == []
    assert p["signatures"] == [{"child": "Alice", "by": "Mme Parent Deux", "at": "2026-11-01T19:00:00+01:00"}]
    assert p["attachments"] == 1
    assert p["replies_allowed"] is True


def test_post_without_signature(lk):
    p = post_from_api(raw_post(P + "4"), lk, BASE)
    assert p["signature_required"] is False
    assert p["pending_signature_for"] == []


def test_unknown_ids_fall_back(lk_empty):
    p = post_from_api(raw_post(P + "1"), lk_empty, BASE)
    assert p["author"] == "inconnu (300)"
    assert p["children"] == ["inconnu (202)"]
    assert p["groups"] == ["inconnu (400)"]


def test_post_date_prefers_visible_at():
    assert post_date(raw_post(P + "2")).isoformat() == "2026-11-01T07:00:00+01:00"
    assert post_date(raw_post(P + "1")).isoformat() == "2026-11-13T17:42:38+01:00"


def test_fingerprint_ignores_signatures():
    raw = raw_post(P + "1")
    signed = {**raw, "postSignatures": [{"signedById": 101, "signedForId": 202, "createdAt": "x"}]}
    assert post_fingerprint(raw) == post_fingerprint(signed)
    assert post_fingerprint(raw) != post_fingerprint({**raw, "content": "<p>Piscine</p>"})
    assert post_fingerprint(raw) != post_fingerprint({**raw, "visibleAt": "2026-11-20T08:00:00+01:00"})


def test_notification_from_api():
    n = notification_from_api(load("notifications.json")[1], BASE)
    assert n["kind"] == "calendrier"
    assert n["url"] == f"{BASE}/cma/os/app/calendar?id=1"
    assert "CONSEIL" in n["text"]
    assert n["read"] is True
    assert n["date"] == "2026-11-05T09:00:00+01:00"


def test_unknown_notification_app():
    n = notification_from_api({**load("notifications.json")[0], "appName": "ROLL"}, BASE)
    assert n["kind"] == "roll"
