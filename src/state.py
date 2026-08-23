from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EMPTY_STATE: dict[str, Any] = {
    "last_fingerprint": None,
    "last_snapshot": None,
    "updated_at": None,
}


def load_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return dict(EMPTY_STATE)

    try:
        with state_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError:
        return dict(EMPTY_STATE)

    if not isinstance(data, dict):
        return dict(EMPTY_STATE)

    merged = dict(EMPTY_STATE)
    merged.update(data)
    return merged


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
