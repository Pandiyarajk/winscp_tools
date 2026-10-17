"""
Scheduler tests: persistence, recurrence, failure handling and stop latency.

Author: Pandiyaraj Karuppasamy
Date: Oct-17-2026
Modified: Oct-18-2026
"""

import json
import time
from datetime import datetime, timedelta

import pytest

from sftp_pilot.scheduler import ScheduledTask, TaskScheduler, TaskStatus, TaskType


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
    make_task(task_type=TaskType.DELETE, dest_path="")  # delete needs no destination


def test_round_trip_through_file(tmp_path):
    path = tmp_path / "tasks.json"
    s = TaskScheduler(str(path))
    s.add_task(make_task(recurring=True, interval_minutes=5))
    again = TaskScheduler(str(path))
    task = again.get_task("abcd1234-0000")
    assert task is not None and task.recurring and task.interval_minutes == 5
    assert not list(tmp_path.glob(".tasks-*")), "temporary file left behind"


def test_one_shot_success_and_failure(tmp_path):
    s = TaskScheduler(str(tmp_path / "t.json"))
    s.add_task(make_task("ok-task-1"))
    s.add_task(make_task("bad-task-1"))
    s.set_task_executor(lambda t: t.task_id.startswith("ok"))
    assert s.run_due_tasks() == 2
    assert s.get_task("ok-task-1").status == TaskStatus.COMPLETED
    bad = s.get_task("bad-task-1")
    assert bad.status == TaskStatus.FAILED and bad.error_message


def test_recurring_task_survives_failure(tmp_path):
    s = TaskScheduler(str(tmp_path / "t.json"))
    s.add_task(make_task(recurring=True, interval_minutes=10))

    def boom(_task):
        raise ConnectionError("network down")

    s.set_task_executor(boom)
    before = datetime.now()
    s.run_due_tasks()
    task = s.get_task("abcd1234-0000")
    assert task.status == TaskStatus.PENDING
    assert "network down" in task.error_message
    assert task.next_run >= before + timedelta(minutes=10)
    assert task.describe_status() == "pending (last run failed)"

    s.set_task_executor(lambda t: True)
    s.run_due_tasks(now=task.next_run)
    assert task.error_message == "" and task.status == TaskStatus.PENDING


def test_interrupted_running_task_is_rescheduled(tmp_path):
    path = tmp_path / "t.json"
    data = make_task().to_dict()
    data["status"] = "running"
    path.write_text(json.dumps([data]), encoding="utf-8")
    task = TaskScheduler(str(path)).get_task("abcd1234-0000")
    assert task.status == TaskStatus.PENDING
    assert "Interrupted" in task.error_message


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
