from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

DEFAULT_API_URL = "https://codex-resets.com/api/v1/status"
DEFAULT_SOURCE_URL = "https://codex-resets.com/"
MONTH_PATTERN = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}(?:,\s+\d{1,2}:\d{2}\s+(?:AM|PM)\s+UTC)?",
    re.IGNORECASE,
)
PERCENT_PATTERN = re.compile(r"[<>]?\d{1,3}%")

# Fields that represent what the user sees as a meaningful notification event.
# Do not include volatile bookkeeping or aggregate stats such as fetched_at,
# raw_shape, or reset_count. The API can revise reset_count without changing the
# latest reset event, which would otherwise duplicate the same Lark message.
NOTIFICATION_KEY_FIELDS = (
    "source_url",
    "active_watch_present",
    "watch_level",
    "watch_chance",
    "watch_deadline",
    "watch_expires_at",
    "watch_seen_at",
    "watch_summary",
    "watch_source_url",
    "latest_reset_at",
    "latest_reset_type",
    "latest_announcement_id",
    "latest_announcement",
    "latest_announcement_url",
)

SNAPSHOT_FINGERPRINT_EXCLUDE = {
    "fetched_at",
    "fingerprint",
    "notification_key",
    "raw_shape",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch_payload(url: str) -> tuple[str, str]:
    headers = {
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "User-Agent": "codex-reset-lark-notifier/0.1",
    }
    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        return response.text, content_type


def normalize_from_url(url: str) -> dict[str, Any]:
    body, content_type = fetch_payload(url)
    if "json" in content_type.lower() or body.lstrip().startswith(("{", "[")):
        return normalize_json(json.loads(body), source_url=url)
    return normalize_html(body, source_url=url)


def normalize_json(payload: Any, source_url: str) -> dict[str, Any]:
    if isinstance(payload, list):
        first = payload[0] if payload else {}
        return build_snapshot(
            source_url=source_url,
            latest_announcement=compact_json(first),
            raw=payload,
        )

    if not isinstance(payload, dict):
        return build_snapshot(source_url=source_url, latest_announcement=str(payload), raw=payload)

    data = first_dict(payload.get("data"))
    root = data or payload
    first_item = find_first_item(root)

    active_watch = first_dict(
        root.get("active_watch"),
        root.get("reset_watch"),
        root.get("resetWatch"),
        root.get("watch"),
        root.get("forecast"),
    )
    watch = active_watch or root
    watch_source = first_dict(watch.get("source"))

    latest_reset = first_dict(
        root.get("latest_reset"),
        root.get("latestReset"),
        root.get("latest"),
        first_item,
    )
    latest_source = first_dict(latest_reset.get("source"))
    stats = first_dict(root.get("stats"))

    snapshot = build_snapshot(
        source_url=source_url,
        active_watch_present=bool(active_watch),
        watch_level=first_value(watch, ["level", "severity", "status"]),
        watch_chance=format_percent(
            first_value(
                watch,
                [
                    "reset_chance_percent",
                    "resetChancePercent",
                    "chance",
                    "probability",
                    "reset_chance",
                    "resetChance",
                    "score",
                ],
            )
        ),
        watch_deadline=first_value(
            watch,
            [
                "forecast_window",
                "forecastWindow",
                "deadline",
                "by",
                "eta",
                "estimated_at",
                "estimatedAt",
                "target_at",
                "targetAt",
            ],
        ),
        watch_expires_at=first_value(
            watch,
            ["expires_at", "expiresAt", "expiry", "valid_until", "validUntil"],
        ),
        watch_seen_at=first_value(
            watch,
            ["observed_at", "observedAt", "seen_at", "seenAt"],
        ),
        watch_summary=first_value(
            watch,
            ["summary", "reason", "evidence", "message", "text"],
        ),
        watch_source_url=first_value(watch_source, ["url"]),
        latest_reset_at=first_value(
            latest_reset,
            ["at", "time", "date", "created_at", "createdAt", "announced_at", "announcedAt"],
        ),
        latest_reset_type=first_value(
            latest_reset,
            ["type", "kind", "reset_type", "resetType", "classification"],
        ),
        latest_announcement=first_value(latest_reset, ["text", "message", "summary"])
        or compact_json(first_item or latest_reset),
        latest_announcement_id=first_value(latest_reset, ["id", "announcement_id", "announcementId"]),
        latest_announcement_url=first_value(latest_source, ["url"]),
        reset_count=first_value(stats, ["total"]),
        raw=payload,
    )
    return snapshot


def normalize_html(html: str, source_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    text_lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]

    watch_chance = extract_watch_chance(text_lines)
    watch_deadline = extract_after_marker(text_lines, "Reset chance", max_lookahead=3)
    latest_reset_at = extract_latest_reset_at(text_lines)
    latest_announcement = extract_latest_announcement(text_lines)
    latest_announcement_url = extract_first_external_link(soup)

    return build_snapshot(
        source_url=source_url,
        active_watch_present=watch_chance is not None,
        watch_chance=watch_chance,
        watch_deadline=watch_deadline,
        watch_summary=extract_quote(text_lines),
        latest_reset_at=latest_reset_at,
        latest_reset_type=extract_reset_type(text_lines),
        latest_announcement=latest_announcement,
        latest_announcement_url=latest_announcement_url,
        reset_count=extract_reset_count(text_lines),
        raw=None,
    )


def build_snapshot(
    *,
    source_url: str,
    active_watch_present: Any | None = None,
    watch_level: Any | None = None,
    watch_chance: Any | None = None,
    watch_deadline: Any | None = None,
    watch_expires_at: Any | None = None,
    watch_summary: Any | None = None,
    watch_seen_at: Any | None = None,
    watch_source_url: Any | None = None,
    latest_reset_at: Any | None = None,
    latest_reset_type: Any | None = None,
    latest_announcement_id: Any | None = None,
    latest_announcement: Any | None = None,
    latest_announcement_url: Any | None = None,
    reset_count: Any | None = None,
    raw: Any | None = None,
) -> dict[str, Any]:
    snapshot = {
        "source_url": source_url,
        "active_watch_present": stringify(active_watch_present),
        "watch_level": stringify(watch_level),
        "watch_chance": stringify(watch_chance),
        "watch_deadline": stringify(watch_deadline),
        "watch_expires_at": stringify(watch_expires_at),
        "watch_seen_at": stringify(watch_seen_at),
        "watch_summary": stringify(watch_summary),
        "watch_source_url": stringify(watch_source_url),
        "latest_reset_at": stringify(latest_reset_at),
        "latest_reset_type": stringify(latest_reset_type),
        "latest_announcement_id": stringify(latest_announcement_id),
        "latest_announcement": stringify(latest_announcement),
        "latest_announcement_url": stringify(latest_announcement_url),
        "reset_count": stringify(reset_count),
        "fetched_at": utc_now_iso(),
    }
    snapshot["notification_key"] = notification_key_snapshot(snapshot)
    snapshot["fingerprint"] = fingerprint_snapshot(snapshot)
    if raw is not None:
        snapshot["raw_shape"] = describe_raw_shape(raw)
    return snapshot


def notification_key_snapshot(snapshot: dict[str, Any] | None) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    stable = {key: snapshot.get(key) for key in NOTIFICATION_KEY_FIELDS}
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_snapshot(snapshot: dict[str, Any]) -> str:
    stable = {k: v for k, v in snapshot.items() if k not in SNAPSHOT_FINGERPRINT_EXCLUDE}
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def format_message(snapshot: dict[str, Any]) -> str:
    lines = ["👀 Codex Reset Watch 更新", ""]
    add_line(lines, "Active watch", snapshot.get("active_watch_present"))
    add_line(lines, "Watch level", snapshot.get("watch_level"))
    add_line(lines, "Reset chance", snapshot.get("watch_chance"))
    add_line(lines, "Forecast window", snapshot.get("watch_deadline"))
    add_line(lines, "Expires at", snapshot.get("watch_expires_at"))
    add_line(lines, "Observed at", snapshot.get("watch_seen_at"))
    add_line(lines, "Evidence", snapshot.get("watch_summary"))
    add_line(lines, "Watch source", snapshot.get("watch_source_url"))
    add_line(lines, "Latest reset", snapshot.get("latest_reset_at"))
    add_line(lines, "Reset type", snapshot.get("latest_reset_type"))
    add_line(lines, "Announcement", snapshot.get("latest_announcement"))
    add_line(
        lines,
        "Source",
        snapshot.get("watch_source_url") or snapshot.get("latest_announcement_url") or snapshot.get("source_url"),
    )
    return "\n".join(lines)


def add_line(lines: list[str], label: str, value: Any) -> None:
    if value not in (None, ""):
        text = str(value)
        if len(text) > 500:
            text = text[:497] + "..."
        lines.append(f"{label}: {text}")


def extract_watch_chance(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        if "Reset watch" in line:
            for candidate in lines[index : index + 6]:
                match = PERCENT_PATTERN.search(candidate)
                if match:
                    return match.group(0)
    for line in lines[:30]:
        match = PERCENT_PATTERN.search(line)
        if match:
            return match.group(0)
    return None


def extract_after_marker(lines: list[str], marker: str, max_lookahead: int = 3) -> str | None:
    for index, line in enumerate(lines):
        if marker.lower() in line.lower():
            for candidate in lines[index + 1 : index + 1 + max_lookahead]:
                if candidate and marker.lower() not in candidate.lower():
                    return candidate
    return None


def extract_latest_reset_at(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        if "Latest Codex" in line and "reset" in line.lower():
            for candidate in lines[index : index + 8]:
                match = MONTH_PATTERN.search(candidate)
                if match:
                    return match.group(0)
    return None


def extract_latest_announcement(lines: list[str]) -> str | None:
    start = 0
    for index, line in enumerate(lines):
        if "Codex reset announcements" in line:
            start = index
            break

    for index, line in enumerate(lines[start:], start=start):
        if MONTH_PATTERN.search(line):
            for candidate in lines[index + 1 : index + 6]:
                if is_useful_announcement_line(candidate):
                    return candidate
    return None


def is_useful_announcement_line(line: str) -> bool:
    lower = line.lower()
    if not line or line.startswith("…"):
        return False
    if "view on x" in lower or "image" in lower:
        return False
    if MONTH_PATTERN.search(line):
        return False
    return len(line) >= 20


def extract_quote(lines: list[str]) -> str | None:
    for line in lines[:40]:
        if line.startswith("“") or line.startswith('"'):
            return line.strip(" >")
    return None


def extract_reset_type(lines: list[str]) -> str | None:
    for line in lines[:80]:
        lower = line.lower()
        if "banked reset" in lower:
            return "banked reset"
        if "regular reset" in lower:
            return "regular reset"
    return None


def extract_reset_count(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        if line.lower() == "resets" and index + 1 < len(lines):
            if lines[index + 1].isdigit():
                return lines[index + 1]
    return None


def extract_first_external_link(soup: BeautifulSoup) -> str | None:
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "x.com" in href or "twitter.com" in href:
            return href
    return None


def first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def first_value(source: dict[str, Any], keys: list[str]) -> Any | None:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def format_percent(value: Any | None) -> Any | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value if "%" in value else value.strip()
    return f"{value}%"


def find_first_item(payload: dict[str, Any]) -> Any | None:
    for key in ("announcements", "resets", "items", "events", "feed", "data", "results"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return value[0]
        if isinstance(value, dict):
            nested = find_first_item(value)
            if nested is not None:
                return nested
    return None


def compact_json(value: Any) -> str | None:
    if value in (None, {}, []):
        return None
    if isinstance(value, str):
        return value
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text[:1000]


def stringify(value: Any | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value)


def describe_raw_shape(value: Any) -> str:
    if isinstance(value, dict):
        keys = sorted(map(str, value.keys()))[:20]
        parts = ["dict:" + ",".join(keys)]
        data = first_dict(value.get("data"))
        if data:
            data_keys = sorted(map(str, data.keys()))[:20]
            parts.append("data:" + ",".join(data_keys))
            parts.append("active_watch:" + ("present" if isinstance(data.get("active_watch"), dict) else "missing"))
        return " ".join(parts)
    if isinstance(value, list):
        return f"list:{len(value)}"
    return type(value).__name__
