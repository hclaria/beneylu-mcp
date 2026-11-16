from pathlib import Path

import pytest

from beneylu_mcp.config import ConfigError, load_settings


def test_env_wins_over_dotenv(tmp_path):
    (tmp_path / ".env").write_text("BENEYLU_USERNAME=fromfile\nBENEYLU_PASSWORD='pw file'\n# comment\n")
    s = load_settings({"BENEYLU_USERNAME": "fromenv", "HOME": str(tmp_path)}, tmp_path / ".env")
    assert s.username == "fromenv"
    assert s.password == "pw file"


def test_state_dir_precedence(tmp_path):
    base = {"BENEYLU_REFRESH_TOKEN": "t", "HOME": str(tmp_path)}
    assert load_settings(base, None).state_dir == tmp_path / ".local/state/beneylu-mcp"
    assert load_settings({**base, "XDG_STATE_HOME": "/x"}, None).state_dir == Path("/x/beneylu-mcp")
    assert (
        load_settings({**base, "XDG_STATE_HOME": "/x", "BENEYLU_STATE_DIR": "/y"}, None).state_dir == Path("/y")
    )


def test_missing_credentials_raises_in_french(tmp_path):
    with pytest.raises(ConfigError, match="BENEYLU_USERNAME"):
        load_settings({"HOME": str(tmp_path)}, None)


def test_refresh_token_alone_is_enough(tmp_path):
    assert load_settings({"BENEYLU_REFRESH_TOKEN": "t", "HOME": str(tmp_path)}, None).refresh_token == "t"


def test_missing_dotenv_file_is_fine(tmp_path):
    s = load_settings({"BENEYLU_REFRESH_TOKEN": "t", "HOME": str(tmp_path)}, tmp_path / "absent.env")
    assert s.username is None


def test_first_run_days_default_and_value(tmp_path):
    base = {"BENEYLU_REFRESH_TOKEN": "t", "HOME": str(tmp_path)}
    assert load_settings(base, None).first_run_days == 7
    assert load_settings({**base, "BENEYLU_FIRST_RUN_DAYS": "14"}, None).first_run_days == 14
    assert load_settings({**base, "BENEYLU_FIRST_RUN_DAYS": "0"}, None).first_run_days == 0


def test_first_run_days_is_capped_by_the_detection_window(tmp_path):
    base = {"BENEYLU_REFRESH_TOKEN": "t", "HOME": str(tmp_path)}
    assert load_settings({**base, "BENEYLU_FIRST_RUN_DAYS": "90"}, None).first_run_days == 30


def test_first_run_days_rejects_garbage(tmp_path):
    base = {"BENEYLU_REFRESH_TOKEN": "t", "HOME": str(tmp_path)}
    for value in ("abc", "-1", "7.5"):
        with pytest.raises(ConfigError, match="BENEYLU_FIRST_RUN_DAYS"):
            load_settings({**base, "BENEYLU_FIRST_RUN_DAYS": value}, None)
