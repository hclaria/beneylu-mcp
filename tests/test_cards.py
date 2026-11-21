import copy

import pytest

from beneylu_mcp.client import BeneyluError
from beneylu_mcp.service import BeneyluService
from beneylu_mcp.state import StateStore
from conftest import BASE, load


def run(svc):
    r = svc.whats_new()
    svc.ack(r["cursor"])
    return r


def new_card(card_id="c-9", date="2026-11-16T11:00:00+01:00", desc="Les animaux de la ferme", media=(9010,)):
    card = copy.deepcopy(load("cards_b-1.json")[0])
    card.update(id=card_id, createdAt=date, updatedAt=date, description=desc)
    card["cardAttachments"] = [
        {"mediaId": m, "entityId": card_id, "entityType": "Card", "timestamp": 1, "signature": f"sig-{m}"} for m in media
    ]
    return card


def test_first_run_reports_recent_published_cards(svc):
    r = svc.whats_new()
    cards = r["cards"]
    assert [c["id"] for c in cards] == ["c-1", "c-2"]  # c-3 > 7 days, c-4 draft, b-2 archived
    assert cards[0] == {
        "id": "c-1",
        "board_id": "b-1",
        "board": "VIE DE LA CLASSE",
        "date": "2026-11-15T19:30:00+01:00",
        "type": "image",
        "author": "Mme Martin",
        "description": "Arc-en-ciel entre deux averses",
        "text": "",
        "media_count": 2,
        "embeds": 0,
        "change": "new",
        "already_reported_at": None,
        "report_count": 1,
    }


def test_card_notifications_are_not_repeated(svc):
    assert "n-5" not in [n["id"] for n in svc.whats_new()["notifications"]]


def test_card_follows_ack_cycle(svc, fake):
    run(svc)
    assert run(svc)["cards"] == []
    fake.add_card("b-1", new_card())
    lost = svc.whats_new()  # delivery fails: no ack
    assert [c["id"] for c in lost["cards"]] == ["c-9"]
    again = svc.whats_new()
    assert again["cards"][0]["report_count"] == 2 and again["cards"][0]["already_reported_at"]
    assert [c["id"] for c in svc.pending()["cards"]] == ["c-9"]
    svc.ack(again["cursor"])
    assert run(svc)["cards"] == []


def test_new_photo_on_a_card_is_an_update(svc, fake):
    run(svc)
    fake.cards["b-1"][0]["cardAttachments"].append(
        {"mediaId": 9020, "entityId": "c-1", "entityType": "Card", "timestamp": 2, "signature": "sig-9020"}
    )
    assert [(c["id"], c["change"]) for c in run(svc)["cards"]] == [("c-1", "updated")]


def test_regenerated_signatures_are_not_an_update(svc, fake):
    run(svc)
    for a in fake.cards["b-1"][0]["cardAttachments"]:
        a["timestamp"], a["signature"] = 99, "other"
    assert run(svc)["cards"] == []


def test_upgraded_install_does_not_replay_old_cards(svc, fake):
    run(svc)
    svc.state.delete("cards_initialized")  # state written by a version without cards
    assert run(svc)["cards"] == []
    fake.add_card("b-1", new_card())
    assert [c["id"] for c in run(svc)["cards"]] == ["c-9"]


def test_list_cards_most_recent_first(svc):
    r = svc.list_cards()
    assert [b["id"] for b in r["boards"]] == ["b-1"]
    assert [c["id"] for c in r["cards"]] == ["c-1", "c-2", "c-3"]
    assert [c["id"] for c in svc.list_cards(limit=1)["cards"]] == ["c-1"]
    with pytest.raises(BeneyluError, match="Pancarte introuvable"):
        svc.list_cards("b-404")


def test_get_card_media_signs_each_attachment(svc, fake):
    r = svc.get_card_media("c-1")
    assert r["board"] == "VIE DE LA CLASSE"
    assert [m["media_id"] for m in r["media"]] == [9001, 9002]
    assert r["media"][0] == {
        "media_id": 9001,
        "name": "IMG_0090.jpg",
        "kind": "image",
        "mime_type": "image/jpeg",
        "download_url": "https://media.example/9001.jpg?X-Amz-Signature=a",
    }
    media_calls = [c for c in fake.calls if c[1].startswith("/api/media-library/media/")]
    assert media_calls[0][2] == {
        "mediaId": 9001, "entityId": "c-1", "entityType": "Card", "timestamp": 1795286476, "signature": "sig-9001"
    }
    with pytest.raises(BeneyluError, match="Carte introuvable"):
        svc.get_card_media("c-404")


def test_cardboard_outage_loses_nothing(svc, fake):
    fake.fail("GET", "/api/cardboard/boards")
    with pytest.raises(BeneyluError):
        svc.whats_new()
    fake.failing.clear()
    assert [c["id"] for c in svc.whats_new()["cards"]] == ["c-1", "c-2"]
