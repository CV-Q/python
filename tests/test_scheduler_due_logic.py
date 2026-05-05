from datetime import datetime, timedelta

import map_poi_fetcher as mp


def main() -> None:
    task = {
        "name": "scheduled_task",
        "enabled": True,
        "schedule": {"type": "daily", "interval_days": 2},
    }
    config = {
        "schedule_interval_days": 1,
        "scheduler": {"enabled": True, "check_interval_minutes": 15},
    }

    now = datetime.now()
    logs_not_due = [
        {"task_name": "scheduled_task", "status": "success", "run_time": (now - timedelta(days=1)).isoformat(timespec="seconds")},
        {"task_name": "scheduled_task", "status": "failed", "run_time": now.isoformat(timespec="seconds")},
    ]
    logs_due = [
        {"task_name": "scheduled_task", "status": "success", "run_time": (now - timedelta(days=3)).isoformat(timespec="seconds")},
    ]

    assert mp.is_task_due(task, logs_not_due, config) is False
    assert mp.is_task_due(task, logs_due, config) is True
    print("scheduler due logic regression passed")


if __name__ == "__main__":
    main()