from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    BLOCKED_AUTH = "blocked_auth"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED_AUTH = "blocked_auth"


class ErrorType(str, Enum):
    AUTH_EXPIRED = "AUTH_EXPIRED"
    SEARCH_PAGE_PARSE_FAILED = "SEARCH_PAGE_PARSE_FAILED"
    NOTE_DETAIL_PARSE_FAILED = "NOTE_DETAIL_PARSE_FAILED"
    DOWNLOAD_TIMEOUT = "DOWNLOAD_TIMEOUT"
    IMAGE_UNAVAILABLE = "IMAGE_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    FILESYSTEM_ERROR = "FILESYSTEM_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class SearchFilters:
    min_likes: int = 0
    min_comments: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_likes": self.min_likes,
            "min_comments": self.min_comments,
        }


@dataclass
class AccountSession:
    session_id: str
    is_valid: bool
    last_checked_at: str
    storage_state_path: str
    browser_profile_dir: str


@dataclass
class SearchJob:
    run_id: str
    keyword: str
    pages: int
    sort: str
    filters: SearchFilters
    status: JobStatus
    mode: str
    created_at: str
    updated_at: str
    output_dir: str = ""
    message: str = ""


@dataclass
class NoteSummary:
    note_id: str
    title: str
    author_name: str
    like_count: int
    comment_count: int
    note_url: str
    search_rank: int
    raw_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageAsset:
    asset_id: str
    note_id: str
    source_url: str
    index: int
    filename: str
    source_url_hash: str
    download_status: TaskStatus = TaskStatus.PENDING
    local_path: str = ""


@dataclass
class NoteRecord:
    note_id: str
    title: str
    description: str
    author_id: str
    author_name: str
    published_at: str
    tags: List[str]
    like_count: int
    comment_count: int
    note_url: str
    images: List[ImageAsset] = field(default_factory=list)


@dataclass
class DownloadTask:
    task_id: str
    run_id: str
    note_id: str
    asset_id: str
    source_url: str
    filename: str
    output_dir: str
    retry_count: int
    status: TaskStatus
    local_path: str = ""
    error_message: str = ""


@dataclass
class FailureRecord:
    run_id: str
    entity_type: str
    entity_id: str
    error_type: ErrorType
    message: str
    retryable: bool
    created_at: str


def account_session_from_dict(data: Dict[str, Any]) -> AccountSession:
    return AccountSession(
        session_id=data["session_id"],
        is_valid=bool(data["is_valid"]),
        last_checked_at=data["last_checked_at"],
        storage_state_path=data["storage_state_path"],
        browser_profile_dir=data.get("browser_profile_dir", ""),
    )


def search_job_from_dict(data: Dict[str, Any]) -> SearchJob:
    filters = data["filters"]
    if not isinstance(filters, SearchFilters):
        filters = SearchFilters(
            min_likes=int(filters.get("min_likes", 0)),
            min_comments=int(filters.get("min_comments", 0)),
        )
    return SearchJob(
        run_id=data["run_id"],
        keyword=data["keyword"],
        pages=int(data["pages"]),
        sort=data["sort"],
        filters=filters,
        status=JobStatus(data["status"]),
        mode=data["mode"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        output_dir=data.get("output_dir", ""),
        message=data.get("message", ""),
    )


def note_summary_from_dict(data: Dict[str, Any]) -> NoteSummary:
    return NoteSummary(
        note_id=data["note_id"],
        title=data.get("title", ""),
        author_name=data.get("author_name", ""),
        like_count=int(data.get("like_count", 0)),
        comment_count=int(data.get("comment_count", 0)),
        note_url=data.get("note_url", ""),
        search_rank=int(data.get("search_rank", 0)),
        raw_payload=data.get("raw_payload", {}),
    )


def image_asset_from_dict(data: Dict[str, Any]) -> ImageAsset:
    return ImageAsset(
        asset_id=data["asset_id"],
        note_id=data["note_id"],
        source_url=data["source_url"],
        index=int(data["index"]),
        filename=data["filename"],
        source_url_hash=data["source_url_hash"],
        download_status=TaskStatus(data.get("download_status", TaskStatus.PENDING.value)),
        local_path=data.get("local_path", ""),
    )


def note_record_from_dict(data: Dict[str, Any]) -> NoteRecord:
    images = [image_asset_from_dict(item) for item in data.get("images", [])]
    return NoteRecord(
        note_id=data["note_id"],
        title=data.get("title", ""),
        description=data.get("description", ""),
        author_id=data.get("author_id", ""),
        author_name=data.get("author_name", ""),
        published_at=data.get("published_at", ""),
        tags=list(data.get("tags", [])),
        like_count=int(data.get("like_count", 0)),
        comment_count=int(data.get("comment_count", 0)),
        note_url=data.get("note_url", ""),
        images=images,
    )


def download_task_from_dict(data: Dict[str, Any]) -> DownloadTask:
    return DownloadTask(
        task_id=data["task_id"],
        run_id=data["run_id"],
        note_id=data["note_id"],
        asset_id=data["asset_id"],
        source_url=data["source_url"],
        filename=data["filename"],
        output_dir=data["output_dir"],
        retry_count=int(data.get("retry_count", 0)),
        status=TaskStatus(data["status"]),
        local_path=data.get("local_path", ""),
        error_message=data.get("error_message", ""),
    )

