from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_resets import format_message, normalize_json


class NormalizeJsonTests(unittest.TestCase):
    def test_normalizes_public_status_api_response(self) -> None:
        payload = {
            "data": {
                "latest_reset": {
                    "id": "2091688655828246890",
                    "reset_type": "regular",
                    "announced_at": "2026-08-24T00:46:51.000Z",
                    "text": "Good Sunday. Reset has been propagated to accounts.",
                    "source": {
                        "type": "x_post",
                        "author": "thsottiaux",
                        "url": "https://x.com/thsottiaux/status/2091688655828246890",
                    },
                },
                "active_watch": {
                    "level": "strong",
                    "reset_chance_percent": 90,
                    "forecast_window": "by 9pm UTC",
                    "observed_at": "2026-08-23T18:00:00.000Z",
                    "expires_at": "2026-08-23T21:00:00.000Z",
                    "text": "Strong chance of a reset soon.",
                    "source": {
                        "type": "x_post",
                        "author": "thsottiaux",
                        "url": "https://x.com/thsottiaux/status/2091000000000000000",
                    },
                },
                "stats": {
                    "total": 46,
                    "last_reset_at": "2026-08-24T00:46:51.000Z",
                    "days_since_last": 0.3,
                    "avg_interval_days": 7.6,
                },
            },
            "meta": {
                "api_version": "v1",
                "generated_at": "2026-08-24T06:50:01.912Z",
            },
        }

        snapshot = normalize_json(payload, source_url="https://codex-resets.com/api/v1/status")

        self.assertEqual(snapshot["watch_chance"], "90%")
        self.assertEqual(snapshot["watch_deadline"], "2026-08-23T21:00:00.000Z")
        self.assertEqual(snapshot["watch_seen_at"], "2026-08-23T18:00:00.000Z")
        self.assertEqual(snapshot["watch_summary"], "Strong chance of a reset soon.")
        self.assertEqual(snapshot["latest_reset_at"], "2026-08-24T00:46:51.000Z")
        self.assertEqual(snapshot["latest_reset_type"], "regular")
        self.assertEqual(snapshot["latest_announcement_id"], "2091688655828246890")
        self.assertEqual(snapshot["latest_announcement"], "Good Sunday. Reset has been propagated to accounts.")
        self.assertEqual(snapshot["latest_announcement_url"], "https://x.com/thsottiaux/status/2091688655828246890")
        self.assertEqual(snapshot["reset_count"], "46")
        self.assertIn("fingerprint", snapshot)

    def test_format_message_includes_watch_seen_at(self) -> None:
        message = format_message(
            {
                "watch_chance": "90%",
                "watch_deadline": "2026-08-23T21:00:00.000Z",
                "watch_seen_at": "2026-08-23T18:00:00.000Z",
                "watch_summary": "Strong chance of a reset soon.",
                "latest_reset_at": "2026-08-24T00:46:51.000Z",
                "latest_reset_type": "regular",
                "latest_announcement": "Good Sunday. Reset has been propagated to accounts.",
                "latest_announcement_url": "https://x.com/thsottiaux/status/2091688655828246890",
            }
        )

        self.assertIn("Seen at: 2026-08-23T18:00:00.000Z", message)


if __name__ == "__main__":
    unittest.main()
