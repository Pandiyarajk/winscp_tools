"""
Scheduler tests: persistence, schedules, retries, claims, locking, history.

Author: Pandiyaraj Karuppasamy
Date: Oct-17-2026
Modified: Oct-18-2026
"""

import json
import os
import socket
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta

import pytest

from sftp_pilot.scheduler import (FileLock, ScheduledTask, TaskScheduler, TaskStatus, TaskType,
                                  pid_alive)


def make_task(task_id="abcd1234-0000", **kw):
    defaults = dict(task_type=TaskType.UPLOAD, source_path="a.txt", dest_path="/up/a.txt",
                    scheduled_time=datetime.now() - timedelta(seconds=1))
    defaults.update(kw)
    return ScheduledTask(task_id, **defaults)


def test_validation_rejects_incomplete_tasks():
    with pytest.raises(ValueError):
        make_task(source_path="")
    with pytest.raises(ValueError):
        make_task(dest_path="")
    with pytest.raises(ValueError):
        make_task(recurring=True, interval_minutes=0)
    with pytest.raises(ValueError):
        make_task(daily_time="25:00")
    with pytest.raises(ValueError):
        make_task(weekdays=[1])  # weekdays without a daily time
    make_task(task_type=TaskType.DELETE, dest_path="")  # delete needs no destination


def test_round_trip_through_file(tmp_path):
    path = tmp_path / "tasks.json"
    s = TaskScheduler(str(path))
    s.add_task(make_task(daily_time="02:30", weekdays=[0, 4]))
    task = TaskScheduler(str(path)).get_task("abcd1234-0000")
    assert task is not None and task.daily_time == "02:30" and task.weekdays == [0, 4]
    assert task.describe_schedule() == "02:30 Mon,Fri"
    assert not list(tmp_path.glob(".tasks-*")), "temporary file left behind"


def test_version_2_0_file_loads(tmp_path):
    path = tmp_path / "t.json"
    old = {"task_id": "old-task-1", "task_type": "upload", "source_path": "a", "dest_path": "/b",
           "scheduled_time": "2026-10-01T10:00:00", "recurring": True, "interval_minutes": 60,
           "status": "pending", "last_run": None, "next_run": "2026-10-01T10:00:00",
           "error_message": ""}
    path.write_text(json.dumps([old]), encoding="utf-8")
    task = TaskScheduler(str(path)).get_task("old-task-1")
    assert task.describe_schedule() == "every 60 min" and task.attempt == 0


def test_one_shot_success_and_failure(tmp_path):
    s = TaskScheduler(str(tmp_path / "t.json"))
    s.add_task(make_task("ok-task-1"))
    s.add_task(make_task("bad-task-1"))
    s.set_task_executor(lambda t: t.task_id.startswith("ok"))
    records = s.run_due_tasks()
    assert sorted(r["result"] for r in records) == ["failed", "ok"]
    assert s.get_task("ok-task-1").status == TaskStatus.COMPLETED
    bad = s.get_task("bad-task-1")
    assert bad.status == TaskStatus.FAILED and bad.error_message
    assert s.run_due_tasks() == []


def test_retries_back_off_then_fail(tmp_path):
    s = TaskScheduler(str(tmp_path / "t.json"), retries=2, retry_delay=60)
    s.add_task(make_task())

    def boom(_task):
        raise ConnectionError("network down")

    s.set_task_executor(boom)
    s.run_due_tasks()
    task = s.get_task("abcd1234-0000")
    first_gap = task.next_run - task.last_run
    assert task.status == TaskStatus.PENDING and task.attempt == 1
    assert first_gap == timedelta(seconds=60)
    assert task.describe_status() == "retrying (1 failed)"

    s.run_due_tasks(now=task.next_run)
    task = s.get_task("abcd1234-0000")
    assert task.attempt == 2 and task.next_run - task.last_run == timedelta(seconds=120)

    s.run_due_tasks(now=task.next_run)
    task = s.get_task("abcd1234-0000")
    assert task.status == TaskStatus.FAILED and "network down" in task.error_message
    assert [r["attempt"] for r in s.read_history()] == [3, 2, 1]


