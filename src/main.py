from __future__ import annotations

import argparse
import os
from typing import Any

from dotenv import load_dotenv

from codex_resets import DEFAULT_SOURCE_URL, format_message, normalize_from_url, utc_now_iso
from lark import send_text
from state import load_state, save_state


def str_to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor Codex reset watch updates and notify Lark.")
    parser.add_argument("--dry-run", action="store_true", help="Print the message without sending or writing state.")
    parser.add_argument("--force", action="store_true", help="Send a notification even if the fingerprint did not change.")
    parser.add_argument("--source-url", help="Override SOURCE_URL or CODEX_RESETS_API_URL.")
    return parser


def run(args: argparse.Namespace) -> int:
    load_dotenv()

    source_url = (
        args.source_url
        or os.getenv("CODEX_RESETS_API_URL")
        or os.getenv("SOURCE_URL")
        or DEFAULT_SOURCE_URL
    )
    state_path = os.getenv("STATE_PATH", "data/state.json")
    notify_on_first_run = str_to_bool(os.getenv("NOTIFY_ON_FIRST_RUN"), default=False)

    state = load_state(state_path)
    snapshot = normalize_from_url(source_url)
    current_fingerprint = snapshot["fingerprint"]
    previous_fingerprint = state.get("last_fingerprint")

    first_run = not previous_fingerprint
    changed = current_fingerprint != previous_fingerprint
    should_notify = args.force or changed

    if first_run and not notify_on_first_run and not args.force:
        should_notify = False

    message = format_message(snapshot)

    print(f"source_url={source_url}")
    print(f"first_run={first_run}")
    print(f"changed={changed}")
    print(f"should_notify={should_notify}")
    print(f"fingerprint={current_fingerprint}")

    if should_notify:
        if args.dry_run:
            print("\n[dry-run] Notification message:\n")
            print(message)
        else:
            send_text(
                webhook_url=os.getenv("LARK_WEBHOOK_URL", ""),
                secret=os.getenv("LARK_WEBHOOK_SECRET") or None,
                text=message,
            )
            print("notification_sent=true")

    if not args.dry_run:
        next_state: dict[str, Any] = {
            "last_fingerprint": current_fingerprint,
            "last_snapshot": snapshot,
            "updated_at": utc_now_iso(),
        }
        save_state(state_path, next_state)
        print(f"state_saved={state_path}")

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
