from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def generate_run_id(keyword: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = safe_filename(keyword, fallback="keyword")
    return f"{stamp}_{slug[:24]}"


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(text: str, fallback: str = "item") -> str:
    text = (text or "").strip()
    text = re.sub(r"[\\\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._")
    return text or fallback


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def normalize_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower().replace(",", "")
    if not text:
        return 0

    wan_match = re.search(r"(\d+(?:\.\d+)?)\s*[万w]", text)
    if wan_match:
        return int(float(wan_match.group(1)) * 10000)

    k_match = re.search(r"(\d+(?:\.\d+)?)\s*k", text)
    if k_match:
        return int(float(k_match.group(1)) * 1000)

    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1))
    return 0


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value


def dump_json(data: Any) -> str:
    return json.dumps(to_jsonable(data), ensure_ascii=False, indent=2)


def parse_json(text: str, default: Any) -> Any:
    if not text:
        return default
    return json.loads(text)


def build_run_root(download_root: Path, keyword: str, run_id: str) -> Path:
    return ensure_directory(download_root / safe_filename(keyword, fallback="keyword") / run_id)


def build_note_output_dir(run_root: Path, note_id: str) -> Path:
    return ensure_directory(run_root / safe_filename(note_id, fallback="note"))


def guess_extension_from_url(url: str, default: str = ".jpg") -> str:
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return suffix
    return default


def first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def published_at_from_text(text: str) -> str:
    patterns = [
        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{4}/\d{2}/\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""

