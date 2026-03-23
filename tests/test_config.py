import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhs_downloader.config import load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_reads_antibot_runtime_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[paths]",
                        f'data_dir = "{(root / "runtime").as_posix()}"',
                        f'browser_profile_dir = "{(root / "runtime" / "browser-profile").as_posix()}"',
                        f'storage_state_path = "{(root / "runtime" / "storage_state.json").as_posix()}"',
                        f'db_path = "{(root / "runtime" / "xhs.sqlite3").as_posix()}"',
                        f'download_root = "{(root / "downloads").as_posix()}"',
                        "",
                        "[runtime]",
                        "headless = false",
                        "crawl_delay_ms = 1200",
                        "search_page_wait_ms = 2000",
                        "note_detail_wait_ms = 1800",
                        "detail_delay_ms = 1500",
                        "download_delay_ms = 1200",
                        "request_jitter_ms = 400",
                        'download_transport = "browser_context"',
                        'protection_mode = "pause"',
                        "max_retries = 3",
                        "download_timeout = 30",
                        "screenshot_on_failure = true",
                        'user_agent = "Mozilla/5.0 Test"',
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                config = load_config(str(config_path))

            self.assertEqual(1500, config.detail_delay_ms)
            self.assertEqual(1200, config.download_delay_ms)
            self.assertEqual(400, config.request_jitter_ms)
            self.assertEqual("browser_context", config.download_transport)
            self.assertEqual("pause", config.protection_mode)

    def test_environment_variables_can_override_transport(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[paths]",
                        f'data_dir = "{(root / "runtime").as_posix()}"',
                        f'browser_profile_dir = "{(root / "runtime" / "browser-profile").as_posix()}"',
                        f'storage_state_path = "{(root / "runtime" / "storage_state.json").as_posix()}"',
                        f'db_path = "{(root / "runtime" / "xhs.sqlite3").as_posix()}"',
                        f'download_root = "{(root / "downloads").as_posix()}"',
                        "",
                        "[runtime]",
                        'download_transport = "browser_context"',
                        'protection_mode = "pause"',
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {
                    "XHS_DOWNLOAD_TRANSPORT": "http",
                    "XHS_PROTECTION_MODE": "pause",
                    "XHS_REQUEST_JITTER_MS": "150",
                },
                clear=True,
            ):
                config = load_config(str(config_path))

            self.assertEqual("http", config.download_transport)
            self.assertEqual("pause", config.protection_mode)
            self.assertEqual(150, config.request_jitter_ms)
