from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from playtomic_core import build_club_runs, should_send_notifications_now
from playtomic_monitor import run_monitor


CONFIG = '''
[watch]
look_ahead_days = 1
state_path = "state.json"

[[watch_windows]]
days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
start = "17:00"
end = "21:00"

[[notification_windows]]
days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
start = "08:00"
end = "22:00"

[notifications]
notify_when_no_new_slots = true

[[clubs]]
url = "https://playtomic.com/clubs/example"
tenant_id = "tenant-1"
name = "Example Club"
timezone = "Europe/Warsaw"
slug = "example"

[[clubs.resources]]
resource_id = "court-1"
name = "Court 1"
'''

SECOND_CLUB = '''
[[clubs]]
url = "https://playtomic.com/clubs/second"
tenant_id = "tenant-2"
name = "Second Club"
timezone = "UTC"
slug = "second"

[[clubs.resources]]
resource_id = "court-2"
name = "Court 2"
'''


@contextmanager
def at_warsaw_time(time_text: str):
    moment = datetime.fromisoformat(f"2026-10-08T{time_text}").replace(tzinfo=ZoneInfo("Europe/Warsaw"))
    with patch("playtomic_core.datetime", wraps=datetime) as clock:
        clock.now.side_effect = lambda timezone: moment.astimezone(timezone)
        yield


class QuietHoursMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config_path = Path(directory.name) / "config.toml"
        self.config_path.write_text(CONFIG)
        self.state_path = Path(directory.name) / "state.json"
        self.known_slot = "court-1|2026-10-08T19:00:00+02:00|90"
        self.state_path.write_text(json.dumps({"known_slots": [self.known_slot]}))
        self.original_state = self.state_path.read_bytes()
        self.output = io.StringIO()

    def run_monitor(self, *, dry_run: bool = False, test_notification: str | None = None) -> int:
        with redirect_stdout(self.output):
            return run_monitor(self.config_path, dry_run=dry_run, test_notification=test_notification)

    def test_quiet_check_makes_no_requests_or_notifications_and_leaves_state_untouched(self) -> None:
        with (
            at_warsaw_time("23:00:00"),
            patch("playtomic_core.http_get_json") as fetch,
            patch("playtomic_core.http_get_text") as fetch_page,
            patch("playtomic_monitor.send_notifications") as notify,
            patch("playtomic_monitor.save_state_payload") as save,
        ):
            self.assertEqual(self.run_monitor(), 0)

        fetch.assert_not_called()
        fetch_page.assert_not_called()
        notify.assert_not_called()
        save.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), self.original_state)
        self.assertIn("Skipping Example Club: outside notification hours.", self.output.getvalue())
        self.assertNotIn("No matching", self.output.getvalue())

    def test_first_morning_check_fetches_and_only_alerts_about_unseen_slots(self) -> None:
        with at_warsaw_time("02:00:00"):
            self.run_monitor()

        payload = [{
            "resource_id": "court-1",
            "start_date": "2026-10-08",
            "slots": [
                {"start_time": "16:00:00", "duration": 90},
                {"start_time": "17:00:00", "duration": 90},
            ],
        }]
        with (
            at_warsaw_time("08:00:00"),
            patch("playtomic_core.http_get_json", return_value=payload) as fetch,
            patch("playtomic_monitor.send_notifications") as notify,
        ):
            self.assertEqual(self.run_monitor(), 0)

        fetch.assert_called_once()
        notify.assert_called_once()
        message = notify.call_args.args[1]
        self.assertIn("18:00-19:30", message)
        self.assertNotIn("19:00-20:30", message)
        self.assertEqual(
            set(json.loads(self.state_path.read_text())["known_slots"]),
            {self.known_slot, "court-1|2026-10-08T18:00:00+02:00|90"},
        )

    def test_mixed_timezones_only_fetch_active_club_and_preserve_quiet_club_state(self) -> None:
        self.config_path.write_text(CONFIG + SECOND_CLUB)
        self.state_path.write_text(json.dumps({"known_slots": [self.known_slot, "court-2|old|90"]}))
        with (
            at_warsaw_time("23:00:00"),
            patch("playtomic_core.http_get_json", return_value=[]) as fetch,
            patch("playtomic_monitor.send_notifications") as notify,
        ):
            self.assertEqual(self.run_monitor(), 0)

        fetch.assert_called_once()
        self.assertIn("tenant_id=tenant-2", fetch.call_args.args[0])
        notify.assert_called_once()
        self.assertNotIn("Example Club", notify.call_args.args[1])
        self.assertEqual(json.loads(self.state_path.read_text()), {"known_slots": [self.known_slot]})

    def test_dry_run_still_fetches_during_quiet_hours_without_side_effects(self) -> None:
        with (
            at_warsaw_time("02:00:00"),
            patch("playtomic_core.http_get_json", return_value=[]) as fetch,
            patch("playtomic_monitor.send_notifications") as notify,
        ):
            self.assertEqual(self.run_monitor(dry_run=True), 0)

        fetch.assert_called_once()
        notify.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), self.original_state)
        self.assertNotIn("Skipping", self.output.getvalue())

    def test_check_that_finishes_during_quiet_hours_does_not_notify(self) -> None:
        with (
            at_warsaw_time("21:59:59"),
            patch("playtomic_core.should_send_notifications_now", side_effect=[True, False]),
            patch("playtomic_core.http_get_json", return_value=[]) as fetch,
            patch("playtomic_monitor.send_notifications") as notify,
        ):
            self.assertEqual(self.run_monitor(), 0)

        fetch.assert_called_once()
        notify.assert_not_called()

    def test_manual_queries_still_fetch_during_quiet_hours(self) -> None:
        with (
            at_warsaw_time("02:00:00"),
            patch("playtomic_core.http_get_json", return_value=[]) as fetch,
        ):
            _, _, club_runs = build_club_runs(self.config_path)

        fetch.assert_called_once()
        self.assertTrue(club_runs[0].availability_checked)
        self.assertFalse(club_runs[0].notifications_allowed_now)
        self.assertEqual(self.state_path.read_bytes(), self.original_state)

    def test_without_notification_windows_checks_at_any_time(self) -> None:
        self.config_path.write_text(CONFIG.replace(
            '[[notification_windows]]\ndays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]\n'
            'start = "08:00"\nend = "22:00"\n',
            "",
        ))
        with (
            at_warsaw_time("02:00:00"),
            patch("playtomic_core.http_get_json", return_value=[]) as fetch,
            patch("playtomic_monitor.send_notifications") as notify,
        ):
            self.assertEqual(self.run_monitor(), 0)

        fetch.assert_called_once()
        notify.assert_called_once()

    def test_explicit_test_notification_bypasses_quiet_hours_without_fetching(self) -> None:
        with (
            at_warsaw_time("02:00:00"),
            patch("playtomic_core.http_get_json") as fetch,
            patch("playtomic_monitor.send_notifications") as notify,
        ):
            self.assertEqual(self.run_monitor(test_notification="test"), 0)

        fetch.assert_not_called()
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1], "test")
        self.assertEqual(self.state_path.read_bytes(), self.original_state)

    def test_notification_window_boundaries(self) -> None:
        config = {"notification_windows": [{"days": ["thu"], "start": "08:00", "end": "22:00"}]}
        for time_text, expected in [("07:59:59", False), ("08:00:00", True), ("22:00:00", True), ("22:00:01", False)]:
            with self.subTest(time=time_text), at_warsaw_time(time_text):
                self.assertEqual(should_send_notifications_now(config, "Europe/Warsaw"), expected)


if __name__ == "__main__":
    unittest.main()
