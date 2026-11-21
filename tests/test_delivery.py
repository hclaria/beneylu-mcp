"""At-least-once delivery: whats_new never forgets a change until the caller acknowledges it."""

import json

import pytest

from beneylu_mcp.client import BeneyluError
from beneylu_mcp.server import build_server
from beneylu_mcp.service import BeneyluService
from beneylu_mcp.state import StateStore
from conftest import BASE, P
from test_server import call, text_of


def ids(r):
    return [p["id"] for p in r["posts"]]


def test_lost_reply_is_reported_again(svc):
    first = svc.whats_new()  # the reply never reaches the parents
    assert ids(first) == [P + "1"] and first["posts"][0]["already_reported_at"] is None
    again = svc.whats_new()
    assert ids(again) == [P + "1"]
    post = again["posts"][0]
    assert post["already_reported_at"] == first["checked_at"]
    assert post["report_count"] == 2 and post["change"] == "new"
    assert again["notifications"][0]["already_reported_at"] == first["checked_at"]


def test_ack_stops_reports(svc):
    r = svc.whats_new()
    assert svc.ack(r["cursor"]) == {"acknowledged": 4, "already_acknowledged": False}  # 1 post, 1 notification, 2 cards
    after = svc.whats_new()
    assert after["posts"] == [] and after["notifications"] == []
    assert after["first_run"] is False


def test_ack_is_idempotent_and_rejects_unknown_cursor(svc):
    r = svc.whats_new()
    svc.ack(r["cursor"])
    assert svc.ack(r["cursor"]) == {"acknowledged": 0, "already_acknowledged": True}
    with pytest.raises(BeneyluError, match="Curseur inconnu"):
        svc.ack("nope")


def test_unacked_first_run_stays_first_run(svc):
    svc.whats_new()
    assert svc.whats_new()["first_run"] is True
    assert svc.state.get("initialized") is None


def test_late_ack_of_old_batch_keeps_newer_edit(svc, fake):
    old = svc.whats_new()
    svc.ack(old["cursor"])
    fake.edit_post(P + "2", content="<p>Version 1</p>")
    v1 = svc.whats_new()  # reported, never acknowledged
    fake.edit_post(P + "2", content="<p>Version 2</p>")
    v2 = svc.whats_new()
    assert [(p["id"], p["text"], p["already_reported_at"]) for p in v2["posts"]] == [(P + "2", "Version 2", None)]
    svc.ack(v1["cursor"])  # a stale ack must not swallow Version 2
    still = svc.whats_new()
    assert [(p["id"], p["text"]) for p in still["posts"]] == [(P + "2", "Version 2")]
    svc.ack(still["cursor"])
    assert svc.whats_new()["posts"] == []


def test_ack_covers_items_reported_by_earlier_batches(svc):
    svc.whats_new()
    second = svc.whats_new()
    svc.ack(second["cursor"])
    assert svc.pending() == {"posts": [], "notifications": [], "cards": []}


def test_pending_item_survives_leaving_the_window(svc, clock):
    first = svc.whats_new()
    clock.set("2027-01-30T12:00:00+01:00")  # P1 is now far outside the 30-day window
    later = svc.whats_new()
    assert P + "1" in ids(later)
    assert next(p for p in later["posts"] if p["id"] == P + "1")["already_reported_at"] == first["checked_at"]


def test_unread_increase_repeats_until_ack(svc, fake):
    r = svc.whats_new()
    svc.ack(r["cursor"])
    fake.set_unread(3)
    assert svc.whats_new()["unread_messages_increased"] is True
    r = svc.whats_new()
    assert r["unread_messages_increased"] is True
    svc.ack(r["cursor"])
    assert svc.whats_new()["unread_messages_increased"] is False


def test_pending_reads_local_state_only(svc):
    svc.whats_new()
    calls = len(svc.client.calls)
    p = svc.pending()
    assert len(svc.client.calls) == calls
    assert [x["id"] for x in p["posts"]] == [P + "1"] and p["posts"][0]["report_count"] == 1
    assert [x["id"] for x in p["notifications"]] == ["n-1"]


def test_pending_survives_restart(tmp_path, fake, clock):
    db = tmp_path / "state.db"
    BeneyluService(fake, StateStore(db), BASE, clock).whats_new()
    r = BeneyluService(fake, StateStore(db), BASE, clock).whats_new()
    assert ids(r) == [P + "1"] and r["posts"][0]["report_count"] == 2


def test_failed_fetch_records_no_batch(svc, fake):
    fake.fail("GET", "/api/notification/notifications-in-app")
    with pytest.raises(BeneyluError):
        svc.whats_new()
    assert svc.pending() == {"posts": [], "notifications": [], "cards": []}


def test_ack_through_mcp(svc):
    server = build_server(svc)
    body = json.loads(text_of(call(server, "whats_new")))
    pending = json.loads(text_of(call(server, "pending")))
    assert [p["id"] for p in pending["posts"]] == [P + "1"]
    ok = json.loads(text_of(call(server, "ack", {"cursor": body["cursor"]})))
    assert ok == {"acknowledged": 4, "already_acknowledged": False}  # 1 post, 1 notification, 2 cards
    bad = call(server, "ack", {"cursor": "nope"})
    assert bad.is_error and "Curseur inconnu" in text_of(bad)
