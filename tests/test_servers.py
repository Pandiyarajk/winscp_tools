"""
Several servers: config isolation, environment variables, tasks that pick
their server, --run-due across servers, the console chooser.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import builtins
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sftp_pilot.config_manager import ConfigManager, env_suffix
from sftp_pilot.console import ConsoleInterface
from sftp_pilot.runner import make_task_executor
from sftp_pilot.scheduler import ScheduledTask, TaskScheduler, TaskStatus, TaskType

REPO = Path(__file__).resolve().parent.parent

TWO_SERVERS = """\
[DEFAULT]
host = main.example
username = alice
password = main-secret
host_key_policy = reject
timeout = 12

[server:backup]
host = backup.example
port = 2222
username = bob
password = backup-secret

[server:no-secret]
host = bare.example
username = carol
"""


def manager(tmp_path, text=TWO_SERVERS):
    path = tmp_path / "config.ini"
    path.write_text(text, encoding="utf-8")
    return ConfigManager(str(path))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith("SFTP_PILOT_"):
            monkeypatch.delenv(name)


def test_server_names_and_details(tmp_path):
    cfg = manager(tmp_path)
    assert cfg.server_names() == ["default", "backup", "no-secret"]
    default = cfg.get_connection_details()
    assert (default["server"], default["host"], default["port"], default["username"]) == \
        ("default", "main.example", 22, "alice")
    backup = cfg.get_connection_details("backup")
    assert (backup["server"], backup["host"], backup["port"], backup["username"], backup["password"]) == \
        ("backup", "backup.example", 2222, "bob", "backup-secret")
    assert cfg.get_connection_details("default")["host"] == "main.example"


def test_a_named_server_never_inherits_credentials(tmp_path):
    cfg = manager(tmp_path)
    bare = cfg.get_connection_details("no-secret")
    assert bare["host"] == "bare.example" and bare["username"] == "carol"
    assert bare["password"] == "", "the default server's password leaked into another server"
    assert bare["private_key_path"] == "" and bare["private_key_passphrase"] == ""


def test_non_secret_settings_are_shared(tmp_path):
    cfg = manager(tmp_path)
    for name in ("backup", "no-secret"):
        details = cfg.get_connection_details(name)
        assert details["host_key_policy"] == "reject" and details["timeout"] == 12.0


@pytest.mark.parametrize("missing, section", [
    ("host", "[server:x]\nusername = carol\n"),
    ("username", "[server:x]\nhost = bare.example\n"),
])
def test_a_server_must_state_its_own_address_and_user(tmp_path, missing, section):
    # [DEFAULT] has both, and still does not fill the gap in [server:x]
    default_only = TWO_SERVERS.split("[server:backup]")[0]
    with pytest.raises(ValueError, match=f"needs '{missing}'"):
        manager(tmp_path, default_only + section).get_connection_details("x")


def test_environment_secrets_are_per_server(tmp_path, monkeypatch):
    cfg = manager(tmp_path)
    monkeypatch.setenv("SFTP_PILOT_PASSWORD", "env-for-default")
    monkeypatch.setenv("SFTP_PILOT_PASSWORD_BACKUP", "env-for-backup")
    assert cfg.get_connection_details()["password"] == "env-for-default"
    assert cfg.get_connection_details("backup")["password"] == "env-for-backup"
    # the default server's variable is never offered to another server
    assert cfg.get_connection_details("no-secret")["password"] == ""
    monkeypatch.setenv("SFTP_PILOT_KEY_PASSPHRASE_NO_SECRET", "phrase")
    assert cfg.get_connection_details("no-secret")["private_key_passphrase"] == "phrase"
    assert cfg.get_connection_details("backup")["private_key_passphrase"] == ""


def test_env_suffix():
    assert env_suffix("") == "" and env_suffix("default") == ""
    assert env_suffix("backup") == "_BACKUP"
    assert env_suffix("my-server.2") == "_MY_SERVER_2"


def test_unknown_server_and_missing_default_are_clear(tmp_path):
    cfg = manager(tmp_path)
    with pytest.raises(ValueError, match="Unknown server 'nope'.*default, backup, no-secret"):
        cfg.get_connection_details("nope")
    only_named = manager(tmp_path, "[server:a]\nhost = a\nusername = u\n[server:b]\nhost = b\nusername = u\n")
    assert only_named.server_names() == ["a", "b"]
    with pytest.raises(ValueError, match="no default server.*a, b"):
        only_named.get_connection_details()
    assert only_named.get_connection_details("b")["host"] == "b"
    with pytest.raises(ValueError, match="no server"):
        manager(tmp_path, "[PATHS]\nremote_upload_dir = /\n").get_connection_details()


def test_server_default_is_reserved(tmp_path):
    with pytest.raises(ValueError, match="not allowed"):
        manager(tmp_path, TWO_SERVERS + "\n[server:default]\nhost = x\nusername = y\n")


def test_single_server_config_is_unchanged(tmp_path):
    cfg = manager(tmp_path, "[DEFAULT]\nhost = h\nusername = u\npassword = p\n[PATHS]\nremote_upload_dir = /up\n")
    assert cfg.server_names() == ["default"]
    assert cfg.get_connection_details()["password"] == "p"
    assert cfg.get_paths()["remote_upload_dir"] == "/up"


def test_other_sections_do_not_inherit_from_default(tmp_path):
    cfg = manager(tmp_path, "[DEFAULT]\nhost = h\nusername = u\nretries = 9\n[SCHEDULING]\nenabled = true\n")
    assert cfg.get_scheduling_config()["retries"] == 3  # the built-in default, not [DEFAULT]'s


def test_task_server_field_round_trips_and_old_files_load(tmp_path):
    path = tmp_path / "t.json"
    s = TaskScheduler(str(path))
    s.add_task(ScheduledTask("srv-task-1", TaskType.DELETE, "/x", server="backup"))
    assert TaskScheduler(str(path)).get_task("srv-task-1").server == "backup"
    assert ScheduledTask("srv-task-2", TaskType.DELETE, "/x").server_label == "default"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data[0]["server"]
    path.write_text(json.dumps(data), encoding="utf-8")
    old = TaskScheduler(str(path)).get_task("srv-task-1")
    assert old.server == "" and old.server_label == "default"


def two_server_config(tmp_path, a, b):
    path = tmp_path / "config.ini"
    path.write_text(
        f"[DEFAULT]\nhost = 127.0.0.1\nport = {a.port}\nusername = tester\npassword = s3cret\n"
        f"known_hosts_file = known_hosts\ntimeout = 10\n[SCHEDULING]\nretries = 0\n"
        f"[LOGGING]\nlog_file = run.log\n"
        f"[server:other]\nhost = 127.0.0.1\nport = {b.port}\nusername = tester\npassword = s3cret\n",
        encoding="utf-8")
    return path


def test_tasks_run_against_their_own_server(tmp_path, remote, remote_b):
    cfg = ConfigManager(str(two_server_config(tmp_path, remote, remote_b)))
    src = tmp_path / "f.txt"
    src.write_text("payload")
    sched = TaskScheduler(str(tmp_path / "tasks.json"))
    sched.set_task_executor(make_task_executor(cfg.get_connection_details))
    past = datetime.now() - timedelta(seconds=1)
    sched.add_task(ScheduledTask("to-default-1", TaskType.UPLOAD, str(src), "/d/", past))
    sched.add_task(ScheduledTask("to-other-01", TaskType.UPLOAD, str(src), "/o/", past, server="other"))
    sched.add_task(ScheduledTask("to-nowhere-1", TaskType.UPLOAD, str(src), "/n/", past, server="ghost"))
    records = {r["task_id"]: r for r in sched.run_due_tasks()}

    assert (tmp_path / "remote/d/f.txt").read_text() == "payload"
    assert (tmp_path / "remote_b/o/f.txt").read_text() == "payload"
    assert not (tmp_path / "remote/o").exists() and not (tmp_path / "remote_b/d").exists()
    assert records["to-default-1"]["server"] == "default" and records["to-other-01"]["server"] == "other"
    assert records["to-nowhere-1"]["result"] == "failed"
    assert "Unknown server 'ghost'" in records["to-nowhere-1"]["error"]
    assert sched.get_task("to-nowhere-1").status == TaskStatus.FAILED


def run_cli(args, cwd):
    env = dict(os.environ, PYTHONPATH=str(REPO))
    return subprocess.run([sys.executable, "-m", "sftp_pilot", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


def test_run_due_uses_each_tasks_server(tmp_path, remote, remote_b):
    cfg = two_server_config(tmp_path, remote, remote_b)
    src = tmp_path / "f.txt"
    src.write_text("x")
    sched = TaskScheduler(str(tmp_path / "scheduled_tasks.json"))
    past = datetime.now() - timedelta(seconds=1)
    sched.add_task(ScheduledTask("run-def-001", TaskType.UPLOAD, str(src), "/in/", past))
    sched.add_task(ScheduledTask("run-oth-001", TaskType.UPLOAD, str(src), "/in/", past, server="other"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = run_cli(["-c", str(cfg), "--run-due"], cwd=elsewhere)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "remote/in/f.txt").exists() and (tmp_path / "remote_b/in/f.txt").exists()
    shown = run_cli(["-c", str(cfg), "--history"], cwd=elsewhere).stdout
    assert "other" in shown and "default" in shown


def test_run_due_refuses_a_broken_server_section(tmp_path, remote, remote_b):
    cfg = two_server_config(tmp_path, remote, remote_b)
    cfg.write_text(cfg.read_text() + "[server:broken]\nhost = x\n", encoding="utf-8")  # no username
    result = run_cli(["-c", str(cfg), "--run-due"], cwd=tmp_path)
    assert result.returncode == 2
    assert "needs 'username'" in result.stdout + result.stderr


@pytest.mark.parametrize("answers, expected", [
    (["1"], ""), (["2"], "backup"), (["backup"], "backup"), ([""], ""),
    (["3"], "no-secret"), (["9"], None), (["ghost"], None),
])
def test_console_server_chooser(tmp_path, monkeypatch, answers, expected, capsys):
    path = tmp_path / "config.ini"
    path.write_text(TWO_SERVERS, encoding="utf-8")
    console = ConsoleInterface(str(path), str(tmp_path / "tasks.json"))
    console.config_manager = ConfigManager(str(path))
    feed = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(feed))
    assert console._choose_server() == expected
    assert "backup" in capsys.readouterr().out


def test_console_chooser_skips_the_question_with_one_server(tmp_path, monkeypatch):
    path = tmp_path / "config.ini"
    path.write_text("[DEFAULT]\nhost = h\nusername = u\n", encoding="utf-8")
    console = ConsoleInterface(str(path), str(tmp_path / "tasks.json"))
    console.config_manager = ConfigManager(str(path))
    monkeypatch.setattr(builtins, "input", lambda prompt="": pytest.fail("asked with one server"))
    assert console._choose_server() == ""
    only_named = tmp_path / "named.ini"
    only_named.write_text("[server:solo]\nhost = h\nusername = u\n", encoding="utf-8")
    console.config_manager = ConfigManager(str(only_named))
    assert console._choose_server() == "solo"
