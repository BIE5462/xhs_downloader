from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..domain.models import (
    AccountSession,
    DownloadTask,
    FailureRecord,
    JobStatus,
    NoteRecord,
    NoteSummary,
    SearchJob,
    TaskStatus,
    account_session_from_dict,
    download_task_from_dict,
    note_record_from_dict,
    note_summary_from_dict,
    search_job_from_dict,
)
from ..infra.utils import dump_json, parse_json, utc_now_iso


class SQLiteRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    is_valid INTEGER NOT NULL,
                    last_checked_at TEXT NOT NULL,
                    storage_state_path TEXT NOT NULL,
                    browser_profile_dir TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    run_id TEXT PRIMARY KEY,
                    keyword TEXT NOT NULL,
                    pages INTEGER NOT NULL,
                    sort TEXT NOT NULL,
                    min_likes INTEGER NOT NULL,
                    min_comments INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    message TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS note_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    note_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    like_count INTEGER NOT NULL,
                    comment_count INTEGER NOT NULL,
                    note_url TEXT NOT NULL,
                    search_rank INTEGER NOT NULL,
                    raw_payload TEXT NOT NULL,
                    UNIQUE(run_id, note_id)
                );

                CREATE TABLE IF NOT EXISTS note_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    note_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    note_url TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(run_id, note_id)
                );

                CREATE TABLE IF NOT EXISTS download_tasks (
                    task_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    note_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    retry_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    UNIQUE(run_id, asset_id)
                );

                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    retryable INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def upsert_session(self, session: AccountSession) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, is_valid, last_checked_at, storage_state_path, browser_profile_dir
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    is_valid = excluded.is_valid,
                    last_checked_at = excluded.last_checked_at,
                    storage_state_path = excluded.storage_state_path,
                    browser_profile_dir = excluded.browser_profile_dir
                """,
                (
                    session.session_id,
                    1 if session.is_valid else 0,
                    session.last_checked_at,
                    session.storage_state_path,
                    session.browser_profile_dir,
                ),
            )

    def get_latest_session(self) -> Optional[AccountSession]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, is_valid, last_checked_at, storage_state_path, browser_profile_dir
                FROM sessions
                ORDER BY last_checked_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return account_session_from_dict(dict(row))

    def create_job(self, job: SearchJob) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    run_id, keyword, pages, sort, min_likes, min_comments, status, mode,
                    created_at, updated_at, output_dir, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.run_id,
                    job.keyword,
                    job.pages,
                    job.sort,
                    job.filters.min_likes,
                    job.filters.min_comments,
                    job.status.value,
                    job.mode,
                    job.created_at,
                    job.updated_at,
                    job.output_dir,
                    job.message,
                ),
            )

    def update_job(
        self,
        run_id: str,
        status: JobStatus,
        message: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            current = conn.execute(
                "SELECT message, output_dir FROM jobs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if current is None:
                return
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, message = ?, output_dir = ?
                WHERE run_id = ?
                """,
                (
                    status.value,
                    utc_now_iso(),
                    message if message is not None else current["message"],
                    output_dir if output_dir is not None else current["output_dir"],
                    run_id,
                ),
            )

    def get_job(self, run_id: str) -> Optional[SearchJob]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        return search_job_from_dict(
            {
                **data,
                "filters": {
                    "min_likes": data["min_likes"],
                    "min_comments": data["min_comments"],
                },
            }
        )

    def get_latest_job(self) -> Optional[SearchJob]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        return search_job_from_dict(
            {
                **data,
                "filters": {
                    "min_likes": data["min_likes"],
                    "min_comments": data["min_comments"],
                },
            }
        )

    def list_jobs(self, limit: int = 20) -> List[SearchJob]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        results: List[SearchJob] = []
        for row in rows:
            data = dict(row)
            results.append(
                search_job_from_dict(
                    {
                        **data,
                        "filters": {
                            "min_likes": data["min_likes"],
                            "min_comments": data["min_comments"],
                        },
                    }
                )
            )
        return results

    def save_note_summary(self, run_id: str, summary: NoteSummary) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO note_summaries (
                    run_id, note_id, title, author_name, like_count, comment_count,
                    note_url, search_rank, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, note_id) DO UPDATE SET
                    title = excluded.title,
                    author_name = excluded.author_name,
                    like_count = excluded.like_count,
                    comment_count = excluded.comment_count,
                    note_url = excluded.note_url,
                    search_rank = excluded.search_rank,
                    raw_payload = excluded.raw_payload
                """,
                (
                    run_id,
                    summary.note_id,
                    summary.title,
                    summary.author_name,
                    summary.like_count,
                    summary.comment_count,
                    summary.note_url,
                    summary.search_rank,
                    dump_json(summary.raw_payload),
                ),
            )

    def list_note_summaries(self, run_id: str) -> List[NoteSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT note_id, title, author_name, like_count, comment_count, note_url, search_rank, raw_payload
                FROM note_summaries
                WHERE run_id = ?
                ORDER BY search_rank ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            note_summary_from_dict(
                {
                    **dict(row),
                    "raw_payload": parse_json(row["raw_payload"], {}),
                }
            )
            for row in rows
        ]

    def save_note_record(self, run_id: str, record: NoteRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO note_records (run_id, note_id, title, author_name, published_at, note_url, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, note_id) DO UPDATE SET
                    title = excluded.title,
                    author_name = excluded.author_name,
                    published_at = excluded.published_at,
                    note_url = excluded.note_url,
                    payload = excluded.payload
                """,
                (
                    run_id,
                    record.note_id,
                    record.title,
                    record.author_name,
                    record.published_at,
                    record.note_url,
                    dump_json(record),
                ),
            )

    def list_note_records(self, run_id: str) -> List[NoteRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM note_records WHERE run_id = ? ORDER BY note_id ASC",
                (run_id,),
            ).fetchall()
        return [note_record_from_dict(parse_json(row["payload"], {})) for row in rows]

    def get_note_record(self, run_id: str, note_id: str) -> Optional[NoteRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM note_records WHERE run_id = ? AND note_id = ?",
                (run_id, note_id),
            ).fetchone()
        if row is None:
            return None
        return note_record_from_dict(parse_json(row["payload"], {}))

    def save_download_task(self, task: DownloadTask) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO download_tasks (
                    task_id, run_id, note_id, asset_id, source_url, filename,
                    output_dir, retry_count, status, local_path, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    filename = excluded.filename,
                    output_dir = excluded.output_dir,
                    retry_count = excluded.retry_count,
                    status = excluded.status,
                    local_path = excluded.local_path,
                    error_message = excluded.error_message
                """,
                (
                    task.task_id,
                    task.run_id,
                    task.note_id,
                    task.asset_id,
                    task.source_url,
                    task.filename,
                    task.output_dir,
                    task.retry_count,
                    task.status.value,
                    task.local_path,
                    task.error_message,
                ),
            )

    def list_download_tasks(
        self,
        run_id: str,
        statuses: Optional[Sequence[TaskStatus]] = None,
    ) -> List[DownloadTask]:
        sql = """
            SELECT task_id, run_id, note_id, asset_id, source_url, filename,
                   output_dir, retry_count, status, local_path, error_message
            FROM download_tasks
            WHERE run_id = ?
        """
        params: List[object] = [run_id]
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            sql += f" AND status IN ({placeholders})"
            params.extend(status.value for status in statuses)
        sql += " ORDER BY note_id ASC, filename ASC"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [download_task_from_dict(dict(row)) for row in rows]

    def update_download_task(
        self,
        task_id: str,
        status: TaskStatus,
        retry_count: Optional[int] = None,
        local_path: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT retry_count, local_path, error_message
                FROM download_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if current is None:
                return
            conn.execute(
                """
                UPDATE download_tasks
                SET status = ?, retry_count = ?, local_path = ?, error_message = ?
                WHERE task_id = ?
                """,
                (
                    status.value,
                    retry_count if retry_count is not None else current["retry_count"],
                    local_path if local_path is not None else current["local_path"],
                    error_message if error_message is not None else current["error_message"],
                    task_id,
                ),
            )

    def record_failure(self, failure: FailureRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO failures (run_id, entity_type, entity_id, error_type, message, retryable, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    failure.run_id,
                    failure.entity_type,
                    failure.entity_id,
                    failure.error_type.value,
                    failure.message,
                    1 if failure.retryable else 0,
                    failure.created_at,
                ),
            )

    def get_run_stats(self, run_id: str) -> Dict[str, int]:
        with self._connect() as conn:
            summary_count = conn.execute(
                "SELECT COUNT(*) AS count FROM note_summaries WHERE run_id = ?",
                (run_id,),
            ).fetchone()["count"]
            record_count = conn.execute(
                "SELECT COUNT(*) AS count FROM note_records WHERE run_id = ?",
                (run_id,),
            ).fetchone()["count"]
            task_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM download_tasks
                WHERE run_id = ?
                GROUP BY status
                """,
                (run_id,),
            ).fetchall()
            failure_count = conn.execute(
                "SELECT COUNT(*) AS count FROM failures WHERE run_id = ?",
                (run_id,),
            ).fetchone()["count"]

        task_counts = {row["status"]: row["count"] for row in task_rows}
        return {
            "summary_count": summary_count,
            "record_count": record_count,
            "download_pending": int(task_counts.get(TaskStatus.PENDING.value, 0)),
            "download_running": int(task_counts.get(TaskStatus.RUNNING.value, 0)),
            "download_success": int(task_counts.get(TaskStatus.SUCCESS.value, 0)),
            "download_failed": int(task_counts.get(TaskStatus.FAILED.value, 0)),
            "download_skipped": int(task_counts.get(TaskStatus.SKIPPED.value, 0)),
            "failure_count": failure_count,
        }
