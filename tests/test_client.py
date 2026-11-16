import json
from datetime import datetime

import httpx
import pytest
import respx

from beneylu_mcp.client import BeneyluAuthError, BeneyluClient, BeneyluError
from beneylu_mcp.config import Settings
from beneylu_mcp.state import StateStore

BASE = "https://school.beneylu.com"
NOW = datetime.fromisoformat("2026-11-16T12:00:00+01:00")
PASSWORD = "hunter2-secret"
LOGIN_OK = {
    "json": {"auth_url": "https://login.school.beneylu.com/x", "refresh_token": "rt1"},
    "headers": {"set-cookie": "BEARER=b1; Path=/; HttpOnly"},
}
REFRESH_OK = {
    "json": {"auth_url": "https://login.school.beneylu.com/x", "refresh_token": "rt0"},
    "headers": {"set-cookie": "BEARER=b0; Path=/; HttpOnly"},
}


def make_client(tmp_path, username="u", password=PASSWORD, refresh_token=None):
    settings = Settings(username, password, refresh_token, tmp_path)
    return BeneyluClient(settings, StateStore(tmp_path / "state.db"), now=lambda: NOW)


@pytest.fixture
def mock():
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        yield m


def test_login_then_get_stores_refresh_token(tmp_path, mock):
    client = make_client(tmp_path, password="p")
    login = mock.post("/api/auth/login_check").respond(200, **LOGIN_OK)
    init = mock.get("/api/family/init").respond(200, json={"can_view": True})

    assert client.get_json("/api/family/init") == {"can_view": True}
    assert json.loads(login.calls[0].request.content) == {
        "login": "u",
        "password": "p",
        "otp": "",
        "remember_me": True,
        "captcha": "",
    }
    assert init.calls[0].request.headers["cookie"] == "BEARER=b1"
    assert init.calls[0].request.headers["x-requested-with"] == "XMLHttpRequest"
    assert client.state.get("refresh_token") == "rt1"


def test_stored_refresh_token_avoids_login(tmp_path, mock):
    client = make_client(tmp_path)
    client.state.set("refresh_token", "rt0")
    refresh = mock.post("/api/auth/token/refresh").respond(200, **REFRESH_OK)
    login = mock.post("/api/auth/login_check").respond(200, **LOGIN_OK)
    mock.get("/api/family/init").respond(200, json={})

    client.get_json("/api/family/init")
    assert json.loads(refresh.calls[0].request.content) == {"refresh_token": "rt0"}
    assert login.call_count == 0


def test_401_refreshes_once_and_retries(tmp_path, mock):
    client = make_client(tmp_path)
    client.state.set("refresh_token", "rt0")
    refresh = mock.post("/api/auth/token/refresh").respond(200, **REFRESH_OK)
    login = mock.post("/api/auth/login_check").respond(200, **LOGIN_OK)
    init = mock.get("/api/family/init")
    init.side_effect = [httpx.Response(401), httpx.Response(200, json={"ok": 2})]

    assert client.get_json("/api/family/init") == {"ok": 2}
    assert refresh.call_count == 2  # opening the session, then once for the 401
    assert init.call_count == 2
    assert login.call_count == 0


def test_failed_refresh_falls_back_to_login(tmp_path, mock):
    client = make_client(tmp_path)
    client.state.set("refresh_token", "rt-old")
    mock.post("/api/auth/token/refresh").respond(401, json={"code": 401})
    login = mock.post("/api/auth/login_check").respond(200, **LOGIN_OK)
    mock.get("/api/family/init").respond(200, json={})

    client.get_json("/api/family/init")
    assert login.call_count == 1
    assert client.state.get("refresh_token") == "rt1"


def test_captcha_message_and_hourly_limit(tmp_path, mock):
    client = make_client(tmp_path)
    login = mock.post("/api/auth/login_check").respond(
        401, json={"message": "login_error"}, headers={"X-Bns-Captcha": "site-key"}
    )

    with pytest.raises(BeneyluAuthError, match="captcha"):
        client.get_json("/api/family/init")
    with pytest.raises(BeneyluAuthError, match="13:00"):
        client.get_json("/api/family/init")
    assert login.call_count == 1


def test_hourly_limit_survives_restart(tmp_path, mock):
    mock.post("/api/auth/login_check").respond(401, json={"message": "bad_credentials"})
    with pytest.raises(BeneyluAuthError, match="identifiants"):
        make_client(tmp_path).get_json("/api/family/init")
    with pytest.raises(BeneyluAuthError, match="13:00"):
        make_client(tmp_path).get_json("/api/family/init")


def test_otp_needed_message(tmp_path, mock):
    mock.post("/api/auth/login_check").respond(401, json={"message": "otp_needed"})
    with pytest.raises(BeneyluAuthError, match="double authentification"):
        make_client(tmp_path).get_json("/api/family/init")


