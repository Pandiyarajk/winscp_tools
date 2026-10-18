"""
Command-line tests: --run-due as an external scheduler runs it (a separate
process, started in an unrelated working directory), --history, path handling.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("asyncssh")

from sftp_server import PASSWORD, USER, SFTPServer  # noqa: E402

from sftp_pilot.config_manager import ConfigManager  # noqa: E402
from sftp_pilot.console import _parse_days  # noqa: E402
from sftp_pilot.scheduler import ScheduledTask, TaskScheduler, TaskType  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def run_cli(args, cwd):
    env = dict(os.environ, PYTHONPATH=str(REPO))
    return subprocess.run([sys.executable, "-m", "sftp_pilot", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.fixture
def setup(tmp_path):
    remote = tmp_path / "remote"
    remote.mkdir()
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"  # stands in for System32 / the home folder
    elsewhere.mkdir()
    with SFTPServer(remote) as server:
        cfg = cfg_dir / "config.ini"
        cfg.write_text(
            f"[DEFAULT]\nhost = 127.0.0.1\nport = {server.port}\nusername = {USER}\n"
            f"password = {PASSWORD}\nknown_hosts_file = known_hosts\ntimeout = 10\n"
            f"[SCHEDULING]\nretries = 0\n[LOGGING]\nlog_file = run.log\n", encoding="utf-8")
        yield cfg, cfg_dir, remote, elsewhere


def add(cfg_dir, task_id, task_type, source, dest=""):
    sched = TaskScheduler(str(cfg_dir / "scheduled_tasks.json"))
    sched.add_task(ScheduledTask(task_id, task_type, source, dest,
                                 scheduled_time=datetime.now() - timedelta(seconds=1)))


def test_run_due_from_another_directory(setup, tmp_path):
    cfg, cfg_dir, remote, elsewhere = setup
    src = tmp_path / "nightly.csv"
    src.write_text("data")
    add(cfg_dir, "task-ok-1", TaskType.UPLOAD, str(src), "/in/")

    result = run_cli(["-c", str(cfg), "--run-due"], cwd=elsewhere)
    assert result.returncode == 0, result.stderr
    assert (remote / "in" / "nightly.csv").read_text() == "data"
    # every relative path landed beside the config, nothing in the working dir
    assert {"known_hosts", "run.log", "scheduled_tasks.json"} <= {p.name for p in cfg_dir.iterdir()}
    assert list(elsewhere.iterdir()) == []

    history = [json.loads(line) for line in
               (cfg_dir / "scheduled_tasks.history.jsonl").read_text().splitlines()]
    assert history[-1]["runner"] == "run-due" and history[-1]["result"] == "ok"

    again = run_cli(["-c", str(cfg), "--run-due"], cwd=elsewhere)
    assert again.returncode == 0  # nothing due


def test_two_processes_run_a_task_once(setup, tmp_path):
    cfg, cfg_dir, remote, elsewhere = setup
    src = tmp_path / "big.bin"
    src.write_bytes(os.urandom(3_000_000))
    for i in range(3):
        add(cfg_dir, f"task-race-{i}", TaskType.UPLOAD, str(src), f"/race/{i}.bin")

    env = dict(os.environ, PYTHONPATH=str(REPO))
    procs = [subprocess.Popen([sys.executable, "-m", "sftp_pilot", "-c", str(cfg), "--run-due"],
                              cwd=elsewhere, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True) for _ in range(2)]
    outputs = [p.communicate(timeout=120)[0] for p in procs]
    codes = [p.returncode for p in procs]
    assert codes == [0, 0], "\n---\n".join(outputs)

    history = [json.loads(line) for line in
               (cfg_dir / "scheduled_tasks.history.jsonl").read_text().splitlines()]
    assert sorted(r["task_id"] for r in history) == [f"task-race-{i}" for i in range(3)]
    assert sorted(p.name for p in (remote / "race").iterdir()) == ["0.bin", "1.bin", "2.bin"]


def test_run_due_reports_failure(setup):
    cfg, cfg_dir, _remote, elsewhere = setup
    add(cfg_dir, "task-bad-1", TaskType.DELETE, "/no/such/file")
    result = run_cli(["-c", str(cfg), "--run-due"], cwd=elsewhere)
    assert result.returncode == 1
    shown = run_cli(["-c", str(cfg), "--history"], cwd=elsewhere)
    assert shown.returncode == 0 and "failed" in shown.stdout and "delete failed" in shown.stdout


def test_run_due_config_error(tmp_path):
    bad = tmp_path / "config.ini"
    bad.write_text("[DEFAULT]\nhost = h\nusername = u\nprotocol = ftp\n", encoding="utf-8")
    assert run_cli(["-c", str(bad), "--run-due"], cwd=tmp_path).returncode == 2
    assert run_cli(["-c", str(tmp_path / "missing.ini"), "--run-due"], cwd=tmp_path).returncode == 2


def test_run_due_disabled_runs_nothing(setup):
    cfg, cfg_dir, _remote, elsewhere = setup
    cfg.write_text(cfg.read_text().replace("retries = 0", "retries = 0\nenabled = false"))
    add(cfg_dir, "task-x-1", TaskType.DELETE, "/whatever")
    assert run_cli(["-c", str(cfg), "--run-due"], cwd=elsewhere).returncode == 0
    assert TaskScheduler(str(cfg_dir / "scheduled_tasks.json")).get_task("task-x-1").last_run is None


def test_config_paths_resolve_against_config_folder(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[DEFAULT]\nhost = h\nusername = u\nknown_hosts_file = kh\n"
                   "[LOGGING]\nlog_file =\n", encoding="utf-8")
    manager = ConfigManager(str(cfg))
    assert manager.get_connection_details()["known_hosts_file"] == str(tmp_path / "kh")
    assert manager.get_logging_config()["log_file"] == ""


def test_ctrl_c_cancels_instead_of_interrupting():
    import signal
    from sftp_pilot.console import _ctrl_c_cancels
    before = signal.getsignal(signal.SIGINT)
    with _ctrl_c_cancels() as cancel:
        signal.raise_signal(signal.SIGINT)  # no KeyboardInterrupt
        assert cancel.is_set()
    assert signal.getsignal(signal.SIGINT) is before


def test_parse_days():
    assert _parse_days("") == []
    assert _parse_days("0-4") == [0, 1, 2, 3, 4]
    assert _parse_days("6, 0,2") == [0, 2, 6]
    with pytest.raises(ValueError):
        _parse_days("7")
    with pytest.raises(ValueError):
        _parse_days("mon")
