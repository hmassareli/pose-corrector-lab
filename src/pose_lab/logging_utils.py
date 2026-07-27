"""Run logging helpers (jsonl + directories)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def make_run_dir(root: str | Path, name: str | None = None) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"{stamp}_{name}" if name else stamp
    d = root / run_id
    (d / "checkpoints").mkdir(parents=True)
    (d / "eval").mkdir(parents=True)
    (d / "scalars").mkdir(parents=True)
    return d


class JsonlLogger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: dict[str, Any]) -> None:
        record = {"ts": time.time(), **record}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_json(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
