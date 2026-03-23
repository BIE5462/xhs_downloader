import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhs_downloader.cli import _write_console_text


class GbkStream:
    def __init__(self) -> None:
        self.encoding = "gbk"
        self.buffer = io.BytesIO()
        self.flush_count = 0

    def write(self, text: str) -> int:
        text.encode(self.encoding)
        self.buffer.write(text.encode(self.encoding))
        return len(text)

    def flush(self) -> None:
        self.flush_count += 1


class CliOutputTests(unittest.TestCase):
    def test_write_console_text_uses_backslashreplace_for_gbk_stdout(self) -> None:
        stream = GbkStream()

        _write_console_text('{"title":"配色指南🎨"}', stream=stream)

        rendered = stream.buffer.getvalue().decode("gbk")
        self.assertIn("\\U0001f3a8", rendered)
        self.assertTrue(rendered.endswith("\n"))
        self.assertGreaterEqual(stream.flush_count, 1)

    def test_write_console_text_writes_plain_text_without_changes(self) -> None:
        stream = io.StringIO()

        _write_console_text('{"title":"普通文本"}', stream=stream)

        self.assertEqual('{"title":"普通文本"}\n', stream.getvalue())