def test_retry_success_resets_attempts(tmp_path):
    s = TaskScheduler(str(tmp_path / "t.json"), retries=3, retry_delay=1)
    s.add_task(make_task())
    calls = []
    s.set_task_executor(lambda t: calls.append(1) or len(calls) > 1)
    s.run_due_tasks()
    task = s.get_task("abcd1234-0000")
    s.run_due_tasks(now=task.next_run)
    task = s.get_task("abcd1234-0000")
    assert task.status == TaskStatus.COMPLETED and task.attempt == 0 and task.error_message == ""


def test_recurring_task_survives_failure_without_retries(tmp_path):
    s = TaskScheduler(str(tmp_path / "t.json"))
    start = datetime.now() - timedelta(seconds=1)
    s.add_task(make_task(recurring=True, interval_minutes=10, scheduled_time=start))
    s.set_task_executor(lambda t: (_ for _ in ()).throw(ConnectionError("network down")))
    s.run_due_tasks()
    task = s.get_task("abcd1234-0000")
    assert task.status == TaskStatus.PENDING and "network down" in task.error_message
    assert task.next_run == start + timedelta(minutes=10)
    assert task.describe_status() == "pending (last run failed)"

    s.set_task_executor(lambda t: True)
    s.run_due_tasks(now=task.next_run)
    task = s.get_task("abcd1234-0000")
    assert task.error_message == "" and task.status == TaskStatus.PENDING


def test_interval_does_not_drift():
    start = datetime(2026, 10, 18, 9, 0)
    task = make_task(recurring=True, interval_minutes=15, scheduled_time=start)
    # a run that finished 7 minutes late keeps the 15-minute grid
    assert task.following_run(datetime(2026, 10, 18, 9, 22)) == datetime(2026, 10, 18, 9, 30)
    # a long outage skips missed slots instead of replaying them
    assert task.following_run(datetime(2026, 10, 18, 13, 1)) == datetime(2026, 10, 18, 13, 15)
    assert task.following_run(datetime(2026, 10, 18, 8, 0)) == start


def test_daily_and_weekday_schedule():
    task = make_task(daily_time="02:00")
    sat = datetime(2026, 10, 17, 12, 0)  # a Saturday
    assert task.following_run(sat) == datetime(2026, 10, 18, 2, 0)
    assert task.following_run(datetime(2026, 10, 18, 1, 59)) == datetime(2026, 10, 18, 2, 0)
    assert task.following_run(datetime(2026, 10, 18, 2, 0)) == datetime(2026, 10, 19, 2, 0)

    weekdays = make_task(daily_time="02:00", weekdays=[0, 1, 2, 3, 4])
    assert weekdays.following_run(sat) == datetime(2026, 10, 19, 2, 0)  # Monday
    assert weekdays.describe_schedule() == "02:00 Mon,Tue,Wed,Thu,Fri"


def test_interrupted_running_task_is_rescheduled(tmp_path):
    path = tmp_path / "t.json"
    data = make_task().to_dict()
    data["status"] = "running"
    data["claim"] = {"host": socket.gethostname().upper(),  # case differs on purpose
                     "pid": 2_000_000_000, "token": "x", "run": "y", "at": datetime.now().isoformat()}
    path.write_text(json.dumps([data]), encoding="utf-8")
    task = TaskScheduler(str(path)).get_task("abcd1234-0000")
    assert task.status == TaskStatus.PENDING
    assert "Interrupted" in task.error_message


def test_claim_by_a_live_process_is_respected(tmp_path):
    path = str(tmp_path / "t.json")
    a, b = TaskScheduler(path), TaskScheduler(path)
    a.add_task(make_task())
    seen_by_b = []

    def slow(task):
        seen_by_b.append(b.get_task(task.task_id).status)
        seen_by_b.append(len(b.run_due_tasks()))
        return True

    b.set_task_executor(lambda t: pytest.fail("b ran a task a had claimed"))
    a.set_task_executor(slow)
    a.run_due_tasks()
    assert seen_by_b == [TaskStatus.RUNNING, 0]
    assert a.get_task("abcd1234-0000").status == TaskStatus.COMPLETED


