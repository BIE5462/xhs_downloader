from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QSettings, Qt, QThreadPool, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QSpinBox,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..cli import build_services
from ..domain.errors import AuthExpiredError, DependencyMissingError, DownloadError, ParseError, RateLimitedError, XHSError
from ..infra.logging import configure_logging
from .models import (
    AppState,
    FailedTaskRow,
    FailedTasksTableModel,
    JobsTableModel,
    NoteRow,
    NotesTableModel,
    display_status,
)
from .styles import APP_STYLE_SHEET
from .workers import ServiceWorker


ServiceFactory = Callable[[str], Dict[str, Any]]


class DesktopMainWindow(QMainWindow):
    def __init__(
        self,
        config_path: str = "config.toml",
        verbose: bool = False,
        service_factory: ServiceFactory = build_services,
        settings: Optional[QSettings] = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("小红书下载工作台")
        self.resize(1440, 900)
        self.setMinimumSize(1280, 800)

        self._service_factory = service_factory
        self._settings = settings or QSettings("OpenAI", "xiaohongshu-downloader")
        self._thread_pool = QThreadPool(self)
        self._services: Optional[Dict[str, Any]] = None
        self._loaded_config_path = ""
        self._loaded_verbose = False
        self._selection_locked = False
        self._login_confirmation_event: Optional[Event] = None
        self._state = AppState(
            config_path=self._settings.value("desktop/config_path", config_path, type=str),
            output_dir_override=self._settings.value("desktop/output_dir", "", type=str),
        )

        self._jobs_model = JobsTableModel()
        self._notes_model = NotesTableModel()
        self._failed_model = FailedTasksTableModel()

        self._summary_labels: Dict[str, QLabel] = {}
        self._kpi_values: Dict[str, QLabel] = {}
        self._kpi_hints: Dict[str, QLabel] = {}

        self._build_ui(verbose)
        self._restore_settings()
        self._sync_ui_state()
        self._append_log("工作台已启动，正在加载任务和会话状态。")
        self.refresh_dashboard(validate_session=False)

    def _build_ui(self, verbose: bool) -> None:
        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)

        self._banner = QLabel("", central)
        self._banner.setObjectName("Banner")
        self._banner.setWordWrap(True)
        self._banner.hide()
        root_layout.addWidget(self._banner)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self._splitter.addWidget(self._build_left_panel(verbose))
        self._splitter.addWidget(self._build_center_panel())
        self._splitter.addWidget(self._build_right_panel())
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 1)
        root_layout.addWidget(self._splitter, 1)

        self.setCentralWidget(central)
        self.setStyleSheet(APP_STYLE_SHEET)

    def _build_left_panel(self, verbose: bool) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        login_card, login_layout = self._create_card("账号状态")
        self._session_badge = QLabel("未登录", login_card)
        self._session_badge.setObjectName("BadgeLabel")
        self._session_hint = QLabel("未检测到本地登录态，请先完成登录。", login_card)
        self._session_hint.setWordWrap(True)
        self._session_checked = QLabel("最近校验: -", login_card)

        self._start_login_button = self._create_button("开始登录")
        self._confirm_login_button = self._create_button("已完成登录并保存", variant="accent")
        self._start_login_button.clicked.connect(lambda *_: self._start_login())
        self._confirm_login_button.clicked.connect(lambda *_: self._confirm_login())

        login_layout.addWidget(self._session_badge)
        login_layout.addWidget(self._session_hint)
        login_layout.addWidget(self._session_checked)

        login_buttons = QHBoxLayout()
        login_buttons.setSpacing(8)
        login_buttons.addWidget(self._start_login_button)
        login_buttons.addWidget(self._confirm_login_button)
        login_layout.addLayout(login_buttons)
        layout.addWidget(login_card)

        search_card, search_layout = self._create_card("搜索与下载")
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._keyword_input = QLineEdit(search_card)
        self._pages_spin = QSpinBox(search_card)
        self._pages_spin.setRange(1, 50)
        self._pages_spin.setValue(3)

        self._sort_combo = QComboBox(search_card)
        self._sort_combo.addItem("综合", "comprehensive")
        self._sort_combo.addItem("最新", "latest")
        self._sort_combo.addItem("热度", "hot")

        self._min_likes_spin = QSpinBox(search_card)
        self._min_likes_spin.setRange(0, 999999999)
        self._min_comments_spin = QSpinBox(search_card)
        self._min_comments_spin.setRange(0, 999999999)

        self._output_input = QLineEdit(self._state.output_dir_override, search_card)
        self._browse_output_button = self._create_button("浏览", variant="secondary")
        self._browse_output_button.clicked.connect(lambda *_: self._browse_output_dir())

        output_row = QWidget(search_card)
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(8)
        output_layout.addWidget(self._output_input, 1)
        output_layout.addWidget(self._browse_output_button)

        form.addRow("关键词", self._keyword_input)
        form.addRow("抓取页数", self._pages_spin)
        form.addRow("排序方式", self._sort_combo)
        form.addRow("最低点赞", self._min_likes_spin)
        form.addRow("最低评论", self._min_comments_spin)
        form.addRow("输出目录", output_row)
        search_layout.addLayout(form)

        settings_group = QGroupBox("常用设置", search_card)
        settings_group.setCheckable(True)
        settings_group.setChecked(True)
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setContentsMargins(12, 16, 12, 12)
        settings_layout.setSpacing(10)

        self._config_input = QLineEdit(self._state.config_path, settings_group)
        self._browse_config_button = self._create_button("浏览", variant="secondary")
        self._browse_config_button.clicked.connect(lambda *_: self._browse_config_path())
        self._verbose_checkbox = QCheckBox("详细日志", settings_group)
        self._verbose_checkbox.setChecked(bool(self._settings.value("desktop/verbose", verbose, type=bool)))

        config_row = QWidget(settings_group)
        config_layout = QHBoxLayout(config_row)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(8)
        config_layout.addWidget(self._config_input, 1)
        config_layout.addWidget(self._browse_config_button)
        settings_layout.addWidget(QLabel("配置文件路径", settings_group))
        settings_layout.addWidget(config_row)
        settings_layout.addWidget(self._verbose_checkbox)
        search_layout.addWidget(settings_group)
        layout.addWidget(search_card)

        actions_card, actions_layout = self._create_card("操作")
        self._preview_button = self._create_button("预览筛选", variant="secondary")
        self._run_button = self._create_button("开始下载")
        self._refresh_button = self._create_button("刷新状态", variant="secondary")
        self._preview_button.clicked.connect(lambda *_: self._run_preview())
        self._run_button.clicked.connect(lambda *_: self._run_download())
        self._refresh_button.clicked.connect(lambda *_: self.refresh_dashboard(validate_session=True))
        actions_layout.addWidget(self._preview_button)
        actions_layout.addWidget(self._run_button)
        actions_layout.addWidget(self._refresh_button)
        layout.addWidget(actions_card)
        layout.addStretch(1)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        kpi_card, kpi_layout = self._create_card("运行概览")
        kpi_grid = QGridLayout()
        kpi_grid.setHorizontalSpacing(10)
        kpi_grid.setVerticalSpacing(10)
        for index, (key, title, hint) in enumerate(
            [
                ("status", "最近任务状态", "以右侧详情选中的任务为准"),
                ("candidate", "候选笔记", "搜索结果总量"),
                ("matched", "命中笔记", "按阈值筛选后的结果"),
                ("downloads", "下载成功 / 失败", "仅统计当前任务"),
            ]
        ):
            row = index // 2
            column = index % 2
            kpi_grid.addWidget(self._create_kpi_card(title, key, hint), row, column)
        kpi_layout.addLayout(kpi_grid)
        layout.addWidget(kpi_card)

        jobs_card, jobs_layout = self._create_card("任务历史")
        self._jobs_table = self._create_table_view()
        self._jobs_table.setModel(self._jobs_model)
        self._jobs_table.selectionModel().selectionChanged.connect(lambda *_: self._handle_job_selection_changed())
        jobs_layout.addWidget(self._jobs_table)
        layout.addWidget(jobs_card, 1)

        logs_card, logs_layout = self._create_card("运行日志")
        self._log_output = QPlainTextEdit(logs_card)
        self._log_output.setReadOnly(True)
        self._log_output.setMaximumBlockCount(800)
        logs_layout.addWidget(self._log_output)
        layout.addWidget(logs_card, 1)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        detail_card, detail_layout = self._create_card("任务详情")
        self._tabs = QTabWidget(detail_card)
        self._tabs.addTab(self._build_summary_tab(), "任务摘要")
        self._tabs.addTab(self._build_notes_tab(), "命中笔记")
        self._tabs.addTab(self._build_failed_tab(), "失败任务")
        detail_layout.addWidget(self._tabs)
        layout.addWidget(detail_card, 1)
        return panel

    def _create_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(self)
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        title_label = QLabel(title, card)
        title_label.setObjectName("CardTitle")
        layout.addWidget(title_label)
        return card, layout

    def _create_kpi_card(self, title: str, key: str, hint: str) -> QFrame:
        card = QFrame(self)
        card.setObjectName("KpiCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)
        title_label = QLabel(title, card)
        title_label.setObjectName("KpiTitle")
        value_label = QLabel("-", card)
        value_label.setObjectName("KpiValue")
        hint_label = QLabel(hint, card)
        hint_label.setObjectName("KpiHint")
        hint_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(hint_label)
        self._kpi_values[key] = value_label
        self._kpi_hints[key] = hint_label
        return card

    def _create_button(self, text: str, variant: str = "") -> QPushButton:
        button = QPushButton(text, self)
        if variant:
            button.setProperty("variant", variant)
            button.style().unpolish(button)
            button.style().polish(button)
        return button

    def _create_table_view(self) -> QTableView:
        table = QTableView(self)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        return table

    def _build_summary_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        for key, label in [
            ("run_id", "运行 ID"),
            ("status", "当前状态"),
            ("output_dir", "输出目录"),
            ("updated_at", "更新时间"),
            ("message", "状态说明"),
            ("candidate_count", "候选数量"),
            ("matched_count", "命中数量"),
            ("downloads", "下载结果"),
        ]:
            value_label = QLabel("-", tab)
            value_label.setWordWrap(True)
            self._summary_labels[key] = value_label
            form.addRow(label, value_label)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._open_summary_output_button = self._create_button("打开输出目录", variant="secondary")
        self._open_summary_output_button.clicked.connect(lambda *_: self._open_current_output_dir())
        buttons.addWidget(self._open_summary_output_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return tab

    def _build_notes_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self._notes_table = self._create_table_view()
        self._notes_table.setModel(self._notes_model)
        self._notes_table.selectionModel().selectionChanged.connect(lambda *_: self._sync_ui_state())
        self._notes_table.doubleClicked.connect(lambda *_: self._open_selected_note_link())
        layout.addWidget(self._notes_table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._open_note_button = self._create_button("打开笔记链接", variant="secondary")
        self._open_note_button.clicked.connect(lambda *_: self._open_selected_note_link())
        buttons.addWidget(self._open_note_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return tab

    def _build_failed_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self._failed_table = self._create_table_view()
        self._failed_table.setModel(self._failed_model)
        self._failed_table.selectionModel().selectionChanged.connect(lambda *_: self._sync_ui_state())
        layout.addWidget(self._failed_table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._resume_button = self._create_button("恢复下载")
        self._resume_button.clicked.connect(lambda *_: self._resume_selected_run())
        self._open_failed_output_button = self._create_button("打开输出目录", variant="secondary")
        self._open_failed_output_button.clicked.connect(lambda *_: self._open_selected_failed_output())
        self._open_failed_note_button = self._create_button("打开笔记链接", variant="secondary")
        self._open_failed_note_button.clicked.connect(lambda *_: self._open_selected_failed_note())
        buttons.addWidget(self._resume_button)
        buttons.addWidget(self._open_failed_output_button)
        buttons.addWidget(self._open_failed_note_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return tab

    def _restore_settings(self) -> None:
        geometry = self._settings.value("desktop/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        splitter_state = self._settings.value("desktop/splitter_state")
        if splitter_state:
            self._splitter.restoreState(splitter_state)
        else:
            self._splitter.setSizes([360, 520, 560])

    def closeEvent(self, event: QCloseEvent) -> None:
        self._settings.setValue("desktop/geometry", self.saveGeometry())
        self._settings.setValue("desktop/splitter_state", self._splitter.saveState())
        self._settings.setValue("desktop/config_path", self._config_input.text().strip() or "config.toml")
        self._settings.setValue("desktop/output_dir", self._output_input.text().strip())
        self._settings.setValue("desktop/verbose", self._verbose_checkbox.isChecked())
        if self._login_confirmation_event is not None:
            self._login_confirmation_event.set()
        super().closeEvent(event)

    def refresh_dashboard(self, validate_session: bool, selected_run_id: Optional[str] = None) -> None:
        services = self._ensure_services()
        if services is None:
            return

        if validate_session:
            self._append_log("正在刷新状态并校验当前登录态。")
        else:
            self._append_log("正在从本地记录刷新任务看板。")

        def task() -> Dict[str, Any]:
            session_status = services["auth"].get_session_status(validate=validate_session)
            jobs = services["workflow"].list_jobs(limit=50)["jobs"]
            run_id = selected_run_id or self._state.selected_run_id
            if run_id and run_id not in {job.run_id for job in jobs}:
                run_id = ""
            if not run_id and jobs:
                run_id = jobs[0].run_id
            details = services["workflow"].get_run_details(run_id) if run_id else {}
            return {
                "session_status": session_status,
                "jobs": jobs,
                "selected_run_id": run_id or "",
                "details": details,
            }

        self._start_worker("refresh", task, self._handle_snapshot_loaded, error_context="刷新状态")

    def _start_login(self) -> None:
        if self._state.pending_login_confirmation:
            return
        services = self._ensure_services()
        if services is None:
            return

        self._clear_alert()
        self._state.pending_login_confirmation = True
        self._state.login_confirmation_sent = False
        self._login_confirmation_event = Event()
        self._append_log("已发起登录：外部浏览器会打开，请完成登录后点击“已完成登录并保存”。")
        self._show_alert("info", "浏览器已准备打开，请在小红书页面完成登录后回到工作台点击“已完成登录并保存”。")
        self._sync_ui_state()

        def task() -> Dict[str, Any]:
            session = services["auth"].login(wait_for_confirmation=self._login_confirmation_event.wait)
            status = services["auth"].get_session_status(validate=True)
            return {"session": session, "session_status": status}

        self._start_worker("login", task, self._handle_login_success, error_context="登录")

    def _confirm_login(self) -> None:
        if self._login_confirmation_event is None or self._state.login_confirmation_sent:
            return
        self._state.login_confirmation_sent = True
        self._login_confirmation_event.set()
        self._append_log("已确认登录完成，正在保存会话并校验登录态。")
        self._sync_ui_state()

    def _run_preview(self) -> None:
        services = self._ensure_services()
        if services is None:
            return
        params = self._collect_search_params()
        if params is None:
            return

        self._clear_alert()
        self._append_log(f"开始预览关键词“{params['keyword']}”的筛选结果。")

        def task() -> Dict[str, Any]:
            return services["workflow"].preview(**params)

        self._start_worker("preview", task, self._handle_preview_success, error_context="预览筛选")

    def _run_download(self) -> None:
        services = self._ensure_services()
        if services is None:
            return
        params = self._collect_search_params(include_output_dir=True)
        if params is None:
            return

        self._clear_alert()
        self._append_log(f"开始下载关键词“{params['keyword']}”的命中笔记。")

        def task() -> Dict[str, Any]:
            return services["workflow"].run(**params)

        self._start_worker("run", task, self._handle_run_success, error_context="开始下载")

    def _resume_selected_run(self) -> None:
        services = self._ensure_services()
        if services is None:
            return
        run_id = self._state.selected_run_id
        if not run_id:
            self._show_alert("warning", "当前没有可恢复的任务，请先在任务列表中选择一个任务。")
            return

        self._clear_alert()
        self._append_log(f"开始恢复任务 {run_id} 的失败下载。")

        def task() -> Dict[str, Any]:
            return services["workflow"].resume(run_id)

        self._start_worker("resume", task, self._handle_resume_success, error_context="恢复下载")

    def _start_worker(
        self,
        busy_action: str,
        fn: Callable[[], Any],
        on_success: Callable[[Any], None],
        error_context: str,
    ) -> None:
        worker = ServiceWorker(fn)
        self._state.busy_action = busy_action
        self._sync_ui_state()

        worker.signals.succeeded.connect(on_success)
        worker.signals.failed.connect(lambda exc: self._handle_worker_error(error_context, exc))
        worker.signals.finished.connect(lambda: self._handle_worker_finished(busy_action))
        self._thread_pool.start(worker)

    def _handle_worker_finished(self, busy_action: str) -> None:
        if self._state.busy_action == busy_action:
            self._state.busy_action = ""
        self._sync_ui_state()

    def _handle_worker_error(self, context: str, exc: Exception) -> None:
        if isinstance(exc, AuthExpiredError):
            self._state.session_status["is_valid"] = False
            self._show_alert("error", f"{context}失败：{exc}")
        elif isinstance(exc, RateLimitedError):
            self._show_alert("warning", f"{context}触发限流或验证，请稍后恢复任务。")
        elif isinstance(exc, (DependencyMissingError, DownloadError, ParseError, XHSError)):
            self._show_alert("warning", f"{context}失败：{exc}")
        else:
            self._show_alert("error", f"{context}失败：{exc}")

        if self._state.pending_login_confirmation:
            self._state.pending_login_confirmation = False
            self._state.login_confirmation_sent = False
            self._login_confirmation_event = None

        self._append_log(f"{context}失败：{exc}")
        self._sync_ui_state()

    def _handle_login_success(self, payload: Dict[str, Any]) -> None:
        self._state.pending_login_confirmation = False
        self._state.login_confirmation_sent = False
        self._login_confirmation_event = None
        self._state.session_status = payload["session_status"]
        self._append_log("登录成功，已保存会话并更新状态。")
        self._show_alert("success", "登录态已保存，后续预览和下载操作已可用。")
        self._apply_session_status()
        self.refresh_dashboard(validate_session=False)

    def _handle_preview_success(self, result: Dict[str, Any]) -> None:
        self._append_log(
            f"预览完成：run_id={result['run_id']}，候选 {result['candidate_count']}，命中 {result['matched_count']}。"
        )
        self._show_alert("success", f"预览完成：候选 {result['candidate_count']}，命中 {result['matched_count']}。")
        self.refresh_dashboard(validate_session=False, selected_run_id=result["run_id"])

    def _handle_run_success(self, result: Dict[str, Any]) -> None:
        stats = result.get("stats", {})
        self._append_log(
            f"下载完成：run_id={result['run_id']}，成功 {stats.get('download_success', 0)}，失败 {stats.get('download_failed', 0)}。"
        )
        self._show_alert("success", result.get("message", "下载流程已完成。"))
        self.refresh_dashboard(validate_session=False, selected_run_id=result["run_id"])

    def _handle_resume_success(self, result: Dict[str, Any]) -> None:
        self._append_log(f"恢复下载完成：run_id={result['run_id']}。")
        self._show_alert("success", result.get("message", "恢复下载已完成。"))
        self.refresh_dashboard(validate_session=False, selected_run_id=result["run_id"])

    def _append_log(self, message: str) -> None:
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        if hasattr(self, "_log_output"):
            self._log_output.appendPlainText(f"[{timestamp}] {message}")

    def _handle_snapshot_loaded(self, snapshot: Dict[str, Any]) -> None:
        self._state.session_status = snapshot["session_status"]
        self._state.jobs = snapshot["jobs"]
        self._state.selected_run_id = snapshot["selected_run_id"]
        self._state.current_details = snapshot["details"]

        self._apply_session_status()
        self._jobs_model.set_rows(self._state.jobs)
        self._select_job_row(self._state.selected_run_id)
        self._apply_run_details(self._state.current_details)
        self._append_log("看板数据已刷新。")
        self._sync_ui_state()

    def _apply_session_status(self) -> None:
        status = self._state.session_status
        if not status.get("has_session"):
            text = "未登录"
            colors = ("#E2E8F0", "#475569")
            hint = "未检测到本地登录态，请先完成登录。"
        elif status.get("is_valid"):
            text = "登录有效"
            colors = ("#CCFBF1", "#0F766E")
            session = status.get("session")
            path_text = getattr(session, "storage_state_path", "")
            hint = f"会话文件：{path_text}" if path_text else "登录态有效，可以直接执行预览和下载。"
        else:
            text = "登录失效"
            colors = ("#FEE2E2", "#991B1B")
            hint = "检测到已有会话，但当前登录态已失效，请重新登录。"

        self._session_badge.setText(text)
        self._session_badge.setStyleSheet(
            f"background: {colors[0]}; color: {colors[1]}; border: 1px solid {colors[0]};"
        )
        self._session_hint.setText(hint)
        last_checked = status.get("last_checked_at") or "-"
        self._session_checked.setText(f"最近校验: {last_checked}")

    def _apply_run_details(self, details: Dict[str, Any]) -> None:
        if not details:
            for label in self._summary_labels.values():
                label.setText("-")
            self._notes_model.set_rows([])
            self._failed_model.set_rows([])
            self._set_kpi("status", "-", "暂无任务")
            self._set_kpi("candidate", "-", "暂无统计")
            self._set_kpi("matched", "-", "暂无统计")
            self._set_kpi("downloads", "-", "暂无统计")
            return

        job = details["job"]
        stats = details.get("stats", {})
        matched_summaries = details.get("matched_summaries", [])
        record_map = {record.note_id: record for record in details.get("records", [])}

        note_rows = [
            NoteRow(
                note_id=summary.note_id,
                title=getattr(record_map.get(summary.note_id), "title", summary.title),
                author_name=getattr(record_map.get(summary.note_id), "author_name", summary.author_name),
                like_count=summary.like_count,
                comment_count=summary.comment_count,
                note_url=getattr(record_map.get(summary.note_id), "note_url", summary.note_url),
            )
            for summary in matched_summaries
        ]
        self._notes_model.set_rows(note_rows)
        note_urls = {row.note_id: row.note_url for row in note_rows}
        self._failed_model.from_tasks(details.get("failed_tasks", []), note_urls)

        self._summary_labels["run_id"].setText(job.run_id)
        self._summary_labels["status"].setText(display_status(job.status))
        self._summary_labels["output_dir"].setText(job.output_dir or "-")
        self._summary_labels["updated_at"].setText(getattr(job, "updated_at", "-"))
        self._summary_labels["message"].setText(job.message or "-")
        self._summary_labels["candidate_count"].setText(str(stats.get("summary_count", 0)))
        self._summary_labels["matched_count"].setText(str(len(matched_summaries)))
        self._summary_labels["downloads"].setText(
            f"成功 {stats.get('download_success', 0)} / 失败 {stats.get('download_failed', 0)}"
        )

        self._set_kpi("status", display_status(job.status), "以右侧详情选中的任务为准")
        self._set_kpi("candidate", str(stats.get("summary_count", 0)), "搜索结果总量")
        self._set_kpi("matched", str(len(matched_summaries)), "按阈值筛选后的结果")
        self._set_kpi(
            "downloads",
            f"{stats.get('download_success', 0)} / {stats.get('download_failed', 0)}",
            "下载成功 / 失败",
        )

    def _set_kpi(self, key: str, value: str, hint: str) -> None:
        self._kpi_values[key].setText(value)
        self._kpi_hints[key].setText(hint)

    def _select_job_row(self, run_id: str) -> None:
        self._selection_locked = True
        try:
            selection_model = self._jobs_table.selectionModel()
            if selection_model is None:
                return
            if not run_id:
                selection_model.clearSelection()
                return
            for row in range(self._jobs_model.rowCount()):
                item = self._jobs_model.row_at(row)
                if item is not None and item.run_id == run_id:
                    self._jobs_table.selectRow(row)
                    return
            selection_model.clearSelection()
        finally:
            self._selection_locked = False

    def _handle_job_selection_changed(self) -> None:
        if self._selection_locked:
            return
        selection_model = self._jobs_table.selectionModel()
        indexes = selection_model.selectedRows() if selection_model else []
        if not indexes:
            self._state.selected_run_id = ""
            self._state.current_details = {}
            self._apply_run_details({})
            self._sync_ui_state()
            return

        job = self._jobs_model.row_at(indexes[0].row())
        if job is None or job.run_id == self._state.selected_run_id:
            return

        self._state.selected_run_id = job.run_id
        self._append_log(f"已切换到任务 {job.run_id}，正在加载详情。")
        services = self._ensure_services()
        if services is None:
            return

        def task() -> Dict[str, Any]:
            return services["workflow"].get_run_details(job.run_id)

        self._start_worker("details", task, self._handle_detail_success, error_context="加载任务详情")

    def _handle_detail_success(self, details: Dict[str, Any]) -> None:
        self._state.current_details = details
        self._state.selected_run_id = details["job"].run_id
        self._apply_run_details(details)
        self._sync_ui_state()

    def _collect_search_params(self, include_output_dir: bool = False) -> Optional[Dict[str, Any]]:
        keyword = self._keyword_input.text().strip()
        if not keyword:
            self._show_alert("warning", "请先输入搜索关键词。")
            return None

        params: Dict[str, Any] = {
            "keyword": keyword,
            "pages": self._pages_spin.value(),
            "sort": self._sort_combo.currentData(),
            "min_likes": self._min_likes_spin.value(),
            "min_comments": self._min_comments_spin.value(),
        }
        if include_output_dir:
            output_dir = self._output_input.text().strip()
            params["output_dir"] = output_dir or None
        return params

    def _ensure_services(self) -> Optional[Dict[str, Any]]:
        config_path = self._config_input.text().strip() or "config.toml"
        verbose = self._verbose_checkbox.isChecked()
        if self._services is not None and config_path == self._loaded_config_path and verbose == self._loaded_verbose:
            return self._services

        try:
            configure_logging(verbose)
            self._services = self._service_factory(config_path)
        except Exception as exc:
            self._services = None
            self._loaded_config_path = ""
            self._loaded_verbose = False
            self._state.jobs = []
            self._state.current_details = {}
            self._show_alert("error", f"加载配置或服务失败：{exc}")
            self._append_log(f"加载配置或服务失败：{exc}")
            self._sync_ui_state()
            return None

        self._loaded_config_path = config_path
        self._loaded_verbose = verbose
        self._state.config_path = config_path
        self._state.output_dir_override = self._output_input.text().strip()
        return self._services

    def _show_alert(self, level: str, message: str) -> None:
        styles = {
            "info": ("#CCFBF1", "#115E59"),
            "success": ("#DCFCE7", "#166534"),
            "warning": ("#FFEDD5", "#C2410C"),
            "error": ("#FEE2E2", "#991B1B"),
        }
        background, foreground = styles.get(level, styles["info"])
        self._banner.setText(message)
        self._banner.setStyleSheet(
            f"background: {background}; color: {foreground}; border: 1px solid {background};"
        )
        self._banner.show()

    def _clear_alert(self) -> None:
        self._banner.clear()
        self._banner.hide()

    def _sync_ui_state(self) -> None:
        has_valid_session = bool(self._state.session_status.get("is_valid"))
        busy = bool(self._state.busy_action)
        has_run = bool(self._state.selected_run_id)
        failed_selected = self._selected_failed_task() is not None
        note_selected = self._selected_note_row() is not None
        has_failed_tasks = self._failed_model.rowCount() > 0

        self._start_login_button.setEnabled(not busy and not self._state.pending_login_confirmation)
        self._confirm_login_button.setEnabled(
            self._state.pending_login_confirmation and not self._state.login_confirmation_sent
        )
        self._preview_button.setEnabled(has_valid_session and not busy)
        self._run_button.setEnabled(has_valid_session and not busy)
        self._refresh_button.setEnabled(not busy and not self._state.pending_login_confirmation)
        self._resume_button.setEnabled(has_valid_session and not busy and has_run and has_failed_tasks)
        self._open_summary_output_button.setEnabled(bool(self._summary_labels["output_dir"].text() != "-"))
        self._open_note_button.setEnabled(note_selected)
        self._open_failed_output_button.setEnabled(failed_selected)
        self._open_failed_note_button.setEnabled(failed_selected and bool(self._selected_failed_task().note_url))

        if self._state.pending_login_confirmation:
            self._confirm_login_button.setText(
                "正在保存..." if self._state.login_confirmation_sent else "已完成登录并保存"
            )
        else:
            self._confirm_login_button.setText("已完成登录并保存")

    def _selected_note_row(self) -> Optional[NoteRow]:
        selection_model = self._notes_table.selectionModel()
        if selection_model is None or not selection_model.selectedRows():
            return None
        return self._notes_model.row_at(selection_model.selectedRows()[0].row())

    def _selected_failed_task(self) -> Optional[FailedTaskRow]:
        selection_model = self._failed_table.selectionModel()
        if selection_model is None or not selection_model.selectedRows():
            return None
        return self._failed_model.row_at(selection_model.selectedRows()[0].row())

    def _open_selected_note_link(self) -> None:
        row = self._selected_note_row()
        if row is None or not row.note_url:
            self._show_alert("warning", "当前没有可打开的笔记链接。")
            return
        QDesktopServices.openUrl(QUrl(row.note_url))

    def _open_selected_failed_note(self) -> None:
        row = self._selected_failed_task()
        if row is None or not row.note_url:
            self._show_alert("warning", "失败任务缺少笔记链接，请先查看命中笔记。")
            return
        QDesktopServices.openUrl(QUrl(row.note_url))

    def _open_selected_failed_output(self) -> None:
        row = self._selected_failed_task()
        if row is None:
            self._show_alert("warning", "请先选择一个失败任务。")
            return
        self._open_path(row.output_dir)

    def _open_current_output_dir(self) -> None:
        output_dir = self._summary_labels["output_dir"].text()
        if not output_dir or output_dir == "-":
            self._show_alert("warning", "当前任务没有输出目录。")
            return
        self._open_path(output_dir)

    def _open_path(self, raw_path: str) -> None:
        path = Path(raw_path)
        if not path.exists():
            self._show_alert("warning", f"路径不存在：{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _browse_config_path(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "选择配置文件",
            self._config_input.text().strip() or str(Path.cwd()),
            "TOML Files (*.toml);;All Files (*)",
        )
        if selected:
            self._config_input.setText(selected)

    def _browse_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择输出目录",
            self._output_input.text().strip() or str(Path.cwd()),
        )
        if selected:
            self._output_input.setText(selected)


def launch_window(
    app: QApplication,
    config_path: str = "config.toml",
    verbose: bool = False,
    service_factory: ServiceFactory = build_services,
    settings: Optional[QSettings] = None,
) -> int:
    app.setApplicationName("小红书下载工作台")
    app.setOrganizationName("OpenAI")
    window = DesktopMainWindow(config_path=config_path, verbose=verbose, service_factory=service_factory, settings=settings)
    window.show()
    return app.exec()
