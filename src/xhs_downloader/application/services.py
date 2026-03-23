from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..adapters.browser import PlaywrightBrowserClient
from ..adapters.downloader import ImageDownloader
from ..adapters.storage import SQLiteRepository
from ..config import AppConfig
from ..domain.errors import AuthExpiredError, DownloadError, ParseError, RateLimitedError, XHSError
from ..domain.filters import dedupe_summaries, filter_summaries
from ..domain.models import (
    AccountSession,
    DownloadTask,
    ErrorType,
    FailureRecord,
    ImageAsset,
    JobStatus,
    NoteRecord,
    SearchFilters,
    SearchJob,
    TaskStatus,
)
from ..infra.logging import get_logger
from ..infra.utils import (
    build_note_output_dir,
    build_run_root,
    dump_json,
    ensure_directory,
    generate_run_id,
    guess_extension_from_url,
    sha1_text,
    utc_now_iso,
)


class AuthService:
    def __init__(self, repository: SQLiteRepository, browser_client: PlaywrightBrowserClient, config: AppConfig) -> None:
        self._repository = repository
        self._browser_client = browser_client
        self._config = config

    def login(
        self,
        profile_dir: Optional[str] = None,
        wait_for_confirmation: Optional[Callable[[], None]] = None,
    ) -> AccountSession:
        browser_profile_dir = Path(profile_dir) if profile_dir else self._config.browser_profile_dir
        result = self._browser_client.login_and_save_session(
            storage_state_path=self._config.storage_state_path,
            browser_profile_dir=browser_profile_dir,
            wait_for_confirmation=wait_for_confirmation,
        )
        session = AccountSession(
            session_id=sha1_text(f"{self._config.storage_state_path}:{utc_now_iso()}"),
            is_valid=result["is_valid"],
            last_checked_at=utc_now_iso(),
            storage_state_path=str(self._config.storage_state_path),
            browser_profile_dir=str(browser_profile_dir),
        )
        self._repository.upsert_session(session)
        return session

    def ensure_valid_session(self) -> AccountSession:
        session = self._repository.get_latest_session()
        if session is None:
            raise AuthExpiredError("未找到登录态，请先执行 xhs login")

        session.is_valid = self._browser_client.validate_session(Path(session.storage_state_path))
        session.last_checked_at = utc_now_iso()
        self._repository.upsert_session(session)
        if not session.is_valid:
            raise AuthExpiredError("登录态已失效，请重新执行 xhs login")
        return session

    def get_session_status(self, validate: bool = False) -> Dict[str, Any]:
        session = self._repository.get_latest_session()
        if session is None:
            return {
                "has_session": False,
                "is_valid": False,
                "last_checked_at": "",
                "session": None,
            }

        if validate:
            session.is_valid = self._browser_client.validate_session(Path(session.storage_state_path))
            session.last_checked_at = utc_now_iso()
            self._repository.upsert_session(session)

        return {
            "has_session": True,
            "is_valid": session.is_valid,
            "last_checked_at": session.last_checked_at,
            "session": session,
        }


