from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from xhs_downloader.adapters.storage import SQLiteRepository
from xhs_downloader.application.services import AuthService, SearchWorkflowService
from xhs_downloader.config import AppConfig
from xhs_downloader.domain.models import (
    AccountSession,
    DownloadTask,
    JobStatus,
    NoteRecord,
    NoteSummary,
    SearchFilters,
    SearchJob,
    TaskStatus,
)


def build_config(root: Path) -> AppConfig:
    config = AppConfig(
        data_dir=root / "runtime",
        browser_profile_dir=root / "runtime" / "browser-profile",
        storage_state_path=root / "runtime" / "storage_state.json",
        db_path=root / "runtime" / "xhs.sqlite3",
        download_root=root / "downloads",
        headless=False,
        crawl_delay_ms=0,
        search_page_wait_ms=0,
        note_detail_wait_ms=0,
        detail_delay_ms=0,
        download_delay_ms=0,
        request_jitter_ms=0,
        max_retries=0,
        download_timeout=3,
        download_transport="browser_context",
        protection_mode="pause",
        screenshot_on_failure=True,
        user_agent="Mozilla/5.0 Test",
    )
    config.ensure_directories()
    return config


class FakeBrowserClient:
    def __init__(self) -> None:
        self.validation_result = True
        self.last_wait_for_confirmation = None
        self.validate_paths: list[Path] = []

    def login_and_save_session(
        self,
        storage_state_path: Path,
        browser_profile_dir: Path,
        wait_for_confirmation=None,
    ) -> dict[str, object]:
        self.last_wait_for_confirmation = wait_for_confirmation
        browser_profile_dir.mkdir(parents=True, exist_ok=True)
        storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        storage_state_path.write_text("{}", encoding="utf-8")
        if wait_for_confirmation is not None:
            wait_for_confirmation()
        return {"is_valid": True, "cookie_count": 2}

    def validate_session(self, storage_state_path: Path) -> bool:
        self.validate_paths.append(storage_state_path)
        return self.validation_result


class ServicesTests(unittest.TestCase):
    def test_auth_service_login_supports_cli_default_and_gui_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = SQLiteRepository(root / "test.sqlite3")
            repository.initialize()
            browser = FakeBrowserClient()
            service = AuthService(repository, browser, build_config(root))

            session = service.login()
            self.assertIsInstance(session, AccountSession)
            self.assertIsNone(browser.last_wait_for_confirmation)

            called = {"count": 0}

            def confirm() -> None:
                called["count"] += 1

            session = service.login(wait_for_confirmation=confirm)
            self.assertTrue(session.is_valid)
            self.assertEqual(1, called["count"])

    def test_get_session_status_handles_missing_and_validated_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = SQLiteRepository(root / "test.sqlite3")
            repository.initialize()
            browser = FakeBrowserClient()
            service = AuthService(repository, browser, build_config(root))

            missing = service.get_session_status()
            self.assertFalse(missing["has_session"])
            self.assertFalse(missing["is_valid"])

            service.login(wait_for_confirmation=lambda: None)
            status = service.get_session_status(validate=False)
            self.assertTrue(status["has_session"])
            self.assertTrue(status["is_valid"])

            browser.validation_result = False
            validated = service.get_session_status(validate=True)
            self.assertTrue(validated["has_session"])
            self.assertFalse(validated["is_valid"])
            self.assertEqual(1, len(browser.validate_paths))

    def test_get_run_details_aggregates_matched_notes_and_failed_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = SQLiteRepository(root / "test.sqlite3")
            repository.initialize()
            config = build_config(root)

            job = SearchJob(
                run_id="run_1",
                keyword="穿搭",
                pages=3,
                sort="comprehensive",
                filters=SearchFilters(min_likes=100, min_comments=5),
                status=JobStatus.PARTIAL,
                mode="run",
                created_at="2026-03-23T00:00:00+00:00",
                updated_at="2026-03-23T00:10:00+00:00",
                output_dir=str(root / "downloads" / "run_1"),
                message="测试任务",
            )
            repository.create_job(job)

            matched = NoteSummary(
                note_id="note_1",
                title="高点赞穿搭",
                author_name="作者A",
                like_count=300,
                comment_count=20,
                note_url="https://example.com/note_1",
                search_rank=1,
            )
            filtered_out = NoteSummary(
                note_id="note_2",
                title="普通穿搭",
                author_name="作者B",
                like_count=10,
                comment_count=1,
                note_url="https://example.com/note_2",
                search_rank=2,
            )
            repository.save_note_summary(job.run_id, matched)
            repository.save_note_summary(job.run_id, filtered_out)

            repository.save_note_record(
                job.run_id,
                NoteRecord(
                    note_id="note_1",
                    title="详情页标题",
                    description="描述",
                    author_id="author_1",
                    author_name="作者A",
                    published_at="2026-03-23",
                    tags=["穿搭"],
                    like_count=300,
                    comment_count=20,
                    note_url="https://example.com/note_1?detail=1",
                    images=[],
                ),
            )
            repository.save_download_task(
                DownloadTask(
                    task_id="task_1",
                    run_id=job.run_id,
                    note_id="note_1",
                    asset_id="asset_1",
                    source_url="https://example.com/1.jpg",
                    filename="001.jpg",
                    output_dir=str(root / "downloads" / "run_1" / "note_1"),
                    retry_count=1,
                    status=TaskStatus.FAILED,
                    error_message="下载失败",
                )
            )

            workflow = SearchWorkflowService(
                repository=repository,
                browser_client=FakeBrowserClient(),
                downloader=mock.Mock(),
                auth_service=mock.Mock(),
                config=config,
            )

            details = workflow.get_run_details(job.run_id)
            self.assertEqual("run_1", details["job"].run_id)
            self.assertEqual(2, len(details["summaries"]))
            self.assertEqual(1, len(details["matched_summaries"]))
            self.assertEqual("note_1", details["matched_summaries"][0].note_id)
            self.assertEqual(1, len(details["records"]))
            self.assertEqual(1, len(details["failed_tasks"]))
            self.assertEqual(2, details["stats"]["summary_count"])
            self.assertEqual(1, details["stats"]["download_failed"])
