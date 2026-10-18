"""
Configuration tests.

Author: Pandiyaraj Karuppasamy
Date: Oct-17-2026
Modified: Oct-18-2026
"""

from pathlib import Path

import pytest

from sftp_pilot.config_manager import PASSWORD_ENV, ConfigManager
from sftp_pilot.cli import main


def write(tmp_path, body):
    path = tmp_path / "config.ini"
    path.write_text(body, encoding="utf-8")
    return str(path)


BASE = "[DEFAULT]\nhost = h\nusername = u\npassword = from-file\n"


def test_env_password_overrides_file(tmp_path, monkeypatch):
    cfg = ConfigManager(write(tmp_path, BASE))
    assert cfg.get_connection_details()["password"] == "from-file"
    monkeypatch.setenv(PASSWORD_ENV, "from-env")
    assert cfg.get_connection_details()["password"] == "from-env"


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    conn = ConfigManager(write(tmp_path, BASE)).get_connection_details()
    assert conn["port"] == 22 and conn["host_key_policy"] == "accept_new"


@pytest.mark.parametrize("line", ["protocol = scp", "host_key_policy = yolo"])
def test_unsupported_values_are_rejected(tmp_path, line):
    with pytest.raises(ValueError):
        ConfigManager(write(tmp_path, BASE + line + "\n")).get_connection_details()


def test_example_config_parses():
    example = Path(__file__).resolve().parent.parent / "sftp_pilot" / "example_config.ini"
    manager = ConfigManager(str(example))
    manager.get_connection_details()
    assert manager.server_names() == ["default"]  # the [server:backup] example stays commented out


def test_init_config_writes_once(tmp_path):
    target = tmp_path / "config.ini"
    assert main(["--init-config", "-c", str(target)]) == 0
    ConfigManager(str(target)).get_connection_details()
    target.write_text("mine", encoding="utf-8")
    assert main(["--init-config", "-c", str(target)]) == 1
    assert target.read_text(encoding="utf-8") == "mine"


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "SFTP Pilot" in capsys.readouterr().out
