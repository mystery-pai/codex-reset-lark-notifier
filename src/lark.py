from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any

import httpx


class LarkNotifyError(RuntimeError):
    pass


def build_sign(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        msg=b"",
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_text(webhook_url: str, text: str, secret: str | None = None, timeout_seconds: float = 15.0) -> dict[str, Any]:
    if not webhook_url:
        raise LarkNotifyError("LARK_WEBHOOK_URL is required when sending a notification")

    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": text},
    }

    if secret:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = build_sign(timestamp, secret)

    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(webhook_url, json=payload)
        response.raise_for_status()
        data = response.json()

    code = data.get("code", data.get("StatusCode", 0))
    if code not in (0, None):
        raise LarkNotifyError(f"Lark webhook rejected payload: {data}")

    return data
