import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhs_downloader.adapters.browser import PlaywrightBrowserSession
from xhs_downloader.config import AppConfig
from xhs_downloader.domain.errors import RateLimitedError
from xhs_downloader.domain.models import DownloadTask, NoteSummary, TaskStatus


class FakePage:
    def __init__(self) -> None:
        self._closed = False

    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True

    def bring_to_front(self) -> None:
        return None

    def screenshot(self, path: str, full_page: bool = True) -> None:
        Path(path).write_bytes(b"fake")


class FakeResponse:
    def __init__(self, status: int, headers: dict[str, str], content: bytes) -> None:
        self.status = status
        self.headers = headers
        self._content = content

    def body(self) -> bytes:
        return self._content


class FakeRequestClient:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    def get(self, url: str, headers: dict[str, str], timeout: int) -> FakeResponse:
        return self._response


class FakeContext:
    def __init__(self, response: FakeResponse) -> None:
        self.request = FakeRequestClient(response)
        self.closed = False

    def new_page(self) -> FakePage:
        return FakePage()

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakePlaywright:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def build_config(root: Path) -> AppConfig:
    return AppConfig(
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


class BrowserSessionTests(unittest.TestCase):
    def test_build_note_record_prefers_real_detail_page_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session = PlaywrightBrowserSession(
                FakePlaywright(),
                FakeBrowser(),
                FakeContext(FakeResponse(200, {"content-type": "image/jpeg"}, b"image-bytes")),
                build_config(root),
            )
            summary = NoteSummary(
                note_id="note_1",
                title="标题",
                author_name="作者",
                like_count=1,
                comment_count=1,
                note_url="https://www.xiaohongshu.com/explore/note_1",
                search_rank=1,
            )
            record = session._build_note_record(
                summary,
                {
                    "title": "详情标题",
                    "description": "描述",
                    "author": "详情作者",
                    "bodyText": "详情正文",
                    "tags": ["测试"],
                    "pageUrl": "https://www.xiaohongshu.com/explore/note_1?xsec_token=test&xsec_source=pc_search",
                    "images": [
                        {
                            "src": "https://example.com/image.jpg",
                            "width": 640,
                            "height": 640,
                            "alt": "",
                        }
                    ],
                },
            )

            self.assertEqual(
                "https://www.xiaohongshu.com/explore/note_1?xsec_token=test&xsec_source=pc_search",
                record.note_url,
            )
            session.close()

    def test_build_note_record_prefers_note_slider_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session = PlaywrightBrowserSession(
                FakePlaywright(),
                FakeBrowser(),
                FakeContext(FakeResponse(200, {"content-type": "image/jpeg"}, b"image-bytes")),
                build_config(root),
            )
            summary = NoteSummary(
                note_id="note_2",
                title="标题",
                author_name="作者",
                like_count=1,
                comment_count=1,
                note_url="https://www.xiaohongshu.com/explore/note_2",
                search_rank=1,
            )
            record = session._build_note_record(
                summary,
                {
                    "title": "详情标题",
                    "description": "描述",
                    "author": "详情作者",
                    "bodyText": "详情正文",
                    "tags": ["测试"],
                    "pageUrl": "https://www.xiaohongshu.com/explore/note_2?xsec_token=test",
                    "noteImages": [
                        {
                            "src": "https://example.com/slider-1.jpg",
                            "width": 640,
                            "height": 640,
                            "alt": "",
                        },
                        {
                            "src": "https://example.com/slider-2.jpg",
                            "width": 640,
                            "height": 640,
                            "alt": "",
                        },
                    ],
                    "images": [
                        {
                            "src": "https://picasso-static.xiaohongshu.com/fe-platform/test.png",
                            "width": 200,
                            "height": 200,
                            "alt": "",
                        }
                    ],
                },
            )

            self.assertEqual(
                ["https://example.com/slider-1.jpg", "https://example.com/slider-2.jpg"],
                record.images,
            )
            session.close()

    def test_download_image_uses_browser_context_and_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session = PlaywrightBrowserSession(
                FakePlaywright(),
                FakeBrowser(),
                FakeContext(FakeResponse(200, {"content-type": "image/jpeg"}, b"image-bytes")),
                build_config(root),
            )
            task = DownloadTask(
                task_id="task_1",
                run_id="run_1",
                note_id="note_1",
                asset_id="asset_1",
                source_url="https://example.com/1.jpg",
                filename="001.jpg",
                output_dir=str(root / "downloads" / "note_1"),
                retry_count=0,
                status=TaskStatus.PENDING,
            )

            target = session.download_image(task, "https://www.xiaohongshu.com/explore/note_1")

            self.assertTrue(target.exists())
            self.assertEqual(b"image-bytes", target.read_bytes())
            session.close()

    def test_download_image_detects_html_verification_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session = PlaywrightBrowserSession(
                FakePlaywright(),
                FakeBrowser(),
                FakeContext(FakeResponse(200, {"content-type": "text/html"}, "访问验证".encode("utf-8"))),
                build_config(root),
            )
            task = DownloadTask(
                task_id="task_2",
                run_id="run_1",
                note_id="note_1",
                asset_id="asset_2",
                source_url="https://example.com/2.jpg",
                filename="002.jpg",
                output_dir=str(root / "downloads" / "note_1"),
                retry_count=0,
                status=TaskStatus.PENDING,
            )

            with self.assertRaises(RateLimitedError):
                session.download_image(task, "https://www.xiaohongshu.com/explore/note_1")
            session.close()
