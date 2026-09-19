from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from codex_resets import DEFAULT_SOURCE_URL, format_message, normalize_from_url
from lark import send_text
from state import save_state


def reset_minute(value: Any) -> str | None:
    """A source-independent UTC event marker; homepage timestamps omit seconds."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = datetime.strptime(value, "%b %d, %Y, %I:%M %p UTC").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def latest_known_minute(state: dict[str, Any]) -> str | None:
    latest = reset_minute((state.get("last_snapshot") or {}).get("latest_reset_at"))
    fallback = state.get("fallback_reset_minute")
    return max(filter(None, (latest, fallback)), default=None)


def use_homepage_fallback(
    *,
    state: dict[str, Any],
    state_path: str,
    webhook_url: str,
    secret: str | None,
    dry_run: bool,
    force: bool,
    homepage_url: str = DEFAULT_SOURCE_URL,
) -> int:
    """Degraded mode: only confirm NEW reset events; never infer active_watch from HTML."""
    snapshot = normalize_from_url(homepage_url)
    minute = reset_minute(snapshot.get("latest_reset_at"))
    if not minute or not snapshot.get("latest_announcement"):
        raise RuntimeError("Homepage fallback lacks a verified latest reset and announcement; refusing to overwrite state or send a notification")

    previous = latest_known_minute(state)
    is_new = previous is not None and minute > previous
    print(f"source_mode=homepage_degraded latest_reset_minute={minute} last_seen_minute={previous}")
    print("warning=active_watch cannot be reliably monitored while the status API is unavailable")
    if not (is_new or force):
        print("fallback_no_new_reset=true")
        if previous is None and not dry_run:
            # Establish an initial baseline without a notification.
            save_state(state_path, {**state, "fallback_reset_minute": minute})
        return 0

    message = "⚠️ Codex Resets 首页备用通知（API 暂不可用）\n\n" + format_message({
        **snapshot,
        "active_watch_present": None,
        "watch_chance": None,
        "watch_deadline": None,
        "watch_summary": None,
    })
    if dry_run:
        print("[dry-run] " + message)
        return 0
    send_text(webhook_url=webhook_url, secret=secret, text=message)
    save_state(state_path, {**state, "fallback_reset_minute": minute})
    print("fallback_notification_sent=true")
    return 0


def describe_http_failure(error: httpx.HTTPStatusError) -> str:
    response = error.response
    headers = response.headers
    diagnostic = {
        "status": response.status_code,
        "host": response.request.url.host,
        "path": response.request.url.path,
        "server": headers.get("server", ""),
        "cf_ray": headers.get("cf-ray", ""),
        "cf_mitigated": headers.get("cf-mitigated", ""),
        "retry_after": headers.get("retry-after", ""),
    }
    return " ".join(f"{key}={value}" for key, value in diagnostic.items() if value != "")
