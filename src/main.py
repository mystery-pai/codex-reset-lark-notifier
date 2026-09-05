from __future__ import annotations

import argparse
import os
from typing import Any

from dotenv import load_dotenv

from codex_resets import DEFAULT_API_URL, format_message, normalize_from_url, notification_key_snapshot, utc_now_iso
from lark import send_text
from state import load_state, save_state


def str_to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor Codex reset watch updates and notify Lark.")
    parser.add_argument("--dry-run", action="store_true", help="Print the message without sending or writing state.")
    parser.add_argument("--force", action="store_true", help="Send a notification even if the notification key did not change.")
    parser.add_argument("--source-url", help="Override SOURCE_URL or CODEX_RESETS_API_URL.")
    return parser


def resolve_previous_notification_key(state: dict[str, Any]) -> str | None:
    value = state.get("last_notification_key")
    if value:
        return str(value)

    snapshot_key = notification_key_snapshot(state.get("last_snapshot"))
    if snapshot_key:
        return snapshot_key

    # Backward compatibility for state files created before notification_key was added.
    value = state.get("last_fingerprint")
    return str(value) if value else None


def run(args: argparse.Namespace) -> int:
    load_dotenv()

    source_url = (
        args.source_url
        or os.getenv("CODEX_RESETS_API_URL")
        or os.getenv("SOURCE_URL")
        or DEFAULT_API_URL
    )
    state_path = os.getenv("STATE_PATH", "data/state.json")
    notify_on_first_run = str_to_bool(os.getenv("NOTIFY_ON_FIRST_RUN"), default=False)

    state = load_state(state_path)
    snapshot = normalize_from_url(source_url)
    current_fingerprint = snapshot["fingerprint"]
    current_notification_key = snapshot.get("notification_key") or current_fingerprint
    previous_fingerprint = state.get("last_fingerprint")
    previous_notification_key = resolve_previous_notification_key(state)

    first_run = not previous_notification_key
    snapshot_changed = current_fingerprint != previous_fingerprint
    notification_changed = current_notification_key != previous_notification_key
    should_notify = args.force or notification_changed

    if first_run and not notify_on_first_run and not args.force:
        should_notify = False

    message = format_message(snapshot)

    print(f"source_url={source_url}")
    print(f"first_run={first_run}")
    print(f"snapshot_changed={snapshot_changed}")
    print(f"notification_changed={notification_changed}")
    print(f"should_notify={should_notify}")
    print(f"fingerprint={current_fingerprint}")
    print(f"notification_key={current_notification_key}")

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
        if snapshot_changed or notification_changed or state.get("last_notification_key") != current_notification_key:
            next_state: dict[str, Any] = {
                "last_fingerprint": current_fingerprint,
                "last_notification_key": current_notification_key,
                "last_snapshot": snapshot,
                "updated_at": utc_now_iso(),
            }
            save_state(state_path, next_state)
            print(f"state_saved={state_path}")
        else:
            print("state_unchanged=true")

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
