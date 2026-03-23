from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RUN_DESKTOP_TESTS = os.getenv("RUN_DESKTOP_TESTS") == "1"

if RUN_DESKTOP_TESTS:  # pragma: no cover - 依赖本地 Qt 环境
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from xhs_downloader.desktop.window import DesktopMainWindow
else:  # pragma: no cover - 默认跳过桌面测试
    QApplication = None
    DesktopMainWindow = None
    QSettings = None

from xhs_downloader.domain.models import AccountSession, DownloadTask, JobStatus, NoteSummary, SearchFilters, SearchJob, TaskStatus


def build_session(is_valid: bool = True) -> AccountSession:
    return AccountSession(
        session_id="session_1",
        is_valid=is_valid,
        last_checked_at="2026-03-23T08:00:00+08:00",
        storage_state_path="runtime/storage_state.json",
        browser_profile_dir="runtime/browser-profile",
    )


def build_job(run_id: str = "run_1") -> SearchJob:
    return SearchJob(
        run_id=run_id,
        keyword="穿搭",
        pages=3,
        sort="comprehensive",
        filters=SearchFilters(min_likes=100, min_comments=5),
        status=JobStatus.PARTIAL,
        mode="run",
        created_at="2026-03-23T08:00:00+08:00",
        updated_at="2026-03-23T08:10:00+08:00",
        output_dir=str(Path("downloads") / run_id),
        message="测试任务",
    )


class FakeAuthService:
    def __init__(self, session_status: dict[str, object]) -> None:
        self.session_status = session_status

    def get_session_status(self, validate: bool = False) -> dict[str, object]:
        return self.session_status

    def login(self, wait_for_confirmation=None):
        if wait_for_confirmation is not None:
            wait_for_confirmation()
        self.session_status = {
            "has_session": True,
            "is_valid": True,
            "last_checked_at": "2026-03-23T08:15:00+08:00",
            "session": build_session(),
        }
        return self.session_status["session"]


class FakeWorkflowService:
    def __init__(self, jobs: list[SearchJob], details_by_run: dict[str, dict[str, object]]) -> None:
        self.jobs = jobs
        self.details_by_run = details_by_run

    def list_jobs(self, limit: int = 50) -> dict[str, object]:
        return {"jobs": self.jobs[:limit]}

    def get_run_details(self, run_id: str) -> dict[str, object]:
        return self.details_by_run[run_id]

    def preview(self, **_: object) -> dict[str, object]:
        return {"run_id": "run_1", "candidate_count": 2, "matched_count": 1}

    def run(self, **_: object) -> dict[str, object]:
        return {
            "run_id": "run_1",
            "stats": {"download_success": 1, "download_failed": 1},
            "message": "运行完成",
        }

    def resume(self, run_id: str) -> dict[str, object]:
        return {"run_id": run_id, "message": "恢复完成"}


@unittest.skipUnless(RUN_DESKTOP_TESTS, "设置 RUN_DESKTOP_TESTS=1 后再运行桌面端测试")
class DesktopWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _create_settings(self, root: Path) -> QSettings:
        return QSettings(str(root / "desktop-test.ini"), QSettings.Format.IniFormat)

    def _wait_for_window(self, window: DesktopMainWindow) -> None:
        window._thread_pool.waitForDone(1500)
        self.app.processEvents()

    def test_window_can_bootstrap_offscreen_and_render_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job = build_job()
            details = {
                "job": job,
                "stats": {"summary_count": 2, "download_success": 1, "download_failed": 1},
                "summaries": [],
                "matched_summaries": [
                    NoteSummary(
                        note_id="note_1",
                        title="高点赞穿搭",
                        author_name="作者A",
                        like_count=320,
                        comment_count=10,
                        note_url="https://example.com/note_1",
                        search_rank=1,
                    )
                ],
                "records": [],
                "failed_tasks": [
                    DownloadTask(
                        task_id="task_1",
                        run_id="run_1",
                        note_id="note_1",
                        asset_id="asset_1",
                        source_url="https://example.com/1.jpg",
                        filename="001.jpg",
                        output_dir=str(root / "downloads" / "run_1" / "note_1"),
                        retry_count=1,
                        status=TaskStatus.FAILED,
                        error_message="下载失败",
                    )
                ],
            }
            services = {
                "auth": FakeAuthService(
                    {
                        "has_session": True,
                        "is_valid": True,
                        "last_checked_at": "2026-03-23T08:15:00+08:00",
                        "session": build_session(),
                    }
                ),
                "workflow": FakeWorkflowService([job], {"run_1": details}),
            }
            window = DesktopMainWindow(
                config_path="config.toml",
                verbose=False,
                service_factory=lambda _: services,
                settings=self._create_settings(root),
            )
            self._wait_for_window(window)

            self.assertEqual(1, window._jobs_model.rowCount())
            self.assertEqual("run_1", window._summary_labels["run_id"].text())
            self.assertEqual("2", window._summary_labels["candidate_count"].text())
            self.assertEqual("1", window._summary_labels["matched_count"].text())
            self.assertEqual("1 / 1", window._kpi_values["downloads"].text())
            window.close()

    def test_window_updates_button_states_for_common_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            services = {
                "auth": FakeAuthService(
                    {
                        "has_session": False,
                        "is_valid": False,
                        "last_checked_at": "",
                        "session": None,
                    }
                ),
                "workflow": FakeWorkflowService([], {}),
            }
            window = DesktopMainWindow(
                config_path="config.toml",
                verbose=False,
                service_factory=lambda _: services,
                settings=self._create_settings(root),
            )
            self._wait_for_window(window)

            self.assertTrue(window._start_login_button.isEnabled())
            self.assertFalse(window._preview_button.isEnabled())
            self.assertFalse(window._run_button.isEnabled())

            window._state.session_status = {
                "has_session": True,
                "is_valid": True,
                "last_checked_at": "2026-03-23T08:20:00+08:00",
                "session": build_session(),
            }
            window._state.selected_run_id = "run_1"
            window._summary_labels["output_dir"].setText(str(root))
            window._failed_model.from_tasks(
                [
                    DownloadTask(
                        task_id="task_1",
                        run_id="run_1",
                        note_id="note_1",
                        asset_id="asset_1",
                        source_url="https://example.com/1.jpg",
                        filename="001.jpg",
                        output_dir=str(root / "downloads" / "run_1" / "note_1"),
                        retry_count=1,
                        status=TaskStatus.FAILED,
                        error_message="下载失败",
                    )
                ],
                {"note_1": "https://example.com/note_1"},
            )
            window._sync_ui_state()
            self.assertTrue(window._preview_button.isEnabled())
            self.assertTrue(window._run_button.isEnabled())
            self.assertTrue(window._resume_button.isEnabled())

            window._state.busy_action = "run"
            window._sync_ui_state()
            self.assertFalse(window._preview_button.isEnabled())
            self.assertFalse(window._run_button.isEnabled())
            self.assertFalse(window._resume_button.isEnabled())

            window._state.busy_action = "login"
            window._state.pending_login_confirmation = True
            window._state.login_confirmation_sent = False
            window._sync_ui_state()
            self.assertFalse(window._start_login_button.isEnabled())
            self.assertTrue(window._confirm_login_button.isEnabled())

            window._state.login_confirmation_sent = True
            window._sync_ui_state()
            self.assertFalse(window._confirm_login_button.isEnabled())
            window.close()
