"""R-79CC-2 (session arena-f642a30a): ``age_label``'s fallback parses an ISO-8601
UTC stamp ("…Z") and must treat it as UTC. ``time.mktime`` interprets the parsed
struct as *local* time, which skews the published snapshot age on any non-UTC
runner; ``calendar.timegm`` is the correct UTC counterpart.

This test pins the UTC semantics: it freezes ``time.time`` and asserts the exact
age produced for a known stamp. It passes in UTC environments before and after
the fix, but fails against the old ``mktime`` implementation whenever the host
timezone is not UTC — which is exactly the bug being fixed.
"""

import calendar
import time
import unittest
from unittest import mock

from site_build import extras


class TestAgeLabelUTC(unittest.TestCase):
    def test_fallback_stamp_is_read_as_utc(self):
        stamp = "2026-11-21T06:00:00Z"
        expected_ts = calendar.timegm(time.strptime("2026-11-21T06:00:00", "%Y-%m-%dT%H:%M:%S"))
        with mock.patch.object(extras.time, "time", return_value=expected_ts + 30):
            self.assertEqual(extras.age_label(stamp), "30s old")
        with mock.patch.object(extras.time, "time", return_value=expected_ts + 30 * 60):
            self.assertEqual(extras.age_label(stamp), "30 min old")

    def test_explicit_ts_still_wins_over_parsed_stamp(self):
        with mock.patch.object(extras.time, "time", return_value=1_800_000_000.0):
            self.assertEqual(extras.age_label("2026-11-21T06:00:00Z", 1_800_000_000.0 - 120), "2 min old")

    def test_unparseable_stamp_returns_empty(self):
        self.assertEqual(extras.age_label("not-a-date"), "")
        self.assertEqual(extras.age_label(None, None), "")


if __name__ == "__main__":
    unittest.main()