def test_refresh_only_settings_without_credentials(tmp_path, mock):
    client = make_client(tmp_path, username=None, password=None, refresh_token="rt-env")
    mock.post("/api/auth/token/refresh").respond(401, json={})
    login = mock.post("/api/auth/login_check").respond(200, **LOGIN_OK)
    with pytest.raises(BeneyluAuthError, match="BENEYLU_REFRESH_TOKEN"):
        client.get_json("/api/family/init")
    assert login.call_count == 0


def test_server_error_is_french_and_short(tmp_path, mock):
    client = make_client(tmp_path)
    mock.post("/api/auth/login_check").respond(200, **LOGIN_OK)
    mock.get("/api/family/init").respond(503, text="<html><body>Maintenance</body></html>")
    with pytest.raises(BeneyluError, match="503") as exc:
        client.get_json("/api/family/init")
    assert "<html" not in str(exc.value)


def test_non_json_success_is_an_error(tmp_path, mock):
    client = make_client(tmp_path)
    mock.post("/api/auth/login_check").respond(200, **LOGIN_OK)
    mock.get("/api/family/init").respond(200, text="<html>login page</html>")
    with pytest.raises(BeneyluError, match="JSON"):
        client.get_json("/api/family/init")


def test_network_error_does_not_consume_a_login(tmp_path, mock):
    client = make_client(tmp_path)
    client.state.set("refresh_token", "rt0")
    mock.post("/api/auth/token/refresh").mock(side_effect=httpx.ConnectError("down"))
    login = mock.post("/api/auth/login_check").respond(200, **LOGIN_OK)
    with pytest.raises(BeneyluError, match="injoignable"):
        client.get_json("/api/family/init")
    assert login.call_count == 0
    assert client.state.get("refresh_token") == "rt0"


def test_post_outside_allowlist_is_refused(tmp_path, mock):
    client = make_client(tmp_path)
    with pytest.raises(BeneyluError, match="lecture seule"):
        client.post_json("/api/family/visit", {})
    assert mock.calls.call_count == 0


def test_allowed_lookup_post(tmp_path, mock):
    client = make_client(tmp_path)
    mock.post("/api/auth/login_check").respond(200, **LOGIN_OK)
    lookup = mock.post("/api/auth/users/lookup").respond(200, json=[{"id": 1}])
    assert client.post_json("/api/auth/users/lookup", {"ids": [1]}) == [{"id": 1}]
    assert json.loads(lookup.calls[0].request.content) == {"ids": [1]}


def test_secrets_never_in_error_messages(tmp_path, mock):
    secrets = (PASSWORD, "rt-secret-1", "bearer-secret")
    client = make_client(tmp_path, refresh_token="rt-secret-1")
    mock.post("/api/auth/token/refresh").respond(
        200, json={"refresh_token": "rt-secret-1"}, headers={"set-cookie": "BEARER=bearer-secret; Path=/"}
    )
    mock.get("/api/family/init").respond(500, text=f"boom {PASSWORD} rt-secret-1")
    errors = []
    for call in (
        lambda: client.get_json("/api/family/init"),
        lambda: client.post_json("/api/family/posts/1/sign", {"x": PASSWORD}),
    ):
        with pytest.raises(BeneyluError) as exc:
            call()
        errors.append(str(exc.value))

    mock.post("/api/auth/login_check").respond(401, json={}, headers={"X-Bns-Captcha": "k"})
    mock.post("/api/auth/token/refresh").respond(401, json={})
    with pytest.raises(BeneyluError) as exc:
        make_client(tmp_path / "other", refresh_token="rt-secret-1").get_json("/api/family/init")
    errors.append(str(exc.value))

    for message in errors:
        assert not any(s in message for s in secrets), message


def test_refresh_5xx_keeps_token_and_skips_login(tmp_path, mock):
    client = make_client(tmp_path)
    client.state.set("refresh_token", "rt0")
    mock.post("/api/auth/token/refresh").respond(503, text="<html>maintenance</html>")
    login = mock.post("/api/auth/login_check").respond(200, **LOGIN_OK)
    with pytest.raises(BeneyluError, match="indisponible"):
        client.get_json("/api/family/init")
    assert login.call_count == 0
    assert client.state.get("refresh_token") == "rt0"


def test_login_5xx_does_not_consume_the_hourly_attempt(tmp_path, mock):
    client = make_client(tmp_path)
    login = mock.post("/api/auth/login_check")
    login.side_effect = [httpx.Response(503), httpx.Response(200, **LOGIN_OK)]
    mock.get("/api/family/init").respond(200, json={})
    with pytest.raises(BeneyluError, match="indisponible"):
        client.get_json("/api/family/init")
    assert client.get_json("/api/family/init") == {}
    assert login.call_count == 2
