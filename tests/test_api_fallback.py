from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main
from codex_resets import build_snapshot


def args(*, dry_run=False, force=False):
    return argparse.Namespace(dry_run=dry_run, force=force, source_url=None)


class FallbackTests(unittest.TestCase):
    def test_date_normalization_matches_api_and_homepage(self):
        self.assertEqual(
            main.reset_minute("Sep 12, 2026, 8:09 AM UTC"),
            main.reset_minute("2026-09-12T08:09:17.000Z"),
        )

    def test_same_reset_does_not_send_or_overwrite_api_state(self):
        original = build_snapshot(
            source_url="https://codex-resets.com/api/v1/status",
            active_watch_present=False,
            latest_reset_at="2026-09-12T08:09:17.000Z",
            latest_announcement="already delivered",
        )
        page = build_snapshot(
            source_url="https://codex-resets.com/",
            latest_reset_at="Sep 12, 2026, 8:09 AM UTC",
            latest_announcement="already delivered",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            previous = {"last_snapshot": original, "last_notification_key": original["notification_key"]}
            path.write_text(json.dumps(previous), encoding="utf-8")
            with patch.object(main, "normalize_from_url", return_value=page), patch.object(
                main, "send_notification"
            ) as send:
                outcome = main.handle_api_forbidden(
                    api_url=main.DEFAULT_API_URL,
                    state=previous,
                    state_path=str(path),
                    dry_run=False,
                    notify_on_first_run=False,
                )
            self.assertEqual(outcome, 0)
            send.assert_not_called()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), previous)

    def test_new_homepage_reset_sends_once_then_dedupes(self):
        old = build_snapshot(
            source_url=main.DEFAULT_API_URL,
            active_watch_present=False,
            latest_reset_at="2026-09-12T08:09:17.000Z",
            latest_announcement="old",
        )
        new = build_snapshot(
            source_url=main.DEFAULT_SOURCE_URL,
            latest_reset_at="Sep 19, 2026, 9:00 AM UTC",
            latest_announcement="new reset",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            previous = {
                "last_snapshot": old,
                "last_fingerprint": old["fingerprint"],
                "last_notification_key": old["notification_key"],
            }
            path.write_text(json.dumps(previous), encoding="utf-8")
            with patch.object(main, "normalize_from_url", return_value=new), patch.object(
                main, "send_notification"
            ) as send:
                self.assertEqual(
                    main.handle_api_forbidden(
                        api_url=main.DEFAULT_API_URL,
                        state=previous,
                        state_path=str(path),
                        dry_run=False,
                        notify_on_first_run=False,
                    ),
                    0,
                )
                send.assert_called_once()
                updated = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(updated["last_snapshot"], previous["last_snapshot"])
                self.assertEqual(updated["fallback_last_reset_minute"], "2026-09-19T09:00Z")
                self.assertEqual(
                    main.handle_api_forbidden(
                        api_url=main.DEFAULT_API_URL,
                        state=updated,
                        state_path=str(path),
                        dry_run=False,
                        notify_on_first_run=False,
                    ),
                    0,
                )
                send.assert_called_once()

    def test_invalid_homepage_keeps_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {"last_notification_key": "known"}
            path.write_text(json.dumps(state), encoding="utf-8")
            with patch.object(main, "normalize_from_url", return_value={"latest_reset_at": None}):
                self.assertEqual(
                    main.handle_api_forbidden(
                        api_url=main.DEFAULT_API_URL,
                        state=state,
                        state_path=str(path),
                        dry_run=False,
                        notify_on_first_run=False,
                    ),
                    1,
                )
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), state)

    def test_api_recovery_suppresses_replay(self):
        existing = build_snapshot(
            source_url=main.DEFAULT_API_URL,
            active_watch_present=False,
            latest_reset_at="2026-09-12T08:09:17.000Z",
            latest_announcement="old",
        )
        recovered = build_snapshot(
            source_url=main.DEFAULT_API_URL,
            active_watch_present=False,
            latest_reset_at="2026-09-19T09:00:25.000Z",
            latest_announcement="new reset",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {
                "last_snapshot": existing,
                "last_fingerprint": existing["fingerprint"],
                "last_notification_key": existing["notification_key"],
                "fallback_last_reset_minute": "2026-09-19T09:00Z",
            }
            path.write_text(json.dumps(state), encoding="utf-8")
            with patch.dict(os.environ, {"STATE_PATH": str(path)}, clear=False), patch.object(
                main, "normalize_from_url", return_value=recovered
            ), patch.object(main, "send_notification") as send:
                with redirect_stdout(io.StringIO()) as output:
                    result = main.run(args())
                self.assertEqual(result, 0)
                self.assertIn("suppress_replayed_fallback_reset=true", output.getvalue())
                send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
