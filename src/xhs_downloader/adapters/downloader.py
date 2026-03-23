from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import AppConfig
from ..domain.errors import DownloadError
from ..domain.models import DownloadTask
from ..infra.logging import get_logger
from ..infra.utils import ensure_directory


class ImageDownloader:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._logger = get_logger(self.__class__.__name__)

    def download(self, task: DownloadTask) -> Path:
        output_dir = ensure_directory(Path(task.output_dir))
        target_path = output_dir / task.filename
        if target_path.exists() and target_path.stat().st_size > 0:
            self._logger.debug("文件已存在，跳过下载: %s", target_path)
            return target_path

        last_error = None
        temp_path = Path(f"{target_path}.part")
        headers = {"User-Agent": self._config.user_agent, "Referer": "https://www.xiaohongshu.com/"}
        for attempt in range(self._config.max_retries + 1):
            try:
                request = urllib.request.Request(task.source_url, headers=headers)
                with urllib.request.urlopen(request, timeout=self._config.download_timeout) as response:
                    content_type = response.headers.get_content_type().lower()
                    content = response.read()
                if not content:
                    raise DownloadError("下载内容为空")
                if not content_type.startswith("image/"):
                    raise DownloadError(f"图片资源不可用: content_type={content_type}, url={task.source_url}")
                temp_path.write_bytes(content)
                temp_path.replace(target_path)
                return target_path
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                self._logger.warning(
                    "下载失败，准备重试: task_id=%s, attempt=%s, error=%s",
                    task.task_id,
                    attempt + 1,
                    exc,
                )
                if attempt < self._config.max_retries:
                    time.sleep(min(2 ** attempt, 5))
            finally:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        self._logger.debug("临时文件清理失败: %s", temp_path, exc_info=True)

        raise DownloadError(f"下载失败: {task.source_url} - {last_error}")