def test_task_removed_while_running_stays_removed(tmp_path):
    s = TaskScheduler(str(tmp_path / "t.json"))
    s.add_task(make_task())
    s.set_task_executor(lambda t: s.remove_task(t.task_id))
    s.run_due_tasks()
    assert s.get_all_tasks() == []
    assert s.read_history()[0]["result"] == "ok"


def test_unreadable_file_is_never_overwritten(tmp_path):
    path = tmp_path / "t.json"
    path.write_text("{not json", encoding="utf-8")
    s = TaskScheduler(str(path))
    with pytest.raises(RuntimeError):
        s.add_task(make_task())
    assert path.read_text(encoding="utf-8") == "{not json"


def test_unreadable_task_does_not_drop_the_rest(tmp_path):
    path = tmp_path / "t.json"
    good = make_task().to_dict()
    path.write_text(json.dumps([{"task_id": "x", "task_type": "nope"}, good]), encoding="utf-8")
    assert TaskScheduler(str(path)).get_task("abcd1234-0000") is not None


def test_find_task_never_matches_empty_or_ambiguous(tmp_path):
    s = TaskScheduler(str(tmp_path / "t.json"))
    s.add_task(make_task("abcd1111"))
    s.add_task(make_task("abcd2222"))
    assert s.find_task("") is None
    assert s.find_task("abcd") is None  # ambiguous
    assert s.find_task("abcd1").task_id == "abcd1111"


def test_history_filters_and_rotates(tmp_path, monkeypatch):
    import sftp_pilot.scheduler as mod
    s = TaskScheduler(str(tmp_path / "t.json"))
    s.set_task_executor(lambda t: True)
    for i in range(3):
        s.add_task(make_task(f"task-{i}-xx"))
    s.run_due_tasks()
    assert len(s.read_history()) == 3
    assert [r["task_id"] for r in s.read_history("task-1")] == ["task-1-xx"]
    monkeypatch.setattr(mod, "HISTORY_MAX_BYTES", 10)
    s.add_task(make_task("task-9-xx"))
    s.run_due_tasks()
    assert os.path.exists(s.history_file + ".1")
    assert [r["task_id"] for r in s.read_history()] == ["task-9-xx"]


def test_file_lock_blocks_another_process(tmp_path):
    lock_path = str(tmp_path / "x.lock")
    holder = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {os.getcwd()!r})
        from sftp_pilot.scheduler import FileLock
        with FileLock({lock_path!r}):
            print("held", flush=True)
            time.sleep(3)
    """)
    proc = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "held"
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            with FileLock(lock_path, timeout=0.5):
                pass
        assert time.monotonic() - started >= 0.5
        with FileLock(lock_path, timeout=10):  # free once the holder exits
            pass
    finally:
        proc.wait(10)


def test_pid_alive():
    assert pid_alive(os.getpid())
    assert not pid_alive(2_000_000_000)


def test_pid_alive_sees_a_live_child_and_a_dead_one():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert pid_alive(proc.pid)
    finally:
        proc.kill()
        proc.wait(10)
    assert not pid_alive(proc.pid)


def test_stop_is_prompt_and_thread_runs_tasks(tmp_path):
    s = TaskScheduler(str(tmp_path / "t.json"), check_interval=30)
    ran = []
    s.set_task_executor(lambda t: ran.append(t.task_id) or True)
    s.add_task(make_task())
    s.start()
    deadline = time.monotonic() + 5
    while not ran and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ran == ["abcd1234-0000"]
    started = time.monotonic()
    s.stop()
    assert time.monotonic() - started < 1.0, "stop() waited out the check interval"
    assert not s.running
