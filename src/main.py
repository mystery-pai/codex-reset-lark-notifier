from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

from codex_resets import (
    DEFAULT_API_URL,
    DEFAULT_SOURCE_URL,
    format_message,
    normalize_from_url,
    notification_key_snapshot,
    utc_now_iso,
)
from lark import send_text
from state import load_state, save_state


def str_to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor Codex reset watch updates and notify Lark.")
    parser.add_argument("--dry-run", action="store_true", help="Print without sending or writing state.")
    parser.add_argument("--force", action="store_true", help="Send even if the notification key did not change.")
    parser.add_argument("--source-url", help="Override SOURCE_URL or CODEX_RESETS_API_URL.")
    return parser


def resolve_previous_notification_key(state: dict[str, Any]) -> str | None:
    value = state.get("last_notification_key")
    if value:
        return str(value)
    snapshot_key = notification_key_snapshot(state.get("last_snapshot"))
    if snapshot_key:
        return snapshot_key
    value = state.get("last_fingerprint")
    return str(value) if value else None


def reset_minute(value: Any) -> str | None:
    """Normalize API ISO timestamps and public-page UTC timestamps to the same minute."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        if "T" in raw:
            date = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            normalized = raw.replace(",", "")
            date = datetime.strptime(normalized, "%b %d %Y %I:%M %p UTC").replace(tzinfo=timezone.utc)
        return date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    except ValueError:
        return None


def send_notification(snapshot: dict[str, Any], *, dry_run: bool, text: str | None = None) -> None:
    message = text or format_message(snapshot)
    if dry_run:
        print("\n[dry-run] Notification message:\n" + message)
        return
    send_text(
        webhook_url=os.getenv("LARK_WEBHOOK_URL", ""),
        secret=os.getenv("LARK_WEBHOOK_SECRET") or None,
        text=message,
    )
    print("notification_sent=true")


def handle_api_forbidden(
    *,
    api_url: str,
    state: dict[str, Any],
    state_path: str,
    dry_run: bool,
    notify_on_first_run: bool,
) -> int:
    """Use the public homepage for NEW reset announcements only.

    The HTML page does not provide a reliable structured active_watch. Never
    replace the trusted API snapshot with an incomplete HTML snapshot.
    """
    print(f"source_degraded=true reason=api_http_403 api_url={api_url}", flush=True)
    print("Trying public homepage for a verified new reset announcement only.", flush=True)
    try:
        page = normalize_from_url(DEFAULT_SOURCE_URL)
    except (httpx.HTTPError, ValueError) as exc:
        print(f"homepage_fallback_failed={type(exc).__name__}: {exc}", flush=True)
        return 1

    observed = reset_minute(page.get("latest_reset_at"))
    previous = reset_minute((state.get("last_snapshot") or {}).get("latest_reset_at"))
    last_fallback = state.get("fallback_last_reset_minute")
    # Require the reset date AND announcement to avoid interpreting an error
    # or an HTML redesign as a new event.
    if not observed or not page.get("latest_announcement"):
        print("homepage_fallback_invalid=true; retaining state and skipping notification", flush=True)
        return 1
    if last_fallback == observed or (previous and observed <= previous):
        print("homepage_fallback_no_new_reset=true; trusted API state unchanged", flush=True)
        return 0

    # For pre-existing state, only a strictly newer verified reset may notify.
    first_run = not previous and not last_fallback
    should_notify = not first_run or notify_on_first_run
    print(f"homepage_new_reset={observed} first_run={first_run} should_notify={should_notify}", flush=True)
    if should_notify:
        message = (
            "👀 Codex Reset 更新 (官网页面兜底)\n\n"
            f"Latest reset: {observed}\n"
            f"Announcement: {page['latest_announcement']}\n"
            f"Source: {DEFAULT_SOURCE_URL}\n\n"
            "Note: Status API returned HTTP 403. Active watch data is unavailable."
        )
        send_notification(page, dry_run=dry_run, text=message)

    if not dry_run:
        next_state = dict(state)
        next_state["fallback_last_reset_minute"] = observed
        next_state["fallback_updated_at"] = utc_now_iso()
        save_state(state_path, next_state)
        print(f"fallback_state_saved={state_path}", flush=True)
    return 0


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

    try:
        snapshot = normalize_from_url(source_url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403 and source_url == DEFAULT_API_URL:
            return handle_api_forbidden(
                api_url=source_url,
                state=state,
                state_path=state_path,
                dry_run=args.dry_run,
                notify_on_first_run=notify_on_first_run,
            )
        print(f"source_fetch_failed=http_{exc.response.status_code} url={source_url}", flush=True)
        raise

    current_fingerprint = snapshot["fingerprint"]
    current_notification_key = snapshot.get("notification_key") or current_fingerprint
    previous_fingerprint = state.get("last_fingerprint")
    previous_notification_key = resolve_previous_notification_key(state)
    first_run = not previous_notification_key
    snapshot_changed = current_fingerprint != previous_fingerprint
    notification_changed = current_notification_key != previous_notification_key
    should_notify = args.force or notification_changed

    # A homepage fallback might have already delivered this exact reset while
    # the API was blocked. API recovery must not send it a second time.
    fallback_minute = state.get("fallback_last_reset_minute")
    current_minute = reset_minute(snapshot.get("latest_reset_at"))
    prior_watch = (state.get("last_snapshot") or {}).get("active_watch_present")
    current_watch = snapshot.get("active_watch_present")
    if (
        not args.force
        and fallback_minute
        and fallback_minute == current_minute
        and prior_watch == current_watch
        and current_watch != "True"
    ):
        should_notify = False
        print("suppress_replayed_fallback_reset=true", flush=True)

    if first_run and not notify_on_first_run and not args.force:
        should_notify = False

    print(f"source_url={source_url}")
    print(f"first_run={first_run}")
    print(f"snapshot_changed={snapshot_changed}")
    print(f"notification_changed={notification_changed}")
    print(f"should_notify={should_notify}")
    print(f"fingerprint={current_fingerprint}")
    print(f"notification_key={current_notification_key}")
    if should_notify:
        send_notification(snapshot, dry_run=args.dry_run)

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
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