class SearchWorkflowService:
    def __init__(
        self,
        repository: SQLiteRepository,
        browser_client: PlaywrightBrowserClient,
        downloader: ImageDownloader,
        auth_service: AuthService,
        config: AppConfig,
    ) -> None:
        self._repository = repository
        self._browser_client = browser_client
        self._downloader = downloader
        self._auth_service = auth_service
        self._config = config
        self._logger = get_logger(self.__class__.__name__)

    def preview(
        self,
        keyword: str,
        pages: int,
        sort: str,
        min_likes: int,
        min_comments: int,
    ) -> Dict[str, Any]:
        filters = SearchFilters(min_likes=min_likes, min_comments=min_comments)
        job = self._create_job(keyword, pages, sort, filters, mode="preview")
        self._repository.create_job(job)

        try:
            self._auth_service.ensure_valid_session()
            job.status = JobStatus.RUNNING
            self._repository.update_job(job.run_id, job.status)

            with self._browser_client.open_session(self._config.storage_state_path) as session:
                try:
                    summaries = dedupe_summaries(session.search_notes(keyword, pages, sort))
                except RateLimitedError as exc:
                    self._block_job_for_risk(job, session, "job", job.run_id, str(exc))
                    raise

            for summary in summaries:
                self._repository.save_note_summary(job.run_id, summary)

            filtered = filter_summaries(summaries, filters)
            job.status = JobStatus.COMPLETED
            job.message = f"预览完成，候选 {len(summaries)}，命中 {len(filtered)}"
            self._repository.update_job(job.run_id, job.status, message=job.message)
            return {
                "run_id": job.run_id,
                "mode": job.mode,
                "keyword": keyword,
                "pages": pages,
                "sort": sort,
                "filters": filters,
                "candidate_count": len(summaries),
                "matched_count": len(filtered),
                "matched": filtered[:20],
            }
        except AuthExpiredError as exc:
            job.status = JobStatus.BLOCKED_AUTH
            job.message = str(exc)
            self._repository.update_job(job.run_id, job.status, message=job.message)
            raise
        except RateLimitedError:
            raise
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.message = str(exc)
            self._record_failure(job.run_id, "job", job.run_id, ErrorType.SEARCH_PAGE_PARSE_FAILED, str(exc), False)
            self._repository.update_job(job.run_id, job.status, message=job.message)
            raise

    def run(
        self,
        keyword: str,
        pages: int,
        sort: str,
        min_likes: int,
        min_comments: int,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        filters = SearchFilters(min_likes=min_likes, min_comments=min_comments)
        run_id = generate_run_id(keyword)
        run_root = build_run_root(Path(output_dir) if output_dir else self._config.download_root, keyword, run_id)
        job = SearchJob(
            run_id=run_id,
            keyword=keyword,
            pages=pages,
            sort=sort,
            filters=filters,
            status=JobStatus.PENDING,
            mode="run",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
            output_dir=str(run_root),
            message="",
        )
        self._repository.create_job(job)

        try:
            self._auth_service.ensure_valid_session()
            job.status = JobStatus.RUNNING
            self._repository.update_job(job.run_id, job.status, output_dir=job.output_dir)

            with self._browser_client.open_session(self._config.storage_state_path) as browser_session:
                try:
                    summaries = dedupe_summaries(browser_session.search_notes(keyword, pages, sort))
                    for summary in summaries:
                        self._repository.save_note_summary(job.run_id, summary)

                    filtered = filter_summaries(summaries, filters)
                    for summary in filtered:
                        try:
                            record = browser_session.fetch_note_detail(summary)
                            record.images = self._prepare_assets(record)
                            self._repository.save_note_record(job.run_id, record)
                            self._download_note(job, record, browser_session)
                        except RateLimitedError as exc:
                            self._block_job_for_risk(job, browser_session, "note", summary.note_id, str(exc))
                            raise
                        except ParseError as exc:
                            self._record_failure(
                                job.run_id,
                                "note",
                                summary.note_id,
                                ErrorType.NOTE_DETAIL_PARSE_FAILED,
                                str(exc),
                                False,
                            )
                except RateLimitedError as exc:
                    if job.status != JobStatus.BLOCKED_RISK:
                        self._block_job_for_risk(job, browser_session, "job", job.run_id, str(exc))
                    raise

            stats = self._repository.get_run_stats(job.run_id)
            job.status = JobStatus.PARTIAL if stats["failure_count"] or stats["download_failed"] else JobStatus.COMPLETED
            job.message = f"运行完成，候选 {len(summaries)}，命中 {len(filtered)}，下载成功 {stats['download_success']}"
            self._repository.update_job(job.run_id, job.status, message=job.message)
            return self._write_run_summary(job)
        except AuthExpiredError as exc:
            job.status = JobStatus.BLOCKED_AUTH
            job.message = str(exc)
            self._repository.update_job(job.run_id, job.status, message=job.message)
            raise
        except RateLimitedError:
            raise
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.message = str(exc)
            self._record_failure(job.run_id, "job", job.run_id, ErrorType.UNKNOWN, str(exc), False)
            self._repository.update_job(job.run_id, job.status, message=job.message)
            raise

    def resume(self, run_id: str) -> Dict[str, Any]:
        job = self._repository.get_job(run_id)
        if job is None:
            raise XHSError(f"未找到任务: {run_id}")

        pending_statuses = [TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.RUNNING]
        tasks = self._repository.list_download_tasks(run_id, pending_statuses)
        if not tasks:
            return self._write_run_summary(job)

        self._auth_service.ensure_valid_session()
        job.status = JobStatus.RUNNING
        job.message = "恢复下载中"
        self._repository.update_job(run_id, job.status, message=job.message)

        touched_notes = set()
        note_url_cache: Dict[str, str] = {}
        with self._browser_client.open_session(self._config.storage_state_path) as browser_session:
            try:
                for task in tasks:
                    retry_count = task.retry_count + 1
                    referer_url = note_url_cache.get(task.note_id, "")
                    if not referer_url:
                        record = self._repository.get_note_record(run_id, task.note_id)
                        if record is not None:
                            referer_url = record.note_url
                            note_url_cache[task.note_id] = referer_url
                    try:
                        self._repository.update_download_task(task.task_id, TaskStatus.RUNNING, retry_count=retry_count)
                        local_path = self._download_asset(task, referer_url, browser_session)
                        self._repository.update_download_task(
                            task.task_id,
                            TaskStatus.SUCCESS,
                            retry_count=retry_count,
                            local_path=str(local_path),
                            error_message="",
                        )
                        touched_notes.add(task.note_id)
                    except RateLimitedError as exc:
                        self._repository.update_download_task(
                            task.task_id,
                            TaskStatus.FAILED,
                            retry_count=retry_count,
                            error_message=str(exc),
                        )
                        self._record_failure(
                            run_id,
                            "download_task",
                            task.task_id,
                            ErrorType.RATE_LIMITED,
                            str(exc),
                            True,
                        )
                        touched_notes.add(task.note_id)
                        self._sync_touched_notes(job, run_id, touched_notes)
                        self._block_job_for_risk(job, browser_session, "download_task", task.task_id, str(exc))
                        raise
                    except DownloadError as exc:
                        error_type = self._classify_download_error(str(exc))
                        self._repository.update_download_task(
                            task.task_id,
                            TaskStatus.FAILED,
                            retry_count=retry_count,
                            error_message=str(exc),
                        )
                        self._record_failure(
                            run_id,
                            "download_task",
                            task.task_id,
                            error_type,
                            str(exc),
                            error_type != ErrorType.IMAGE_UNAVAILABLE,
                        )
                        touched_notes.add(task.note_id)
            except RateLimitedError:
                raise

        self._sync_touched_notes(job, run_id, touched_notes)

        stats = self._repository.get_run_stats(run_id)
        job.status = JobStatus.PARTIAL if stats["failure_count"] or stats["download_failed"] else JobStatus.COMPLETED
        job.message = "恢复下载完成"
        self._repository.update_job(run_id, job.status, message=job.message)
        return self._write_run_summary(job)

    def list_jobs(self, limit: int = 20) -> Dict[str, Any]:
        jobs = self._repository.list_jobs(limit)
        return {"jobs": jobs}

    def status(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        job = self._repository.get_job(run_id) if run_id else self._repository.get_latest_job()
        if job is None:
            raise XHSError("未找到任何任务记录")
        stats = self._repository.get_run_stats(job.run_id)
        return {"job": job, "stats": stats}

    def get_run_details(self, run_id: str) -> Dict[str, Any]:
        job = self._repository.get_job(run_id)
        if job is None:
            raise XHSError(f"未找到任务: {run_id}")

        stats = self._repository.get_run_stats(run_id)
        summaries = self._repository.list_note_summaries(run_id)
        matched_summaries = filter_summaries(summaries, job.filters)
        records = self._repository.list_note_records(run_id)
        failed_tasks = self._repository.list_download_tasks(run_id, [TaskStatus.FAILED])
        return {
            "job": job,
            "stats": stats,
            "summaries": summaries,
            "matched_summaries": matched_summaries,
            "records": records,
            "failed_tasks": failed_tasks,
        }

    def _create_job(
        self,
        keyword: str,
        pages: int,
        sort: str,
        filters: SearchFilters,
        mode: str,
    ) -> SearchJob:
        now = utc_now_iso()
        return SearchJob(
            run_id=generate_run_id(keyword),
            keyword=keyword,
            pages=pages,
            sort=sort,
            filters=filters,
            status=JobStatus.PENDING,
            mode=mode,
            created_at=now,
            updated_at=now,
        )

    def _prepare_assets(self, record: NoteRecord) -> List[ImageAsset]:
        results: List[ImageAsset] = []
        seen = set()
        for index, source_url in enumerate(record.images, start=1):
            if source_url in seen:
                continue
            seen.add(source_url)
            extension = guess_extension_from_url(source_url)
            filename = f"{index:03d}{extension}"
            results.append(
                ImageAsset(
                    asset_id=sha1_text(f"{record.note_id}:{source_url}"),
                    note_id=record.note_id,
                    source_url=source_url,
                    index=index,
                    filename=filename,
                    source_url_hash=sha1_text(source_url),
                )
            )
        return results

    def _download_note(self, job: SearchJob, record: NoteRecord, browser_session: Any) -> None:
        note_dir = build_note_output_dir(Path(job.output_dir), record.note_id)
        for asset in record.images:
            task = DownloadTask(
                task_id=sha1_text(f"{job.run_id}:{asset.asset_id}"),
                run_id=job.run_id,
                note_id=record.note_id,
                asset_id=asset.asset_id,
                source_url=asset.source_url,
                filename=asset.filename,
                output_dir=str(note_dir),
                retry_count=0,
                status=TaskStatus.PENDING,
            )
            self._repository.save_download_task(task)
            retry_count = task.retry_count + 1
            try:
                self._repository.update_download_task(task.task_id, TaskStatus.RUNNING, retry_count=retry_count)
                local_path = self._download_asset(task, record.note_url, browser_session)
                asset.local_path = str(local_path)
                asset.download_status = TaskStatus.SUCCESS
                self._repository.update_download_task(
                    task.task_id,
                    TaskStatus.SUCCESS,
                    retry_count=retry_count,
                    local_path=str(local_path),
                    error_message="",
                )
            except RateLimitedError as exc:
                asset.download_status = TaskStatus.FAILED
                self._repository.update_download_task(
                    task.task_id,
                    TaskStatus.FAILED,
                    retry_count=retry_count,
                    error_message=str(exc),
                )
                self._record_failure(
                    job.run_id,
                    "download_task",
                    task.task_id,
                    ErrorType.RATE_LIMITED,
                    str(exc),
                    True,
                )
                self._repository.save_note_record(job.run_id, record)
                self._write_manifest(job, record)
                raise
            except DownloadError as exc:
                error_type = self._classify_download_error(str(exc))
                asset.download_status = TaskStatus.FAILED
                self._repository.update_download_task(
                    task.task_id,
                    TaskStatus.FAILED,
                    retry_count=retry_count,
                    error_message=str(exc),
                )
                self._record_failure(
                    job.run_id,
                    "download_task",
                    task.task_id,
                    error_type,
                    str(exc),
                    error_type != ErrorType.IMAGE_UNAVAILABLE,
                )

        self._repository.save_note_record(job.run_id, record)
        self._write_manifest(job, record)

    def _download_asset(self, task: DownloadTask, referer_url: str, browser_session: Any) -> Path:
        transport = (self._config.download_transport or "browser_context").strip().lower()
        if transport == "http":
            return self._downloader.download(task)
        return browser_session.download_image(task, referer_url)

    def _classify_download_error(self, message: str) -> ErrorType:
        lowered = (message or "").lower()
        if "图片资源不可用" in message:
            return ErrorType.IMAGE_UNAVAILABLE
        if "http error 404" in lowered or "http error 410" in lowered or "status=404" in lowered or "status=410" in lowered:
            return ErrorType.IMAGE_UNAVAILABLE
        return ErrorType.DOWNLOAD_TIMEOUT

    def _sync_touched_notes(self, job: SearchJob, run_id: str, note_ids: set[str]) -> None:
        for note_id in note_ids:
            record = self._repository.get_note_record(run_id, note_id)
            if record is None:
                continue
            refreshed = self._refresh_record_assets(run_id, record)
            self._repository.save_note_record(run_id, refreshed)
            self._write_manifest(job, refreshed)

    def _block_job_for_risk(
        self,
        job: SearchJob,
        browser_session: Any,
        entity_type: str,
        entity_id: str,
        message: str,
    ) -> None:
        artifact_root = self._artifact_root(job)
        prefix = f"{entity_type}_{sha1_text(f'{job.run_id}:{entity_type}:{entity_id}')[:12]}"
        captures = browser_session.capture_diagnostics(artifact_root, prefix) if browser_session is not None else []
        final_message = self._message_with_artifacts(message, captures)
        self._record_failure(job.run_id, entity_type, entity_id, ErrorType.RATE_LIMITED, final_message, True)
        job.status = JobStatus.BLOCKED_RISK
        job.message = final_message
        self._repository.update_job(job.run_id, job.status, message=job.message)

    def _artifact_root(self, job: SearchJob) -> Path:
        if job.output_dir:
            return ensure_directory(Path(job.output_dir) / "_artifacts")
        return ensure_directory(self._config.data_dir / "risk_artifacts" / job.run_id)

    def _message_with_artifacts(self, message: str, captures: List[str]) -> str:
        if not captures:
            return message
        return f"{message} | screenshots={'; '.join(captures)}"

    def _refresh_record_assets(self, run_id: str, record: NoteRecord) -> NoteRecord:
        tasks = self._repository.list_download_tasks(run_id)
        mapping = {task.asset_id: task for task in tasks}
        refreshed_assets: List[ImageAsset] = []
        for asset in record.images:
            task = mapping.get(asset.asset_id)
            if task:
                asset.download_status = task.status
                asset.local_path = task.local_path
            refreshed_assets.append(asset)
        record.images = refreshed_assets
        return record

    def _write_manifest(self, job: SearchJob, record: NoteRecord) -> None:
        note_dir = build_note_output_dir(Path(job.output_dir), record.note_id)
        manifest = {
            "run_id": job.run_id,
            "keyword": job.keyword,
            "filters": job.filters,
            "note": record,
            "downloaded_at": utc_now_iso(),
        }
        manifest_path = note_dir / "manifest.json"
        manifest_path.write_text(dump_json(manifest), encoding="utf-8")

    def _write_run_summary(self, job: SearchJob) -> Dict[str, Any]:
        stats = self._repository.get_run_stats(job.run_id)
        payload = {
            "run_id": job.run_id,
            "keyword": job.keyword,
            "pages": job.pages,
            "sort": job.sort,
            "filters": job.filters,
            "status": job.status,
            "output_dir": job.output_dir,
            "stats": stats,
            "updated_at": utc_now_iso(),
            "message": job.message,
        }
        if job.output_dir:
            summary_path = Path(job.output_dir) / "run_summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(dump_json(payload), encoding="utf-8")
        return payload

    def _record_failure(
        self,
        run_id: str,
        entity_type: str,
        entity_id: str,
        error_type: ErrorType,
        message: str,
        retryable: bool,
    ) -> None:
        self._repository.record_failure(
            FailureRecord(
                run_id=run_id,
                entity_type=entity_type,
                entity_id=entity_id,
                error_type=error_type,
                message=message,
                retryable=retryable,
                created_at=utc_now_iso(),
            )
        )
