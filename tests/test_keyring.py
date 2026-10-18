"""
Keyring storage: opt-in per server, precedence, per-server entries, the CLI.
Uses an in-memory backend, so no real credential store is touched. One extra
test uses the real OS keyring when SFTP_PILOT_REAL_KEYRING=1.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import getpass
import os
import uuid

import pytest

keyring = pytest.importorskip("keyring")

from keyring.backend import KeyringBackend  # noqa: E402
from keyring.errors import PasswordDeleteError  # noqa: E402

from sftp_pilot import keystore  # noqa: E402
from sftp_pilot.cli import main  # noqa: E402
from sftp_pilot.config_manager import ConfigManager  # noqa: E402


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.items = {}
        self.reads = 0

    def get_password(self, service, username):
        self.reads += 1
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.items:
            raise PasswordDeleteError("not found")
        del self.items[(service, username)]


@pytest.fixture
def store():
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith("SFTP_PILOT_"):
            monkeypatch.delenv(name)


CONFIG = """\
[DEFAULT]
host = main.example
username = alice
password_store = keyring
password = file-password

[server:plain]
host = plain.example
username = bob
password = plain-password

[server:backup]
host = backup.example
port = 2222
username = carol
password_store = keyring
"""


def manager(tmp_path, text=CONFIG):
    path = tmp_path / "config.ini"
    path.write_text(text, encoding="utf-8")
    return ConfigManager(str(path)), str(path)


def test_entry_names_are_per_user_host_and_port():
    assert keystore.entry_name("password", "alice", "h", 22) == "alice@h:22"
    assert keystore.entry_name("passphrase", "alice", "h", 22) == "alice@h:22#passphrase"
    assert keystore.entry_name("password", "alice", "h", 2222) != keystore.entry_name("password", "alice", "h", 22)
    with pytest.raises(ValueError):
        keystore.entry_name("token", "a", "h", 22)


def test_keyring_beats_file_and_env_beats_keyring(tmp_path, store, monkeypatch):
    cfg, _ = manager(tmp_path)
    keystore.set_secret("password", "alice", "main.example", 22, "keyring-password")
    assert cfg.get_connection_details()["password"] == "keyring-password"
    monkeypatch.setenv("SFTP_PILOT_PASSWORD", "env-password")
    assert cfg.get_connection_details()["password"] == "env-password"


def test_each_server_reads_its_own_entry(tmp_path, store):
    cfg, _ = manager(tmp_path)
    keystore.set_secret("password", "alice", "main.example", 22, "main-secret")
    keystore.set_secret("password", "carol", "backup.example", 2222, "backup-secret")
    assert cfg.get_connection_details()["password"] == "main-secret"
    assert cfg.get_connection_details("backup")["password"] == "backup-secret"


def test_a_server_that_did_not_opt_in_never_touches_the_keyring(tmp_path, store):
    cfg, _ = manager(tmp_path)
    keystore.set_secret("password", "bob", "plain.example", 22, "stored-but-ignored")
    store.reads = 0
    assert cfg.get_connection_details("plain")["password"] == "plain-password"
    assert store.reads == 0, "the keyring was consulted for a server that did not ask"


def test_password_store_is_not_inherited(tmp_path, store):
    cfg, _ = manager(tmp_path, "[DEFAULT]\nhost = h\nusername = u\npassword_store = keyring\n"
                               "[server:other]\nhost = o\nusername = u\npassword = p\n")
    store.reads = 0
    assert cfg.get_connection_details("other")["password"] == "p"
    assert store.reads == 0


def test_missing_entry_is_a_clear_error_unless_a_key_is_configured(tmp_path, store):
    cfg, _ = manager(tmp_path)
    with pytest.raises(ValueError, match=r"no password is stored for carol@backup.example:2222.*--store-password --server backup"):
        cfg.get_connection_details("backup")
    with_key, _ = manager(tmp_path, CONFIG.replace("username = carol", "username = carol\nprivate_key_path = /k"))
    assert with_key.get_connection_details("backup")["password"] == ""  # key login needs no password


def test_passphrase_comes_from_the_keyring_too(tmp_path, store):
    cfg, _ = manager(tmp_path, CONFIG.replace("username = carol", "username = carol\nprivate_key_path = /k"))
    keystore.set_secret("passphrase", "carol", "backup.example", 2222, "phrase")
    assert cfg.get_connection_details("backup")["private_key_passphrase"] == "phrase"


def test_unknown_password_store_value_is_rejected(tmp_path, store):
    cfg, _ = manager(tmp_path, "[DEFAULT]\nhost = h\nusername = u\npassword_store = vault\n")
    with pytest.raises(ValueError, match="password_store"):
        cfg.get_connection_details()


def test_no_keyring_package_or_backend_is_reported_not_swallowed(tmp_path, monkeypatch):
    cfg, _ = manager(tmp_path)
    monkeypatch.setattr(keystore, "_backend", lambda: (_ for _ in ()).throw(
        keystore.KeyringUnavailable("The keyring package is not installed.")))
    with pytest.raises(ValueError, match="password_store = keyring, but The keyring package is not installed"):
        cfg.get_connection_details()


def test_a_broken_backend_is_not_mistaken_for_no_secret(tmp_path, store, monkeypatch):
    cfg, _ = manager(tmp_path)

    def locked(*_a):
        raise RuntimeError("keyring is locked")

    monkeypatch.setattr(store, "get_password", locked)
    with pytest.raises(ValueError, match="could not be read: keyring is locked"):
        cfg.get_connection_details()


def feed_secret(monkeypatch, *answers):
    queue = iter(answers)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(queue))


def test_cli_store_and_forget(tmp_path, store, monkeypatch, capsys):
    cfg, path = manager(tmp_path)
    feed_secret(monkeypatch, "s3cret", "s3cret")
    assert main(["-c", path, "--store-password", "--server", "backup"]) == 0
    out = capsys.readouterr().out
    assert "password_store = keyring" in out and "carol@backup.example:2222" in out
    assert "s3cret" not in out, "the secret was echoed"
    assert store.items == {("sftp-pilot", "carol@backup.example:2222"): "s3cret"}
    assert cfg.get_connection_details("backup")["password"] == "s3cret"

    feed_secret(monkeypatch, "phrase", "phrase")
    assert main(["-c", path, "--store-passphrase", "--server", "backup"]) == 0
    assert ("sftp-pilot", "carol@backup.example:2222#passphrase") in store.items

    assert main(["-c", path, "--forget-secrets", "--server", "backup"]) == 0
    assert "password, passphrase" in capsys.readouterr().out
    assert store.items == {}
    assert main(["-c", path, "--forget-secrets", "--server", "backup"]) == 0
    assert "nothing was stored" in capsys.readouterr().out


def test_cli_refuses_empty_or_mismatched_input(tmp_path, store, monkeypatch, capsys):
    _, path = manager(tmp_path)
    feed_secret(monkeypatch, "")
    assert main(["-c", path, "--store-password"]) == 1
    feed_secret(monkeypatch, "one", "two")
    assert main(["-c", path, "--store-password"]) == 1
    assert store.items == {}
    err = capsys.readouterr().err
    assert "nothing stored" in err


def test_cli_reports_a_bad_config_and_a_missing_keyring(tmp_path, monkeypatch, capsys):
    _, path = manager(tmp_path)
    assert main(["-c", path, "--store-password", "--server", "ghost"]) == 2
    assert "Unknown server 'ghost'" in capsys.readouterr().err
    monkeypatch.setattr(keystore, "_backend", lambda: (_ for _ in ()).throw(
        keystore.KeyringUnavailable("No usable keyring backend on this system")))

    def must_not_prompt(prompt=""):
        pytest.fail("asked for a secret although there is no keyring to store it in")

    monkeypatch.setattr(getpass, "getpass", must_not_prompt)
    assert main(["-c", path, "--store-password"]) == 2
    assert main(["-c", path, "--store-passphrase"]) == 2
    assert main(["-c", path, "--forget-secrets"]) == 2
    assert "No usable keyring backend" in capsys.readouterr().err


def test_run_due_fails_fast_on_a_missing_stored_password(tmp_path, store):
    _, path = manager(tmp_path)
    assert main(["-c", path, "--run-due"]) == 2


@pytest.mark.skipif(os.environ.get("SFTP_PILOT_REAL_KEYRING") != "1",
                    reason="set SFTP_PILOT_REAL_KEYRING=1 to use the real OS keyring")
def test_real_os_keyring_round_trip():
    user = f"sftp-pilot-test-{uuid.uuid4().hex[:8]}"
    keystore_backend = keyring.get_keyring()
    assert "Memory" not in type(keystore_backend).__name__
    try:
        keystore.set_secret("password", user, "example.invalid", 22, "pässword with spaces")
        assert keystore.get_secret("password", user, "example.invalid", 22) == "pässword with spaces"
        assert keystore.get_secret("passphrase", user, "example.invalid", 22) is None
    finally:
        assert keystore.delete_secret("password", user, "example.invalid", 22)
    assert keystore.get_secret("password", user, "example.invalid", 22) is None
    assert not keystore.delete_secret("password", user, "example.invalid", 22)
