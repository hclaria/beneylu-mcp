import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    username: str | None
    password: str | None
    refresh_token: str | None
    state_dir: Path
    base_url: str = "https://school.beneylu.com"


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _state_dir(env: Mapping[str, str]) -> Path:
    if env.get("BENEYLU_STATE_DIR"):
        return Path(env["BENEYLU_STATE_DIR"])
    if env.get("XDG_STATE_HOME"):
        return Path(env["XDG_STATE_HOME"]) / "beneylu-mcp"
    return Path(env.get("HOME") or Path.home()) / ".local" / "state" / "beneylu-mcp"


def load_settings(environ: Mapping[str, str] | None = None, dotenv: Path | None = Path(".env")) -> Settings:
    env = {**(_read_dotenv(dotenv) if dotenv else {}), **(os.environ if environ is None else environ)}
    username = env.get("BENEYLU_USERNAME") or None
    password = env.get("BENEYLU_PASSWORD") or None
    refresh_token = env.get("BENEYLU_REFRESH_TOKEN") or None
    if not (username and password) and not refresh_token:
        raise ConfigError(
            "Identifiants Beneylu manquants : définir BENEYLU_USERNAME et BENEYLU_PASSWORD "
            "(ou BENEYLU_REFRESH_TOKEN)."
        )
    return Settings(username, password, refresh_token, _state_dir(env))
