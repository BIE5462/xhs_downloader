from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from ..domain.models import DownloadTask, NoteSummary, SearchJob


STATUS_TEXT_MAP = {
    "pending": "待处理",
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "partial": "部分完成",
    "blocked_auth": "登录阻塞",
    "blocked_risk": "风控阻塞",
    "success": "成功",
    "skipped": "已跳过",
}

STATUS_COLOR_MAP = {
    "pending": QColor("#64748B"),
    "running": QColor("#2563EB"),
    "completed": QColor("#0F766E"),
    "failed": QColor("#DC2626"),
    "partial": QColor("#D97706"),
    "blocked_auth": QColor("#DC2626"),
    "blocked_risk": QColor("#EA580C"),
    "success": QColor("#0F766E"),
    "skipped": QColor("#64748B"),
}


def normalize_status(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "")


def display_status(value: Any) -> str:
    normalized = normalize_status(value)
    return STATUS_TEXT_MAP.get(normalized, normalized or "-")


@dataclass
class AppState:
    config_path: str = "config.toml"
    output_dir_override: str = ""
    session_status: Dict[str, Any] = field(
        default_factory=lambda: {
            "has_session": False,
            "is_valid": False,
            "last_checked_at": "",
            "session": None,
        }
    )
    jobs: List[SearchJob] = field(default_factory=list)
    selected_run_id: str = ""
    current_details: Dict[str, Any] = field(default_factory=dict)
    busy_action: str = ""
    pending_login_confirmation: bool = False
    login_confirmation_sent: bool = False


@dataclass
class NoteRow:
    note_id: str
    title: str
    author_name: str
    like_count: int
    comment_count: int
    note_url: str


@dataclass
class FailedTaskRow:
    task_id: str
    note_id: str
    filename: str
    retry_count: int
    status: str
    error_message: str
    output_dir: str
    note_url: str = ""


class JobsTableModel(QAbstractTableModel):
    HEADERS = ["运行 ID", "关键词", "模式", "状态", "创建时间", "输出目录"]

    def __init__(self) -> None:
        super().__init__()
        self._rows: List[SearchJob] = []

    def set_rows(self, rows: List[SearchJob]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, row: int) -> Optional[SearchJob]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        row = self._rows[index.row()]
        values = [
            row.run_id,
            row.keyword,
            row.mode,
            display_status(row.status),
            row.created_at,
            row.output_dir or "-",
        ]
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 3:
            return STATUS_COLOR_MAP.get(normalize_status(row.status))
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 5:
            return row.output_dir
        if role == Qt.ItemDataRole.UserRole:
            return row
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return section + 1


class NotesTableModel(QAbstractTableModel):
    HEADERS = ["标题", "作者", "点赞", "评论", "链接"]

    def __init__(self) -> None:
        super().__init__()
        self._rows: List[NoteRow] = []

    def set_rows(self, rows: List[NoteRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, row: int) -> Optional[NoteRow]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        row = self._rows[index.row()]
        values = [row.title, row.author_name, row.like_count, row.comment_count, row.note_url]
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole and index.column() in {0, 4}:
            return values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return row
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return section + 1


class FailedTasksTableModel(QAbstractTableModel):
    HEADERS = ["文件名", "笔记 ID", "重试次数", "状态", "错误信息"]

    def __init__(self) -> None:
        super().__init__()
        self._rows: List[FailedTaskRow] = []

    def set_rows(self, rows: List[FailedTaskRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, row: int) -> Optional[FailedTaskRow]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def from_tasks(self, tasks: List[DownloadTask], note_urls: Dict[str, str]) -> None:
        rows = [
            FailedTaskRow(
                task_id=task.task_id,
                note_id=task.note_id,
                filename=task.filename,
                retry_count=task.retry_count,
                status=normalize_status(task.status),
                error_message=task.error_message,
                output_dir=task.output_dir,
                note_url=note_urls.get(task.note_id, ""),
            )
            for task in tasks
        ]
        self.set_rows(rows)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        row = self._rows[index.row()]
        values = [
            row.filename,
            row.note_id,
            row.retry_count,
            display_status(row.status),
            row.error_message,
        ]
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 3:
            return STATUS_COLOR_MAP.get(normalize_status(row.status))
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 4:
            return row.error_message
        if role == Qt.ItemDataRole.UserRole:
            return row
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return section + 1
