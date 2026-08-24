from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_resets import DEFAULT_API_URL
from main import run


class MainTests(unittest.TestCase):
    def test_uses_public_status_api_by_default(self) -> None:
        args = argparse.Namespace(dry_run=True, force=False, source_url=None)
        snapshot = {
            "fingerprint": "abc123",
            "latest_reset_at": "2026-08-24T00:46:51.000Z",
        }

        with patch.dict(os.environ, {}, clear=True):
            with patch("main.load_dotenv"):
                with patch("main.load_state", return_value={"last_fingerprint": "abc123"}):
                    with patch("main.normalize_from_url", return_value=snapshot) as normalize_from_url:
                        result = run(args)

        self.assertEqual(result, 0)
        normalize_from_url.assert_called_once_with(DEFAULT_API_URL)


if __name__ == "__main__":
    unittest.main()
