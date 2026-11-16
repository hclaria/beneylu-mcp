import pytest

from beneylu_mcp.client import BeneyluError
from conftest import P

POSTS_PAGE_3 = ("GET", "/api/family/posts", (("page", 3), ("status", "published")))


def test_first_run_reports_last_7_days_only(svc):
    r = svc.whats_new()
    assert r["first_run"] is True
    assert [(p["id"], p["change"]) for p in r["posts"]] == [(P + "1", "new")]
    assert [n["id"] for n in r["notifications"]] == ["n-1"]  # n-2 > 7 days, n-3 FAMILY, n-4 > 30 days
    assert r["notifications"][0]["change"] == "new"
    assert svc.state.seen_fingerprint("post", P + "2") is not None
    assert svc.state.seen_fingerprint("notification", "n-2") is not None


def test_first_run_post_carries_signature_state(svc):
    post = svc.whats_new()["posts"][0]
    assert post["pending_signature_for"] == ["Basile"]
    assert post["author"] == "Mme Martin"


def test_pagination_stops_at_window(svc):
    svc.whats_new()
    keys = svc.client.calls_keys()
    assert ("GET", "/api/family/posts", (("page", 2), ("status", "published"))) in keys
    assert POSTS_PAGE_3 not in keys


def test_second_run_reports_nothing_then_content_edit(svc, fake):
    svc.whats_new()
    second = svc.whats_new()
    assert second["first_run"] is False
    assert second["posts"] == [] and second["notifications"] == []
    fake.edit_post(P + "2", content="<p>Sport et pas piscine</p>")
    r = svc.whats_new()
    assert [(p["id"], p["change"]) for p in r["posts"]] == [(P + "2", "updated")]
    assert r["posts"][0]["text"] == "Sport et pas piscine"


def test_new_notification_after_first_run(svc, fake):
    svc.whats_new()
    fake.notification_list.insert(
        0,
        {
            "id": "n-5",
            "url": "/cma/os/app/calendar?id=2",
            "content": '"EXERCICE INCENDIE" a été ajouté.',
            "createdAt": "2026-11-16T11:00:00+01:00",
            "read": False,
            "appName": "CALENDAR",
        },
    )
    assert [n["id"] for n in svc.whats_new()["notifications"]] == ["n-5"]


def test_new_signature_is_not_an_update(svc, fake):
    svc.whats_new()
    fake.add_signature(P + "1", by=101, child=202)
    assert svc.whats_new()["posts"] == []


def test_scheduled_post_appears_when_visible(svc, clock):
    first = svc.whats_new()
    assert P + "3" not in [p["id"] for p in first["posts"]]
    assert svc.state.seen_fingerprint("post", P + "3") is None
    clock.set("2099-01-01T09:00:00+01:00")
    assert P + "3" in [p["id"] for p in svc.whats_new()["posts"]]


def test_failure_midway_marks_nothing(svc, fake):
    fake.fail("GET", "/api/notification/notifications-in-app")
    with pytest.raises(BeneyluError):
        svc.whats_new()
    assert svc.state.get("initialized") is None
    assert svc.state.seen_fingerprint("post", P + "1") is None


def test_unread_messages_increase(svc, fake):
    fake.set_unread(0)
    assert svc.whats_new()["unread_messages_increased"] is False
    fake.set_unread(2)
    r = svc.whats_new()
    assert r["unread_messages"] == 2 and r["unread_messages_increased"] is True
    assert svc.whats_new()["unread_messages_increased"] is False


def test_list_posts_hides_scheduled(svc):
    r = svc.list_posts()
    assert r["page"] == 1 and r["total_pages"] == 3
    assert [p["id"] for p in r["posts"]] == [P + "1", P + "2"]


def test_get_post_scans_pages_and_reports_missing(svc):
    assert svc.get_post(P + "4")["id"] == P + "4"
    with pytest.raises(BeneyluError, match="introuvable"):
        svc.get_post("nope")


def test_account(svc):
    a = svc.account()
    assert a["name"] == "M. Parent Un"
    assert a["children"] == [{"id": 201, "first_name": "Alice"}, {"id": 202, "first_name": "Basile"}]
    assert a["groups"] == ["Classe GS1", "École Les Pins"]


def test_notifications_limit(svc):
    n = svc.notifications(limit=2)
    assert [x["id"] for x in n] == ["n-1", "n-2"]


def test_lookups_are_cached(svc):
    svc.list_posts()
    svc.list_posts()
    lookups = [c for c in svc.client.calls if c[1] == "/api/auth/users/lookup"]
    assert len(lookups) == 1


def test_never_posts_outside_lookup(svc):
    svc.whats_new()
    svc.list_posts()
    svc.notifications()
    svc.account()
    svc.conversations()
    assert {path for (m, path, _) in svc.client.calls_keys() if m == "POST"} <= {"/api/auth/users/lookup"}


def test_signing_turned_on_is_an_update(svc, fake):
    svc.whats_new()
    fake._post(P + "2")["signableFor"] = [201, 202]
    assert [(p["id"], p["change"]) for p in svc.whats_new()["posts"]] == [(P + "2", "updated")]
