import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from .config import Settings
from .state import StateStore

LOGIN_PATH = "/api/auth/login_check"
REFRESH_PATH = "/api/auth/token/refresh"
ALLOWED_POST_PATHS = frozenset({LOGIN_PATH, REFRESH_PATH, "/api/auth/users/lookup"})
LOGIN_INTERVAL = timedelta(hours=1)
TOKEN_REJECTED = frozenset({400, 401, 403})


class BeneyluError(Exception):
    pass


class BeneyluAuthError(BeneyluError):
    pass


class BeneyluClient:
    def __init__(
        self,
        settings: Settings,
        state: StateStore,
        http: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.settings = settings
        self.state = state
        self._http = http or httpx.Client(
            base_url=settings.base_url,
            timeout=20,
            follow_redirects=False,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self._now = now or (lambda: datetime.now().astimezone())
        self._lock = threading.RLock()

    def get_json(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post_json(self, path: str, body: dict) -> Any:
        if path not in ALLOWED_POST_PATHS:
            raise BeneyluError(f"Appel refusé : ce serveur MCP est en lecture seule ({path}).")
        return self._request("POST", path, json=body)

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        with self._lock:
            if "BEARER" not in self._http.cookies:
                self._open_session()
            response = self._send(method, path, **kwargs)
            if response.status_code == 401:
                self._http.cookies.clear()
                self._open_session()
                response = self._send(method, path, **kwargs)
            return self._decode(path, response)

    def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise BeneyluError(f"Beneylu injoignable ({type(exc).__name__}).") from None

    @staticmethod
    def _decode(path: str, response: httpx.Response) -> Any:
        if response.status_code == 401:
            raise BeneyluAuthError("Beneylu refuse la session même après reconnexion.")
        if response.status_code >= 400:
            raise BeneyluError(f"Beneylu a répondu {response.status_code} sur {path}.")
        try:
            return response.json()
        except ValueError:
            raise BeneyluError(f"Beneylu a renvoyé une réponse inattendue (pas du JSON) sur {path}.") from None

    def _open_session(self) -> None:
        tokens = [t for t in (self.state.get("refresh_token"), self.settings.refresh_token) if t]
        for token in dict.fromkeys(tokens):
            if self._refresh(token):
                return
        self.state.delete("refresh_token")
        if not (self.settings.username and self.settings.password):
            raise BeneyluAuthError(
                "Session Beneylu expirée et aucun identifiant configuré : définir BENEYLU_USERNAME et "
                "BENEYLU_PASSWORD, ou fournir un nouveau BENEYLU_REFRESH_TOKEN."
            )
        self._login()

    def _refresh(self, token: str) -> bool:
        response = self._send("POST", REFRESH_PATH, json={"refresh_token": token})
        if response.status_code in TOKEN_REJECTED:
            return False
        if response.status_code != 200:
            raise _unavailable(response)
        if "BEARER" not in self._http.cookies:
            return False
        self._store_refresh_token(response, fallback=token)
        return True

    def _login(self) -> None:
        now = self._now()
        last = self.state.get("last_login_attempt")
        if last and now - datetime.fromisoformat(last) < LOGIN_INTERVAL:
            retry_at = (datetime.fromisoformat(last) + LOGIN_INTERVAL).astimezone(now.tzinfo)
            raise BeneyluAuthError(
                "Dernière tentative de connexion à Beneylu il y a moins d'une heure ; "
                f"nouvel essai possible après {retry_at:%H:%M}."
            )
        self.state.set("last_login_attempt", now.isoformat())
        body = {
            "login": self.settings.username,
            "password": self.settings.password,
            "otp": "",
            "remember_me": True,
            "captcha": "",
        }
        try:
            response = self._send("POST", LOGIN_PATH, json=body)
            if response.status_code not in TOKEN_REJECTED and response.status_code != 200:
                raise _unavailable(response)
        except BeneyluError:
            # Beneylu never judged the credentials: the hourly attempt is not spent.
            if last:
                self.state.set("last_login_attempt", last)
            else:
                self.state.delete("last_login_attempt")
            raise
        if response.status_code == 200 and "BEARER" in self._http.cookies:
            self._store_refresh_token(response, fallback=None)
            return
        if "X-Bns-Captcha" in response.headers:
            raise BeneyluAuthError(
                "Beneylu demande un captcha pour se connecter. Se connecter une fois sur school.beneylu.com "
                "dans le navigateur, ou fournir BENEYLU_REFRESH_TOKEN, puis réessayer dans une heure."
            )
        message = _json_message(response)
        if message in ("otp_needed", "otp_failed"):
            raise BeneyluAuthError(
                "Le compte Beneylu demande une double authentification : le serveur MCP ne peut pas se connecter seul."
            )
        raise BeneyluAuthError(f"Beneylu a refusé les identifiants (réponse {response.status_code}).")

    def _store_refresh_token(self, response: httpx.Response, fallback: str | None) -> None:
        try:
            token = response.json().get("refresh_token")
        except (ValueError, AttributeError):
            token = None
        if token or fallback:
            self.state.set("refresh_token", token or fallback)


def _unavailable(response: httpx.Response) -> BeneyluError:
    return BeneyluError(f"Beneylu est indisponible (réponse {response.status_code}), réessayer plus tard.")


def _json_message(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("message") if isinstance(body, dict) else None
