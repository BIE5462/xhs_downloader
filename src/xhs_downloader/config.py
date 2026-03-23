from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .infra.utils import ensure_directory

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - Python 3.9 fallback
    tomllib = None


@dataclass
class AppConfig:
    data_dir: Path
    browser_profile_dir: Path
    storage_state_path: Path
    db_path: Path
    download_root: Path
    headless: bool
    crawl_delay_ms: int
    search_page_wait_ms: int
    note_detail_wait_ms: int
    detail_delay_ms: int
    download_delay_ms: int
    request_jitter_ms: int
    max_retries: int
    download_timeout: int
    download_transport: str
    protection_mode: str
    screenshot_on_failure: bool
    user_agent: str

    def ensure_directories(self) -> None:
        ensure_directory(self.data_dir)
        ensure_directory(self.browser_profile_dir)
        ensure_directory(self.download_root)
        ensure_directory(self.db_path.parent)
        ensure_directory(self.storage_state_path.parent)


def _load_toml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    loader = tomllib
    if loader is None:
        try:
            import tomli as loader  # type: ignore[assignment]
        except ModuleNotFoundError:
            return _load_toml_fallback(path)

    with path.open("rb") as handle:
        return loader.load(handle)


def _load_toml_fallback(path: Path) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    current_section: Optional[str] = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            data.setdefault(current_section, {})
            continue

        if "=" not in line:
            continue

        key, raw_value = [item.strip() for item in line.split("=", 1)]
        value: Any = raw_value
        if raw_value.startswith('"') and raw_value.endswith('"'):
            value = raw_value[1:-1]
        elif raw_value.lower() in {"true", "false"}:
            value = raw_value.lower() == "true"
        else:
            try:
                value = int(raw_value)
            except ValueError:
                value = raw_value

        if current_section:
            section = data.setdefault(current_section, {})
            section[key] = value
        else:
            data[key] = value

    return data


def _bool_from_env(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(config_path: Optional[str] = None) -> AppConfig:
    config_file = Path(config_path or "config.toml")
    raw = _load_toml(config_file)

    paths = raw.get("paths", {})
    runtime = raw.get("runtime", {})

    data_dir = Path(os.getenv("XHS_DATA_DIR", paths.get("data_dir", "runtime")))
    browser_profile_dir = Path(
        os.getenv("XHS_BROWSER_PROFILE_DIR", paths.get("browser_profile_dir", str(data_dir / "browser-profile")))
    )
    storage_state_path = Path(
        os.getenv("XHS_STORAGE_STATE_PATH", paths.get("storage_state_path", str(data_dir / "storage_state.json")))
    )
    db_path = Path(os.getenv("XHS_DB_PATH", paths.get("db_path", str(data_dir / "xhs.sqlite3"))))
    download_root = Path(os.getenv("XHS_DOWNLOAD_ROOT", paths.get("download_root", "downloads")))

    headless = _bool_from_env(os.getenv("XHS_HEADLESS"), bool(runtime.get("headless", False)))
    crawl_delay_ms = int(os.getenv("XHS_CRAWL_DELAY_MS", runtime.get("crawl_delay_ms", 1200)))
    search_page_wait_ms = int(os.getenv("XHS_SEARCH_PAGE_WAIT_MS", runtime.get("search_page_wait_ms", 2000)))
    note_detail_wait_ms = int(os.getenv("XHS_NOTE_DETAIL_WAIT_MS", runtime.get("note_detail_wait_ms", 1800)))
    detail_delay_ms = int(os.getenv("XHS_DETAIL_DELAY_MS", runtime.get("detail_delay_ms", 1500)))
    download_delay_ms = int(os.getenv("XHS_DOWNLOAD_DELAY_MS", runtime.get("download_delay_ms", 1200)))
    request_jitter_ms = int(os.getenv("XHS_REQUEST_JITTER_MS", runtime.get("request_jitter_ms", 400)))
    max_retries = int(os.getenv("XHS_MAX_RETRIES", runtime.get("max_retries", 3)))
    download_timeout = int(os.getenv("XHS_DOWNLOAD_TIMEOUT", runtime.get("download_timeout", 30)))
    download_transport = str(
        os.getenv("XHS_DOWNLOAD_TRANSPORT", runtime.get("download_transport", "browser_context"))
    ).strip() or "browser_context"
    protection_mode = str(os.getenv("XHS_PROTECTION_MODE", runtime.get("protection_mode", "pause"))).strip() or "pause"
    screenshot_on_failure = _bool_from_env(
        os.getenv("XHS_SCREENSHOT_ON_FAILURE"),
        bool(runtime.get("screenshot_on_failure", True)),
    )
    user_agent = os.getenv(
        "XHS_USER_AGENT",
        runtime.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        ),
    )

    config = AppConfig(
        data_dir=data_dir,
        browser_profile_dir=browser_profile_dir,
        storage_state_path=storage_state_path,
        db_path=db_path,
        download_root=download_root,
        headless=headless,
        crawl_delay_ms=crawl_delay_ms,
        search_page_wait_ms=search_page_wait_ms,
        note_detail_wait_ms=note_detail_wait_ms,
        detail_delay_ms=detail_delay_ms,
        download_delay_ms=download_delay_ms,
        request_jitter_ms=request_jitter_ms,
        max_retries=max_retries,
        download_timeout=download_timeout,
        download_transport=download_transport,
        protection_mode=protection_mode,
        screenshot_on_failure=screenshot_on_failure,
        user_agent=user_agent,
    )
    config.ensure_directories()
    return config
